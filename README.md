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

Config opencode (mode remote) :

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "depenses": {
      "type": "remote",
      "url": "http://127.0.0.1:9000/mcp",
      "enabled": true
    }
  }
}
```

Variables d'environnement :

- `MCP_BASE_API_URL` : URL de base de l'API interrogée par le MCP.
- `MCP_HOST` : interface d'écoute (défaut `127.0.0.1`).
- `MCP_PORT` : port d'écoute (défaut `9000`).
- `MCP_ALLOWED_HOST` : hôte autorisé pour la protection anti-DNS-rebinding. Le
  port fait partie du `Host` reçu : utiliser `<hôte>:*` si le client inclut un
  port (sinon le serveur répond `421 Misdirected Request`).


