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


def api_get(ctx: Context, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = os.environ.get("MCP_BASE_API_URL")
    if not base_url:
        return {"ok": False, "error": "MCP_BASE_API_URL est absent"}

    try:
        authorization = forward_authorization(ctx)
    except McpAuthError as e:
        return {"ok": False, "error": str(e)}

    url = base_url.rstrip("/") + path
    started = time.perf_counter()
    try:
        response = httpx.get(url, headers={"Authorization": authorization}, params=params, timeout=DEFAULT_TIMEOUT)
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


@mcp.tool(
    description=(
        "Interroge la méta-table BUDAT (lignes de dépenses). Commencer par appeler meta_budat_schema "
        "pour connaître les champs filtrables/groupables/numériques exacts et les fonctions d'agrégation. "
        "Sans group_by/agg : renvoie des lignes "
        "(au plus 100). Avec group_by et/ou agg : renvoie des lignes agrégées (au plus 100). "
        "filters : annee, cas, source, ministere, segment, domaine, gm, service, fournisseur_in_fine_siren, "
        "id_cpro (égalité), fournisseur_budat, fournisseur_in_fine_designation (icontains), "
        "montant_min/montant_max, facture_date_after/facture_date_before. "
        "group_by : champs séparés par des virgules. agg : liste de 'func:champ' "
        "(func ∈ sum, avg, count, min, max ; champ numérique ou '*' pour count). "
        "ordering : champs séparés par des virgules, préfixe - pour desc ; en mode agrégat, accepte les "
        "champs de group_by et les noms d'agrégats (ex. -sum_montant). "
        "Exemples : top 10 fournisseurs d'un segment -> filters={segment: '<segment>'}, "
        "group_by='fournisseur_budat', agg=['sum:montant'], ordering='-sum_montant' ; "
        "top ministères par dépense chez un fournisseur -> filters={fournisseur_budat: '<fournisseur>'}, "
        "group_by='ministere', agg=['sum:montant'], ordering='-sum_montant'."
    )
)
def meta_budat_query(
    ctx: Context,
    filters: dict[str, str] | None = None,
    group_by: str | None = None,
    agg: list[str] | None = None,
    ordering: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(filters or {})
    if group_by:
        params["group_by"] = group_by
    if agg:
        params["agg"] = agg
    if ordering:
        params["ordering"] = ordering
    return api_get(ctx, "/api/meta-budat/", params=params)


@mcp.tool(
    description="Décrit le schéma exposé de la méta-table BUDAT (champs filtrables, groupables, numériques, agrégats)."
)
def meta_budat_schema(ctx: Context) -> dict[str, Any]:
    return api_get(ctx, "/api/meta-budat/schema/")


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
