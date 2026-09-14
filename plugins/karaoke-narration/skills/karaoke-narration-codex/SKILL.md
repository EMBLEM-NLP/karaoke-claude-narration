---
name: karaoke-narration-codex
description: Use in ChatGPT Work or Codex when the user asks to narrate a response, produce a word-highlighted karaoke player, audit whether a narrated response matches the source text, or enable supported Codex Stop-hook narration. Use explicit MCP tools on ChatGPT web/mobile surfaces; use trusted hooks only where the Codex runtime supports them.
metadata:
  version: 2.4.1
  author: emblem-nlp
  plugin: karaoke-narration
---

# Karaoke Narration For ChatGPT And Codex

This skill creates a narrated review player with word-level highlighting. It is the OpenAI/Codex route for the existing `karaoke-narration` engine.

## Core Rule

Never say a response was narrated unless a narration tool or trusted hook actually ran and returned success. On ChatGPT web/mobile, do not claim silent every-turn narration. Use explicit tool calls because those surfaces may not provide a local hook runtime.

## Tool Order

1. Call `preflight` before the first narration in a session or when a narration fails.
2. If the user wants a chat response read aloud, call `narrate_chat_response` with the exact response text and present the returned packed player HTML. This is the primary ChatGPT Work path.
3. Use `narrate_text` only for lower-level lifecycle flows where the caller intentionally wants a `narration_id` before fetching a player.
4. Use `get_status` for a pending or referenced narration.
5. Use `get_player` only after `get_status` reports `state: ready`.
6. Use `verify_against_ground_truth` when the user asks whether a narrated output exactly matches what was said.
7. Use `delete_narration` when the user asks to remove an output.

## Surface Behavior

- ChatGPT Work, web, and mobile: use explicit MCP tools. Present the returned player or narration ID after success.
- Never open or share `player_embed_template.html` as a player. It is a reusable template and will show placeholders such as `__STATIC_TRANSCRIPT_FALLBACK__` until `pack_standalone.py` injects a specific chat response.
- Codex CLI and trusted Codex runtime: use the plugin's `Stop` hook for automatic narration when enabled and trusted.
- Unsupported or untrusted hook runtime: fall back to explicit narration tools.

## Accuracy Rules

- The source text is ground truth.
- Preserve links as one-word Markdown labels when the text will be narrated.
- Avoid Markdown tables in narrated text; the parser handles prose, headings, bullets, blockquotes, and fenced code more predictably.
- Leave model mode blank unless it is supplied exactly by the host or user.
- Do not infer token counts, model names, or effort settings from memory.

## Failure Handling

- If `preflight` reports missing dependencies, tell the user the missing items and stop before attempting narration.
- If `narrate_text` fails with `qc_gate_failed`, do not present the player as usable.
- If `get_player` returns a large HTML payload and the host cannot render it directly, provide the narration ID and status instead of inventing a URL.

## Hook Notes

The Codex `Stop` event carries `last_assistant_message`, which is the preferred source for automatic narration. The hook is opt-in and must be reviewed/trusted by the runtime before it runs. It should never block a turn; narration is a side effect, not a reason to continue or redirect the agent loop.
