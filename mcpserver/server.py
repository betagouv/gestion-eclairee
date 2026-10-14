"""Serveur MCP minimal : vérifie la connectivité avec l'API partenaire."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

DEFAULT_TIMEOUT = 10.0

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


@mcp.tool(description="Vérifie la connectivité avec l'API partenaire.")
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


def main() -> None:
    app = mcp.streamable_http_app(stateless_http=True, transport_security=transport_security)
    uvicorn.run(
        app,
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "9000")),
    )


if __name__ == "__main__":
    main()
