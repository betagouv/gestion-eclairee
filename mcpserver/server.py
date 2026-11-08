"""Serveur MCP passe-plat : forwarde le Bearer OAuth vers l'API Django."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any, Protocol

import httpx
import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

DEFAULT_TIMEOUT = 10.0
AUTHORIZATION_HEADER = "authorization"
BEARER_SCHEME = "bearer"

# Configure transport security for DNS rebinding protection (mcp >= 1.23)
# Per MCP spec: MUST validate Origin header, SHOULD bind to localhost when running locally
# Allow connections from production domain and localhost for development
allowed_host = os.environ.get("MCP_ALLOWED_HOST", "").strip()
allowed_hosts = ["localhost:*", "127.0.0.1:*"]
allowed_origins = ["http://localhost:*", "http://127.0.0.1:*"]
if allowed_host:
    allowed_hosts = [allowed_host, *allowed_hosts]
    allowed_origins = [f"https://{allowed_host}", *allowed_origins]

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=allowed_hosts,
    allowed_origins=allowed_origins,
)

mcp = MCPServer(
    "Dépenses",
    version="0.1.0",
    description="MCP Dépenses : analyse des factures.",
)


class McpAuthError(Exception):
    pass


class HeadersCarrier(Protocol):
    @property
    def headers(self) -> Mapping[str, str] | None: ...


def forward_authorization(ctx: HeadersCarrier) -> str:
    """Retourne l'en-tête `Authorization: Bearer <access_token>` reçu, à forwarder tel quel."""
    headers = ctx.headers
    if not headers:
        raise McpAuthError("En-tête Authorization absent")

    header = headers.get(AUTHORIZATION_HEADER, "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME or not value:
        raise McpAuthError("En-tête Authorization invalide")

    return f"Bearer {value}"


@mcp.tool(description="Vérifie la connectivité avec l'API partenaire (GET sur l'URL de base, sans authentification).")
def healthcheck() -> dict[str, Any]:
    target = os.environ.get("MCP_BASE_API_URL")
    if not target:
        return {"ok": False, "error": "MCP_BASE_API_URL est absent"}

    started = time.perf_counter()
    try:
        response = httpx.get(target, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "url": target,
            "error": f"{type(e).__name__}: {e}",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    return {
        "ok": response.is_success,
        "url": target,
        "status_code": response.status_code,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@mcp.tool(description="Vérifie l'authentification utilisateur auprès de l'API (Bearer OAuth requis).")
def auth_healthcheck(ctx: Context) -> dict[str, Any]:
    base_url = os.environ.get("MCP_BASE_API_URL")
    if not base_url:
        return {"ok": False, "error": "MCP_BASE_API_URL est absent"}

    try:
        authorization = forward_authorization(ctx)
    except McpAuthError as e:
        return {"ok": False, "error": str(e)}

    url = base_url.rstrip("/") + "/api/healthcheck"
    started = time.perf_counter()
    try:
        response = httpx.get(url, headers={"Authorization": authorization}, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "url": url,
            "error": f"{type(e).__name__}: {e}",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    body: Any = None
    if response.is_success:
        try:
            body = response.json()
        except ValueError:
            body = None

    return {
        "ok": response.is_success,
        "status_code": response.status_code,
        "body": body,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def build_www_authenticate() -> str:
    """Challenge RFC 9728 : pointe vers le document de métadonnées de la ressource
    servi par Django (PUBLIC_BASE_URL), source de vérité unique."""
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base_url:
        raise McpAuthError("PUBLIC_BASE_URL est absent : impossible de construire le challenge WWW-Authenticate")
    resource_metadata = f"{public_base_url}/.well-known/oauth-protected-resource"
    return f'Bearer resource_metadata="{resource_metadata}"'


def _has_bearer_token(scope: dict[str, Any]) -> bool:
    headers = {k.lower(): v for k, v in scope.get("headers", [])}
    authorization = headers.get(b"authorization", b"")
    scheme, _, value = authorization.partition(b" ")
    return scheme.lower() == b"bearer" and bool(value)


class ResourceMetadataMiddleware:
    """Répond 401 + `WWW-Authenticate: Bearer resource_metadata=...` aux requêtes
    sans jeton Bearer. La validation du jeton reste du ressort de l'API Django
    (le serveur MCP reste un passe-plat sans état)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and not _has_bearer_token(scope):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"www-authenticate", build_www_authenticate().encode()),
                        (b"content-type", b"application/json"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"jsonrpc":"2.0","error":{"code":-32001,"message":"Unauthorized"},"id":null}',
                }
            )
            return
        await self.app(scope, receive, send)


def main() -> None:
    build_www_authenticate()
    app = mcp.streamable_http_app(stateless_http=True, transport_security=transport_security)
    uvicorn.run(
        ResourceMetadataMiddleware(app),
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "9000")),
        workers=1,
    )


if __name__ == "__main__":
    main()
