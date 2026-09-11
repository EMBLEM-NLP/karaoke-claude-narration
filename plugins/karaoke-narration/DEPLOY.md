# Deploying karaoke-narration as a claude.ai custom connector

Everything in this file was checked against Anthropic's current documentation
(fetched fresh; not assumed from the plugin's own README, which is accurate
on most points but not authoritative on Anthropic's product). Where the two
disagreed, this file follows Anthropic's docs.

## 0. What you're deploying

`mcp/server_http_authed.py` — NOT the bare `mcp/server.py`. The bare server
has no auth layer (confirmed in SECURITY.md: "This plugin does not add its
own auth layer"). The authed version wraps it with a shared-secret bearer
check, verified in this session to correctly return 401 on missing/wrong
tokens and 200 with a real MCP handshake on the right one.

## 1. Pick a host that stays up

This cannot be a Claude-provided sandbox (that's what generated these files,
and it does not persist a process even across two tool calls in the same
turn - confirmed directly in DEPLOY_NOTES.md). Anthropic's own docs are
explicit that custom connectors are dialled **from Anthropic's cloud**, so
the host needs a stable public IPv4 address reachable from Anthropic's
outbound range `160.79.104.0/21` - not a machine behind NAT/VPN/firewall
with no port forwarding, and not IPv6-only.

Two real options:

**A. Your own machine + tunnel** (code and TTS/ASR stay local; nothing
about `narrate` actually needs this, but it's the zero-cost option):
```bash
export KARAOKE_MCP_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
python3 mcp/server_http_authed.py --port 8787
# separate terminal:
cloudflared tunnel --url http://localhost:8787      # or: ngrok http 8787
```
The tunnel must stay running for the connector to work - closing the
terminal (or your machine sleeping) takes the connector down with it.

**B. A small persistent host** (Fly.io, Railway, a $5 VPS, etc.) using the
included Dockerfile - see the build-test step in DEPLOY_NOTES.md before
relying on it, since it hasn't been build-tested from this session.

## 2. Add the connector in claude.ai

Verified against Anthropic's current help center and docs (not the plugin's
README), as of this session:

- **Free / Pro / Max:** Customize (or Settings) → Connectors → "+" → Add
  custom connector → paste your `https://.../mcp` URL → open **Advanced
  settings** → **Request headers** → add `Authorization` = `Bearer
  <KARAOKE_MCP_TOKEN value>` → Add → Connect.
- **Team / Enterprise:** an Owner/Primary Owner adds it first, under
  Organization settings → Connectors → Add → Custom → Web, same URL and
  header. Members then connect individually from their own Customize →
  Connectors.
- **You cannot add a new custom connector from the mobile app.** Add it on
  web or desktop; it syncs to mobile automatically once added.

**One live caveat, not from the plugin's docs:** Anthropic's own
documentation currently labels request-header authentication **beta**, and
notes it's "being slowly rolled out" and may not appear on every account/
surface yet. If you don't see a "Request headers" option in Advanced
settings, that's why - not a mistake in this setup. Fall back to the
"authless" option temporarily only for a private, throwaway test URL, never
for anything you leave up.

## 3. Verify from your side, not just claude.ai's

Before adding the connector, hit your public URL directly, exactly as
Anthropic's cloud will:
```bash
curl -i -X POST https://YOUR-URL/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"x","version":"1"}}}'
```
Expect HTTP 200 and a JSON-RPC result naming `karaoke-narration`. If you get
a timeout, connection refused, or a redirect, fix that before adding it in
claude.ai - Anthropic's docs note that a redirect to a different host will
silently drop the Authorization header, which looks like an auth failure
but is actually a routing one.

## 4. What this deployment does and doesn't give you

Gives you: `narrate` and `verify_against_ground_truth` as tools any
claude.ai conversation can call, once you invoke the connector - the
functional equivalent of the Claude-Code-only Stop hook, just triggered by
you (or a future Claude turn) calling the tool rather than firing
automatically after every reply.

Doesn't give you: automatic narration of every turn without being asked.
That's the Stop-hook behavior, and per the plugin's own compatibility
table, it has no runtime on claude.ai regardless of connector setup - a
connector and a hook are different mechanisms solving different problems.
