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


