# Sécurité

Mesures de sécurité de l'application (front web + API + serveur MCP).
Les décisions structurantes sont documentées dans les ADR référencés ci-dessous :
ADR 0008 (OAuth2/MCP), ADR 0009 (API meta_budat), ADR 0010 (deux bases de données).

## Authentification

- **Front web** : OIDC ProConnect (lasuite / mozilla-django-oidc), signature RS256,
  scopes `openid email given_name usual_name`, `OIDC_ALLOW_DUPLICATE_EMAILS = False`.
  Backend unique `CustomOIDCBackend` : **aucune authentification par mot de passe**
  (modèle `User` sans champ password, `USERNAME_FIELD = admin_email`).
  (`gesec/settings.py:148-172`, `gesec/front/auth/backends.py`)
- **Backchannel logout** : à la déconnexion ProConnect, tous les tokens OAuth2
  (access, refresh, grants) de l'utilisateur sont supprimés par `sub`.
  (`gesec/front/auth/views.py:10-17`)
- **API / MCP** : Bearer OAuth2 émis par Django, serveur d'autorisation (ADR 0008) :
  - Authorization Code + **PKCE S256 obligatoire** (`plain` rejeté), clients **publics uniquement** ;
  - redirect URIs **loopback uniquement** (127.0.0.1 / [::1], pas `localhost`), match exact au runtime ;
  - **pas de DCR** : clients pré-enregistrés dans l'admin ; seules les routes
    `authorize`, `token`, `revoke-token` sont exposées sous `/oauth/` (le reste → 404) ;
  - tokens **hashés au repos** (RFC 9700), access token 1 h,
    refresh 10 h avec **rotation + protection anti-réutilisation** ;
  - scope unique `data` ; audience RFC 8707 (`resource = MCP_PUBLIC_URL`) validée
    côté API par `validate_token_resource` ;
  - **utilisateurs inactifs rejetés** (401) à la validation du Bearer
    (`GesecOAuth2Validator`).
- **Admin Django** : monté sur un chemin obscurci (`DJANGO_ADMIN_BASE_URL_PATH`),
  login redirigé vers OIDC.
- **Serveur MCP** (`mcpserver/`) : passe-plat stateless — forwarde le Bearer tel quel
  vers `/api/` (Django reste la seule autorité de validation), 401 +
  `WWW-Authenticate: Bearer resource_metadata=...` (RFC 9728) sans jeton,
  protection DNS rebinding activée, bind `127.0.0.1` par défaut.

## Permissions

- API : permission Django globale **`gesec.api_access`** par défaut sur toutes les
  routes `/api/` (DRF `DEFAULT_PERMISSION_CLASSES` = `ApiAccessPermission`,
  `UNAUTHENTICATED_USER = None` → 401 sans jeton, 403 sans la permission),
  y compris `/api/healthcheck`.
- Téléchargement de fichiers `/s3/<path>` : **superuser authentifié uniquement** (403 sinon).
- Base `data` (pipeline) : jamais migrée par Django (`DataRouter.allow_migrate = False`) ;
  la base applicative (`default`) héberge users, OAuth, sessions, compteurs de rate limit (ADR 0010).

## Rate limiting

Compteurs en base Postgres (`gesec_ratelimitcount`), incrément atomique par UPSERT SQL,
plafond anti-débordement `MAX_COUNT = 10^6` (`gesec/front/ratelimit/`).

| Surface | Limite | Réponse |
|---|---|---|
| `/api/*` (toutes routes, tous utilisateurs) | 200 req/jour, clé globale | 429 + `Retry-After` |
| `/oauth/*` | 100 req/jour, clé globale | 429 + `Retry-After` |
| `/s3/*` | 200 req/jour **par utilisateur** | 403 |

Le MCP forwardant vers `/api/` est borné par transitivité. Le risque de DoS global
(clé globale, middleware avant l'auth) est accepté et documenté (ADR 0008).

## Limitation des données exposées (API meta_budat, ADR 0009)

- **Plafond dur de 25 lignes** (`MAX_ROWS`) sur les listes **et** les agrégats, sans pagination.
- Filtres, tri, groupements et agrégats restreints à des **allowlists**
  (`FILTERABLE`, `ICONTAINS`, `RANGE`, `GROUPABLE`, `ORDERABLE`, `NUMERIC`, `AGG_FUNCS`
  = sum/avg/count/min/max) ; champ ou fonction inconnu → **400**.
- Toutes les valeurs passent en **paramètres liés ORM** ; aucun SQL concaténé.
- Route unique en list (`GET /api/meta-budat/`, pas de `retrieve`) ;
  schéma découvert via `GET /api/meta-budat/schema/`.
- Autres limites : PDF > 50 pages ignorés (`too_large`) ; LLM Albert ~98-100 req/min.

## En-têtes, cookies, CSRF, XSS

- Middlewares : `SecurityMiddleware`, `CsrfViewMiddleware`, `XFrameOptionsMiddleware`
  (X-Frame-Options DENY), `ALLOWED_HOSTS` restreint (env).
- `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`,
  `SECURE_PROXY_SSL_HEADER` (TLS terminé par le proxy Scalingo).
- `{% csrf_token %}` sur les formulaires POST (logout, consentement OAuth).
- Templates : autoescape Django actif, aucun `|safe` ; seul `mark_safe` sur un
  pourcentage formaté numériquement.
- TLS/HSTS/CSP supposés gérés par l'infrastructure (routeur Scalingo), non définis dans settings.

## Secrets et données sensibles

- Tous les secrets en variables d'environnement (`django-environ`, `ENV_FILE` hors dépôt) :
  `DJANGO_SECRET`, `DATABASE_URL`/`DATA_DATABASE_URL`, `OIDC_RP_*`, `AWS_S3_*`,
  `ALBERT_API_KEY`... Aucun secret commité (règle AGENTS.md,
  `.gitignore`) ; seules des valeurs factices dans `test.env`.
- Clés API externes (Albert) passées au client LLM, **jamais loggées** ; les logs API
  enregistrent méthode/path/user/client_id, **jamais le jeton**.
- `PROD_DB_URL` : accès prod **lecture seule forcée** côté Postgres
  (`postgresql_readonly=True`), requêtes toujours bornées (`LIMIT`)
  (`scripts/synthese_budat.py`).
- Traçabilité : `request_id` corrélé dans les logs (header `X-Request-ID`).

## Stockage

- `STORAGE_BACKEND=fs|s3` ; credentials S3 100 % env.
- Protection path traversal : `safe_join` (FS) / préfixe assaini (S3) ;
  le téléchargement passe par la vue superuser-only `/s3/<path>`, pas par URL publique.
