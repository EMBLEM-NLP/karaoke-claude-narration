# karaoke-claude-narration

Claude Code plugin marketplace for EMBLEM-NLP's `karaoke-narration` plugin.

```bash
claude plugin marketplace add EMBLEM-NLP/karaoke-claude-narration
claude plugin install karaoke-narration@emblem-nlp
```

The repository is named `karaoke-claude-narration`; the plugin id remains
`karaoke-narration`, and the marketplace id remains `emblem-nlp`.

Full plugin docs live in [`plugins/karaoke-narration/README.md`](plugins/karaoke-narration/README.md).

OpenAI/Codex compatibility lives beside the Claude package:

- Codex plugin manifest: [`plugins/karaoke-narration/.codex-plugin/plugin.json`](plugins/karaoke-narration/.codex-plugin/plugin.json)
- OpenAI MCP adapter: [`plugins/karaoke-narration/mcp/openai_server.py`](plugins/karaoke-narration/mcp/openai_server.py)
- Codex skill: [`plugins/karaoke-narration/skills/karaoke-narration-codex/SKILL.md`](plugins/karaoke-narration/skills/karaoke-narration-codex/SKILL.md)
- Adapter notes: [`plugins/karaoke-narration/mcp/OPENAI_CODEX.md`](plugins/karaoke-narration/mcp/OPENAI_CODEX.md)
