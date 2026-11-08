import asyncio

import pytest

from mcpserver.server import McpAuthError, ResourceMetadataMiddleware, build_www_authenticate, forward_authorization


class FakeContext:
    def __init__(self, headers):
        self.headers = headers


def test_forward_authorization_passes_bearer_through():
    ctx = FakeContext({"authorization": "Bearer some-oauth-access-token"})

    assert forward_authorization(ctx) == "Bearer some-oauth-access-token"


def test_forward_authorization_no_headers():
    with pytest.raises(McpAuthError):
        forward_authorization(FakeContext(None))


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Basic abc",
        "Bearer",
        "bearer ",
    ],
)
def test_forward_authorization_rejects_invalid_header(header):
    with pytest.raises(McpAuthError):
        forward_authorization(FakeContext({"authorization": header}))


def test_build_www_authenticate_points_to_django_prm(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.gouv.fr/")

    assert (
        build_www_authenticate()
        == 'Bearer resource_metadata="https://app.example.gouv.fr/.well-known/oauth-protected-resource"'
    )


def test_build_www_authenticate_requires_public_base_url(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    with pytest.raises(McpAuthError):
        build_www_authenticate()


class FakeApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def run_middleware(scope, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.gouv.fr")
    app = FakeApp()
    middleware = ResourceMetadataMiddleware(app)
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, None, send))
    return app, sent


def http_scope(headers):
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}


def test_middleware_rejects_request_without_bearer(monkeypatch):
    app, sent = run_middleware(http_scope([]), monkeypatch)

    assert not app.called
    assert sent[0]["status"] == 401
    www_authenticate = dict(sent[0]["headers"])[b"www-authenticate"].decode()
    assert www_authenticate == (
        'Bearer resource_metadata="https://app.example.gouv.fr/.well-known/oauth-protected-resource"'
    )


def test_middleware_forwards_request_with_bearer():
    app, sent = run_middleware(http_scope([(b"authorization", b"Bearer token")]))

    assert app.called
    assert sent[0]["status"] == 200


def test_middleware_ignores_non_http_scopes():
    app, sent = run_middleware({"type": "lifespan", "headers": []})

    assert app.called
    assert sent[0]["status"] == 200
