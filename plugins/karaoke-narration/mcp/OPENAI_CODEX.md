# OpenAI/Codex MCP Adapter

`openai_server.py` is the OpenAI/Codex-facing adapter for the existing karaoke narration engine.

It differs from the original Claude-oriented `server.py` in four ways:

- It returns structured objects instead of JSON strings.
- It returns opaque `narration_id` values instead of server-local `/tmp` paths.
- It stores output below `PLUGIN_DATA` or `KARAOKE_PLUGIN_DATA`.
- It exposes small lifecycle tools: `preflight`, `narrate_text`, `get_status`, `get_player`, `verify_against_ground_truth`, and `delete_narration`.

## Local Codex Transport

The plugin-level `.mcp.json` starts the server over stdio:

```json
{
  "mcpServers": {
    "karaoke-narration": {
      "command": "python3",
      "args": ["${PLUGIN_ROOT}/mcp/openai_server.py"]
    }
  }
}
```

## HTTP Transport

For a hosted connector, run:

```bash
python3 mcp/openai_server.py --http --port 8787
```

The production endpoint must be placed behind real authentication, quotas, and log redaction before public submission. Narration text and generated audio should be treated as user content.

## Runtime Dependencies

Narration requires:

```bash
apt-get install -y ffmpeg
pip install --break-system-packages piper-tts faster-whisper numpy
```

The MCP server itself also requires the MCP SDK version used by this package:

```bash
pip install 'mcp[cli]==1.29.0'
```
