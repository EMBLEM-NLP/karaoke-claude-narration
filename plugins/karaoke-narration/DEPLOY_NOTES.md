# Deploy notes — verified in a live test session, 2026-08-04

## What was tested
- `pip install "mcp[cli]"` (unpinned) → resolves to mcp 2.0.0 → server.py fails:
  `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`
- Root cause: mcp 2.0.0 renamed `FastMCP` to `MCPServer` and moved it from
  `mcp.server.fastmcp` to `mcp.server.mcpserver`. server.py (shipped at
  plugin v1.28.0) targets the pre-2.0 API.
- Fix: pin `mcp[cli]==1.29.0` (see requirements.txt). Confirmed working:
  `from mcp.server.fastmcp import FastMCP` imports cleanly under 1.29.0.

## What was verified end-to-end (not just syntax-checked)
1. `python3 mcp/server.py --http --port 8787` starts cleanly, Uvicorn binds,
   session manager starts.
2. Real MCP protocol handshake: POST /mcp `initialize` → 200, server
   correctly identifies as `karaoke-narration` v1.29.0, returns a session ID.
3. `tools/list` → both `narrate` and `verify_against_ground_truth` present,
   with the documented input/output schemas.
4. `tools/call narrate` with real text → real audio + standalone HTML player
   produced, full QC report returned, `"ok": true`, every boolean QC check
   true. `source_matches_ground_truth: null` correctly reflects "not
   supplied," matching the skill's own documented honesty about that check.

## What was NOT tested (could not be, from this environment)
Public reachability. This was run and killed within a single ephemeral
sandboxed session — confirmed directly: a backgrounded server process died
between two separate tool calls in the same test session, before I switched
to single-call start+test+kill sequences. This is not a config problem to
fix; it's the correct behavior of a task-scoped sandbox. It means:
- This environment cannot be the deploy target. It was never going to be.
- Whatever you deploy this to needs to be a host that stays up on its own —
  your own machine + a tunnel (cloudflared/ngrok), or a small persistent
  host (Fly.io, Railway, a VPS, etc.). `narrate` is a pure function (no
  local file/keychain access needed), so per mcp/README.md, either path is
  fully viable — this isn't limited to the stdio/local-only case.

## Before you expose it publicly
mcp/server.py takes no credentials and SECURITY.md confirms this. But the
HTTP endpoint itself has no auth layer built in — per mcp/README.md, put
auth in front of it (the connector dialog's OAuth or header-auth option,
or your tunnel/host's own auth) before the URL goes live, since "the
endpoint is public while the tunnel is up."

## Dockerfile status: written, NOT build-tested
docker isn't available in this sandbox, so unlike everything above, the
Dockerfile was NOT actually built or run — only reasoned from verified
components (the pinned requirements.txt that installs cleanly, the confirmed
need for ffmpeg, and server_http_authed.py, which WAS fully protocol-tested
above). Build it yourself before trusting it:
    docker build -t karaoke-mcp .
    docker run -p 8787:8787 -e KARAOKE_MCP_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))") karaoke-mcp
    curl -i -X POST http://localhost:8787/mcp -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      -H "Authorization: Bearer <the token you just generated>" \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"x","version":"1"}}}'
If that doesn't return HTTP 200 with a real handshake, something in the
container environment differs from this sandbox - don't proceed to deploy
until it does.
