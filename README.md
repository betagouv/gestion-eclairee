Gestion Éclairée
================

Analyse des dépenses.


## Setup

```sh
uv sync --all-packages
```


## Run tests

```sh
pytest --no-migrations tests

# With coverage
pytest --cov=gesec --cov-report html --no-migrations tests
```


## Run linter / formatter / type checker

ruff format; ruff check --fix
ty check


## Synthèse BUDAT

Génère en JSON les chiffres de couverture du corpus BUDAT (volume, montants,
couverture par ministère, factures restant à éclater par fournisseur,
enrichissement UGAP, groupes de marchandises). Lecture seule sur la base pointée
par la variable d'environnement nommée en premier argument.

```sh
uv run python scripts/synthese_budat.py <ENV_VAR> <annee>
```

- `<ENV_VAR>` : nom de la variable d'environnement contenant l'URL de la base
  (ex. `PROD_DB_URL`).
- `<annee>` : année BUDAT à analyser (ex. `2025`).

La sortie JSON va sur stdout ; les tableaux sont émis en tableaux de tableaux
(en-tête en première ligne). Exemple, avec la variable définie dans un fichier
dotenv sans polluer l'environnement du shell :

```sh
( set -a && source ../gesec.env && set +a && uv run python scripts/synthese_budat.py PROD_DB_URL 2025 ) > synthese.json
```


## MCP server

Le serveur MCP (`mcpserver/`) fait partie du workspace uv (voir Setup).

Lancement local (le port par défaut est `9000`, pour éviter le conflit avec le
serveur Django sur `8000`) :

```sh
MCP_BASE_API_URL=<url> MCP_PORT=9000 uv run --package mcpserver python -m mcpserver.server
```

Inspection interactive :

```sh
npx @modelcontextprotocol/inspector --url http://127.0.0.1:9000/mcp
```

Protocole de test de bout en bout en local (Django + MCP + client OpenCode,
flux OAuth via ProConnect de l'intégration) :
`docs/test-mcp-opencode-local.md`.

Config opencode (mode remote) : l'agent fait lui-même la découverte OAuth
(RFC 9728 → RFC 8414 → Authorization Code + PKCE S256) avec un client
pré-enregistré par l'admin Django (pas de DCR) ; seul le `client_id` (public,
non secret) est à renseigner :

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "depenses": {
      "type": "remote",
      "url": "http://127.0.0.1:9000/mcp",
      "enabled": true,
      "oauth": { "client_id": "<client_id créé dans l'admin Django>" }
    }
  }
}
```

Authentification : OAuth2. Le serveur MCP est un passe-plat sans état qui
forwarde le `Bearer` reçu vers l'API Django ; c'est Django qui joue le rôle de
serveur d'autorisation (django-oauth-toolkit, clients créés dans l'admin
Django uniquement, redirect URIs de boucle locale uniquement, clients publics
+ PKCE S256, scope unique `data`). L'API `/api/` exige une authentification
(permissions Django standard : `IsAuthenticated` par défaut,
`DjangoModelPermissions` par ressource). Voir `docs/adr/0008-as-oauth-mcp.md`.

Variables d'environnement :

- `PUBLIC_BASE_URL` : URL publique de l'application Django, issuer OAuth
  (ex. `https://app.example.gouv.fr`).
- `MCP_PUBLIC_URL` : URL publique du MCP vue par les agents (ressource OAuth,
  ex. `https://mcp.example.gouv.fr/mcp`).
- `MCP_BASE_API_URL` : URL de base de l'API interrogée par le MCP.
- `MCP_HOST` : interface d'écoute (défaut `127.0.0.1`).
- `MCP_PORT` : port d'écoute (défaut `9000`).
- `MCP_ALLOWED_HOST` : hôte autorisé pour la protection anti-DNS-rebinding. Le
  port fait partie du `Host` reçu : utiliser `<hôte>:*` si le client inclut un
  port (sinon le serveur répond `421 Misdirected Request`).
- `OAUTH_ACCESS_TOKEN_TTL` : durée de vie d'un access token OAuth en secondes
  (défaut `3600`).

## API de données meta_budat

La méta-table BUDAT est exposée en lecture seule (voir
`docs/adr/0009-api-meta-budat.md`) ; l'agent y accède via les outils MCP
`meta_budat_query` / `meta_budat_schema`, qui forwardent son Bearer vers :

- `GET /api/meta-budat/` : route unique. Sans `group_by`/`agg` : liste des
  lignes (filtres `annee`, `ministere`, `fournisseur_budat`/
  `fournisseur_in_fine_designation` en `icontains`, `montant_min`/
  `montant_max`, `facture_date_after`/`facture_date_before`, `ordering=...`).
  Avec `group_by` et/ou `agg` : lignes agrégées, ex.
  `?segment=<segment>&group_by=fournisseur_budat&agg=sum:montant&ordering=-sum_montant`
  (top fournisseurs du segment). **Plafond dur de 100 lignes** dans les deux
  modes ; 400 si champ, fonction ou terme de tri inconnu. En mode agrégat,
  `ordering` accepte les champs de `group_by` et les noms d'agrégats
  (`sum_montant`, `count_all`, ...).
- `GET /api/meta-budat/schema/` : allowlists exposées (filtrable, groupable,
  numérique, fonctions d'agrégation, règle du déclencheur d'agrégat, `max_rows`).

Permission requise : `gesec.api_access` (globale, sur `User`).


