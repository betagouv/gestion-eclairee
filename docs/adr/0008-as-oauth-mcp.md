# Serveur d'autorisation OAuth2 (Django) pour le MCP

Statut : accepté

Le serveur MCP expose des outils d'analyse des dépenses à des agents (OpenCode,
Cursor). ProConnect ne permet ni l'enregistrement dynamique de clients
(RFC 7591), ni la métadonnée de client par URL (CIMD), et n'émet pas
d'audience dédiée, mais rien n'empêche de jouer le rôle d'Authorization
Server côté Django. L'authentification passe donc par un Authorization Server
OAuth2 porté par Django (django-oauth-toolkit >= 3.4), avec des clients
pré-enregistrés par l'admin Django : Authorization Code + PKCE S256.

## Architecture

```
agent MCP --Bearer access_token--> mcpserver (passe-plat, sans état)
                                         | forward du Bearer tel quel
                                         v
                           Django /api/ (DRF + OAuth2ProtectedResourceAuthentication)
                                         ^
                            Django = AS : /oauth/authorize, /oauth/token,
                            /oauth/revoke_token
                           + /.well-known/oauth-authorization-server (racine, RFC 8414 strict)
                           + /.well-known/oauth-protected-resource (RFC 9728)
```

Le document RFC 9728 (protected resource metadata) est servi par Django,
source de vérité unique, et pointe vers l'URL publique du MCP
(`MCP_PUBLIC_URL`). Le 401 du process `mcp` renvoie un `WWW-Authenticate`
avec `resource_metadata` pointant vers ce document ; la validation du jeton
reste du ressort de `/api/`.

## Décisions

- **AS** : django-oauth-toolkit >= 3.4 (`OAUTH2_PROVIDER`), modèle
  `Application` remplacé par `gesec.OAuthApplication` (défini dans `gesec/common/models.py`)
  (`OAUTH2_PROVIDER_APPLICATION_MODEL`).
 - **Whitelist des routes sous `/oauth/`** : seules `authorize/`, `token/` et
   `revoke_token/` sont montées (namespace `oauth2_provider` conservé). Le reste
   de `oauth2_provider.urls` — vues de management `applications/*` /
   `authorized_tokens/*`, device flow, introspection RFC 7662 (inutilisable :
   scope `introspection` absent de `SCOPES`), DCR, endpoints OIDC — n'est pas
   exposé.
 - **Clients pré-enregistrés par l'admin, DCR désactivé** : la création de
  clients passe uniquement par l'admin Django (`ApplicationAdmin` de DOT,
  enregistré sur `OAuthApplication`) ; un client partagé se crée avec
  `user=None`. `DCR_ENABLED` est laissé à `False` (défaut DOT) :
  `/oauth/register/` répond 404 et les métadonnées n'annoncent pas de
  `registration_endpoint`. Les agents (ex. OpenCode) utilisent le
  `client_id` du client pré-enregistré (`oauth.client_id`, aucun secret).
 - **Redirect URIs loopback uniquement, chemin exact** : `OAuthApplication.clean()`
   n'accepte que des hôtes de boucle locale `http(s)://127.0.0.1[:port][/chemin]` /
   `http(s)://[::1][:port][/chemin]` (pas `localhost`, RFC 8252 §8.3) ; le contrôle
   passe par le `full_clean()` du formulaire admin, qui enregistre donc le chemin
   exact du callback (ex. `http://127.0.0.1/callback` — le callback par défaut
   d'OpenCode écoute sur `127.0.0.1` avec un port éphémère et le chemin
   `/callback`, configurable via `oauth.redirect_uri`). À l'exécution,
   `OAuthApplication.redirect_uri_allowed()` refuse toute URI non loopback puis
   délègue à DOT le match exact (schéma, hôte, chemin et query identiques) : le
   port reste libre pour les IP loopback en `http` (RFC 8252 §7.3), le chemin
   doit correspondre exactement à une URI enregistrée. Le code reste protégé par
   le PKCE S256 obligatoire.
- **Clients publics uniquement** (`token_endpoint_auth_method: none`) et
  **flux authorization code uniquement**, imposés aussi par
  `OAuthApplication.clean()`.
- **PKCE S256 obligatoire** : `PKCE_REQUIRED=True` +
  `COMPLIANT_BCP_RFC9700_PKCE_METHOD=True` (rejette `plain`).
- **Access tokens opaques**, vérifiés en ligne en base, hashés au repos
  (`COMPLIANT_BCP_RFC9700_TOKEN_STORAGE=True`, incompatible avec
  `REFRESH_TOKEN_GRACE_PERIOD_SECONDS` non nul, laissé à 0).
