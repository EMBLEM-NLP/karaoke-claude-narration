# karaoke-narration MCP server

One codebase, two transports. Which you need depends entirely on the surface.

| Surface | Transport | Hosting | Local file/keychain access |
|---|---|---|---|
| Claude Code | stdio | none | yes |
| Claude Desktop | stdio via `claude_desktop_config.json` | none | yes |
| Claude Desktop | custom connector | public URL | no |
| Cowork | custom connector only | public URL | no |
| claude.ai | custom connector only | public URL | no |

Anthropic's docs are explicit that custom connectors are dialled **from
Anthropic's cloud, not your device**, and that local servers configured via
`claude_desktop_config.json` are a separate mechanism unavailable in Cowork and
claude.ai. That single fact decides the table above.

## stdio (no hosting)

```jsonc
// claude_desktop_config.json
{ "mcpServers": {
    "karaoke-narration": {
      "command": "python3",
      "args": ["/abs/path/to/plugins/karaoke-narration/mcp/server.py"]
    } } }
```

Claude Code: `claude mcp add karaoke-narration -- python3 /abs/path/.../server.py`

## HTTP + tunnel (public URL, code stays local)

```bash
python3 server.py --http --port 8787
cloudflared tunnel --url http://localhost:8787     # or: ngrok http 8787
```

Add the resulting `https://…/mcp` URL under Customize → Connectors → Add custom
connector. The process still runs on your machine, so it keeps local access
while satisfying the public-reachability requirement.

**This endpoint is public while the tunnel is up.** Put auth in front of it —
the connector dialog supports OAuth (Client ID/Secret) and, in beta, request
headers, where Claude stores the value and never shows it again.

## Deployed (public URL, no local access)

Fine for `narrate`, which is a pure function. Useless for anything needing your
keychain, browser, or files — deploying moves the code away from the machine
whose state it needed. See `references/credential-handling.md`.

## Tools

- `narrate(text, model, model_id, mode, steps)` — build audio + player. Surfaces
  a QC-gate failure as an error rather than shipping unverified audio.
- `verify_against_ground_truth(built_text, ground_truth)` — word-level diff.
  Exists because the in-flight turn is in no API or export: a turn enters a
  store when it *ends*.

## What a connector does not fix

Narration fidelity. A connector relocates where the build runs; it does not give
the model access to the turn it is currently writing. In Claude Code the `Stop`
hook already solves that by receiving `last_assistant_message` from the runtime.
