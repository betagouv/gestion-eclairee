# Protocole de test local de bout en bout : Django + MCP + client OpenCode

Test manuel du serveur MCP avec un client OpenCode réel, incluant le flux
OAuth complet (Django comme serveur d'autorisation, ProConnect de
l'intégration comme fournisseur d'identité). Voir `docs/adr/0008-as-oauth-mcp.md`
pour l'architecture.

Les identifiants du compte de test ProConnect ne sont pas documentés ici :
les demander à l'utilisateur (environnement d'intégration uniquement).

## Prérequis

- Base PostgreSQL locale migree (`uv run ./manage.py migrate` avec le bon
  `ENV_FILE`) ; la permission `gesec.api_access` doit être accordée à
  l'utilisateur qui va se connecter via ProConnect (sinon
  `meta_budat_query` / `meta_budat_schema` répondent 403).
- Un client OAuth pré-enregistré dans l'admin Django (voir ADR 0008) : client
  public, flux authorization code, redirect URIs de boucle locale
  `http://127.0.0.1/callback` et `http://127.0.0.1/mcp/oauth/callback` (callback
  par défaut d'OpenCode ; le port est libre, le chemin doit correspondre
  exactement). Noter son `client_id` (public, non secret).
- Le serveur Django doit tourner avec l'OIDC de l'intégration ProConnect :
  `OIDC_RP_DOMAIN=fca.integ01.dev-agentconnect.fr` (+ `OIDC_RP_CLIENT_ID` /
  `OIDC_RP_CLIENT_SECRET` de l'intégration), `PUBLIC_BASE_URL=http://127.0.0.1:8000`
  et `MCP_PUBLIC_URL=http://127.0.0.1:9000/mcp`.
- La table `gesec_meta_budat` doit exister pour que `meta_budat_query` réponde
  autre chose qu'un 500 (en local, elle n'est créée que par le pipeline gold ;
  on peut la créer à la main via le schéma du modèle `MetaBudat` et y insérer
  quelques lignes de test).

## 1. Lancer le serveur Django

```sh
ENV_FILE=test.env \
DATABASE_URL=postgres://test:test@127.0.0.1:5544/test \
OIDC_RP_CLIENT_ID=<...> OIDC_RP_CLIENT_SECRET=<...> \
OIDC_RP_DOMAIN=fca.integ01.dev-agentconnect.fr \
PUBLIC_BASE_URL=http://127.0.0.1:8000 \
MCP_PUBLIC_URL=http://127.0.0.1:9000/mcp \
uv run ./manage.py runserver 127.0.0.1:8000 --noreload
```

Vérifier : `curl -s http://127.0.0.1:8000/.well-known/oauth-protected-resource`
renvoie les métadonnées RFC 9728 pointant vers `http://127.0.0.1:8000`.

## 2. Lancer le serveur MCP

```sh
ENV_FILE=test.env \
MCP_BASE_API_URL=http://127.0.0.1:8000 \
MCP_PORT=9000 \
PUBLIC_BASE_URL=http://127.0.0.1:8000 \
uv run python -m mcpserver.server
```

Vérifier : un POST sur `http://127.0.0.1:9000/mcp` sans jeton répond 401 avec
un challenge `WWW-Authenticate: Bearer resource_metadata=...`.

## 3. Configurer le client OpenCode

Créer un répertoire de test avec un `opencode.json` (client pré-enregistré,
pas de DCR) :

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "depenses-local": {
        "type": "remote",
        "url": "http://127.0.0.1:9000/mcp",
        "oauth": {
          "client_id": "<client_id créé dans l'admin Django>",
          "scope": "data"
        }
      }
    }
  }
}
```

Puis, dans ce répertoire : `opencode mcp list` doit montrer `depenses-local`
en `needs authentication`.

## 4. Authentification OAuth (navigateur)

**Attention : le délai d'attente d'OpenCode pour le callback navigateur est
court.** Pour ne pas le rater : se connecter une première fois à la main dans
le navigateur (session ProConnect conservée par les cookies), puis lancer
l'auth et ouvrir l'URL imprimée immédiatement.

1. (Pré-chauffe) Ouvrir `http://127.0.0.1:8000/oidc/authenticate?next=/` dans le
   navigateur et se connecter via ProConnect avec le compte de test de
   l'intégration : page de connexion (email) → page de mot de passe → étape
   de choix de l'organisation (sélectionner le premier bloc proposé devrait
   marcher) → retour sur Django, connecté.
2. `opencode mcp logout depenses-local` (pour repartir de zéro), puis
   `opencode mcp auth depenses-local` : OpenCode imprime l'URL
   `http://127.0.0.1:8000/oauth/authorize/?...` et attend le callback.
3. Ouvrir cette URL dans le même navigateur (déjà authentifié) : l'écran de
   consentement Django « Autoriser … ? » s'affiche directement ; cliquer sur
   « Autoriser ».
4. Le navigateur est redirigé vers `http://127.0.0.1:<port>/callback?code=...`
   ; OpenCode échange le code contre un jeton (PKCE S256) et stocke le
   refresh token. `opencode mcp list` doit alors montrer
   `✓ depenses-local connected (OAuth)`.

## 5. Tester les outils de données MCP

Depuis le répertoire du client, demander à OpenCode en langage naturel
d'interroger la méta-table BUDAT à travers le serveur MCP, par exemple :

```sh
opencode run "Depuis le serveur MCP depenses-local, montre-moi quelques lignes \
de la méta-table BUDAT, filtre sur l'année 2025, et donne-moi le total des \
montants par ministère trié par montant décroissant."
```

L'agent consulte de lui-même `meta_budat_schema` (les descriptions des outils
du serveur le guident) puis appelle `meta_budat_query` (mode lignes puis mode
agrégé `group_by`/`agg`/`ordering`) et rapporte des résultats conformes :
lignes (≤ 100) ou agrégats en HTTP 200 ; 400 si champ inconnu, 403 sans la
permission `gesec.api_access`, 500 si la table `gesec_meta_budat` n'existe pas.

## 6. Nettoyage

```sh
opencode mcp logout depenses-local   # supprime les jetons stockés
# arrêter runserver et mcpserver (Ctrl+C ou kill)
```