- **Scope unique** : `data` (`SCOPES` / `DEFAULT_SCOPES`) — marque la
  possibilité d'accéder aux données. Aucun contrôle de scope côté API pour
  l'instant.
- **Permissions API en Django standard** : DRF `IsAuthenticated` par défaut
  (`DEFAULT_PERMISSION_CLASSES`), `DjangoModelPermissions` par ressource pour
  les futures vues `/api/` (ex. `healthcheck` n'exige que d'être authentifié,
  session ou Bearer). Plus de permission custom `access_mcp`.
- **Utilisateurs inactifs rejetés à la validation du jeton** : DOT ne vérifie
  que expiration et scopes dans `is_valid` ; `OAUTH2_VALIDATOR_CLASS` =
  `gesec.front.oauth.GesecOAuth2Validator` rejette en plus les Bearer dont
  l'utilisateur est inactif (401).
- **Écran de consentement** : `oauth2_provider/authorize.html` surchargé en
  DSFR (dans `gesec/templates/`, prioritaire car `oauth2_provider` est après
  `gesec` dans `INSTALLED_APPS`).
- **Audience RFC 8707** : les agents envoient `resource=<MCP_PUBLIC_URL>` à
  l'autorisation, le jeton est donc borné à cette ressource. L'API Django
  (`PUBLIC_BASE_URL`) étant le back-end de la ressource MCP, elle accepte ces
  jetons via `RESOURCE_SERVER_TOKEN_RESOURCE_VALIDATOR` =
  `gesec.front.oauth.validate_token_resource` (sinon DOT comparerait
  l'audience du jeton à l'URI de la requête API et tout jeton serait rejeté).
 - **Métadonnées** : montées à la racine uniquement (`/.well-known/...`, RFC
   8414 strict et RFC 9728, issuer = `PUBLIC_BASE_URL` via `OIDC_ISS_ENDPOINT`)
   ; la forme « fallback » sous `/oauth/.well-known/...` n'est pas servie.
   Les endpoints restent sous `/oauth/` uniquement.
 - **Rate limiting** : `OAuthRateLimitMiddleware` borne les appels à `/oauth/`
   globalement (100/jour, clé globale, `RateLimitCount`). Ce plafond global borne
   aussi les tentatives de brute force sur `/oauth/token/` ; le risque de DoS
   global (un attaquant anonyme épuise le budget pour tous les clients) est
   accepté.
 - **Traçabilité des appels API** : `DEFAULT_AUTHENTICATION_CLASSES` utilise
   `gesec.front.api.auth.LoggingOAuth2Authentication`, qui loggue chaque requête
   `/api/` (méthode, path, utilisateur pk/email, `client_id` de l'application)
   en INFO et les échecs d'authentification en WARNING — jamais le jeton.
- **Révocation** : RFC 7009 (`/oauth/revoke_token/`), suppression du client
  depuis l'admin Django, et backchannel logout ProConnect qui supprime les
  `AccessToken` / `RefreshToken` / `Grant` DOT de l'utilisateur par `sub`
  (`CustomOIDCBackChannelLogoutView` ; la route `oidc/backchannel-logout/`
  est surchargée avant l'include de `lasuite.oidc_login.urls` car la lib ne
  fournit aucun hook de classe pour cette vue, contrairement à
  `OIDC_CALLBACK_CLASS`).

## Variables d'environnement

- `PUBLIC_BASE_URL` : URL publique de Django, issuer OAuth.
- `MCP_PUBLIC_URL` : URL publique du MCP (audience RFC 8707 / ressource RFC
  9728) — doit être exactement l'URL appelée par l'agent pour `/mcp`.
- TTL des jetons en dur dans `gesec/settings.py` : access token 1 h,
  refresh token 10 h avec rotation et protection anti-rejeu.

## Déploiement

Coupure nette assumée : les agents existants cassent ; chaque agent refait
authorize avec le client pré-enregistré créé en prod via l'admin Django
(fenêtre à annoncer). Procfile inchangé.

## Alternatives écartées

- AS externe (ex. ProConnect) : ne permet ni DCR ni CIMD, ni audience dédiée.
- DCR natif (RFC 7591/7592) : retiré — inutile dès lors que les clients sont
  créés par l'admin, et cela réduit la surface d'attaque (plus de
  `registration_access_token` ni d'endpoints de management RFC 7592).
- JWT signés : retirent la révocation immédiate et la lecture des permissions
  à chaque requête.
