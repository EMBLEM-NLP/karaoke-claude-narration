#!/usr/bin/env python3
"""
server_http_authed.py — deployment entrypoint for karaoke-narration's MCP
server, adding the one thing it ships without: an auth layer on the HTTP
transport.

WHY THIS EXISTS, SEPARATELY FROM mcp/server.py
-----------------------------------------------
SECURITY.md is explicit: "This plugin does not add its own auth layer" and
"[if exposing via a tunnel] put auth in front of it." mcp/server.py itself
has no code addressing this — it only implements the two tools. Verified
against Anthropic's current documentation (fetched fresh, not assumed):
custom connectors support two auth models —

  1. Full OAuth 2.1 (the default/primary path). Requires standing up a real
     authorization server (issuer_url + resource_server_url + token
     issuance/discovery endpoints). Correct for a shared, multi-user
     deployment; substantial infrastructure for a single-operator tool.
  2. Request-header auth ("static_headers", BETA on Anthropic's side, per
     their own docs). The connector dialog lets the operator configure a
     header (commonly `Authorization: Bearer <token>`) that Claude sends on
     every request. The server just checks it. No discovery, no token
     issuance, no separate auth server.

This implements (2): the right-sized choice for one operator's own server,
not a multi-tenant service. If you need (1) instead - e.g. deploying this
for a team, where each person should authenticate as themselves - that is a
materially bigger build (real issuer, token endpoint, PKCE, refresh) and is
NOT what this file does. Say so if that's actually what you need.

DOES NOT MODIFY mcp/server.py. Imports its already-built `mcp` FastMCP
instance and wraps the ASGI app it exposes, so the vendored file stays
diffable against upstream and easy to update later.
"""
import os
import sys
import secrets
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import mcp  # noqa: E402  (the plugin's existing FastMCP instance)

TOKEN_ENV = "KARAOKE_MCP_TOKEN"


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject any request whose Authorization header doesn't match the
    configured shared secret. Constant-time compare (secrets.compare_digest)
    so response timing can't be used to brute-force the token."""

    def __init__(self, app: ASGIApp, token: str):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        scheme, _, supplied = auth.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, self._token):
            return JSONResponse(
                {"error": "unauthorized",
                 "detail": "missing or incorrect Authorization: Bearer <token>"},
                status_code=401,
            )
        return await call_next(request)


def build_app() -> Starlette:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        sys.exit(
            f"[server_http_authed] {TOKEN_ENV} is not set. Refusing to start "
            f"an unauthenticated public endpoint. Generate one with:\n"
            f"  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
            f"then: export {TOKEN_ENV}=<that value>"
        )
    if len(token) < 20:
        sys.exit(f"[server_http_authed] {TOKEN_ENV} is too short to be a "
                 f"real secret ({len(token)} chars). Use secrets.token_urlsafe(32).")

    inner = mcp.streamable_http_app()
    return Starlette(
        routes=inner.routes,
        middleware=[Middleware(BearerAuthMiddleware, token=token)],
        lifespan=inner.router.lifespan_context,
    )


app = None  # built lazily so `import` alone (e.g. for tests) doesn't require the env var


if __name__ == "__main__":
    import argparse
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    app = build_app()
    print(f"[server_http_authed] listening on {args.host}:{args.port}, "
          f"{TOKEN_ENV} set ({len(os.environ[TOKEN_ENV])} chars) - "
          f"every request must carry Authorization: Bearer <token>")
    uvicorn.run(app, host=args.host, port=args.port)
