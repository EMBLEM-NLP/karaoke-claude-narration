# Security Policy — karaoke-narration

This package ships on its own, and this file is its threat model in full. It has two
components with materially different exposure — read both before installing.

## Reporting a vulnerability

Report privately via GitHub's "Report a vulnerability" flow, or contact the maintainers
directly. Please do not open a public issue for a security report.

## Threat model

This plugin has two independent components with different exposure. Read both before
installing.

### 1. The `Stop` hook (`hooks/hooks.json` → `scripts/stop_hook.py`)

**Fires on every turn** (Claude Code only — `Stop` has no matcher). It is inert by default:

- **Opt-in.** No-ops unless `~/.karaoke-narration/enabled` exists, set via `/karaoke on`.
- **Content-filtered.** Skips replies under `KARAOKE_MIN_CHARS` (default 220) and replies that
  are mostly fenced code.
- **Local only, once enabled.** Runs Piper (TTS) and faster-whisper (ASR) as local
  subprocesses. No network call is made per narration.
- **One exception, on first use of a given voice:** `ensure_voice()` downloads that Piper
  voice model from Hugging Face over HTTPS if it isn't already cached locally
  (`curl -sL https://huggingface.co/rhasspy/piper-voices/...`). This is a one-time model
  fetch, not a per-turn network call — after the first run for a given voice, everything is
  local. If you audit network egress, expect exactly this one call on first use.
- **Writes to disk.** `~/.karaoke-narration/turns/<session>-<ts>/` (audio, timing JSON,
  standalone HTML player) and `~/.karaoke-narration/hook.log`. Nothing is written outside
  that directory.
- **Reads no credentials.** Nothing here touches an API key, keychain, or browser session.
- **Never blocks the agent loop.** Always exits 0; never emits `decision: "block"`; runs
  `async: true` so a slow build cannot stall the conversation.
- **Model attribution — largely closed as of 2.0.0, but know how it works.** The `Stop`
  payload does not carry model identity, so the hook cannot read the running model
  directly. Through 1.30.0 the only source was `KARAOKE_MODEL`/`KARAOKE_MODEL_ID`, set by
  hand and therefore stale by default — set once, then silently wrong after any model
  switch. 2.0.0 adds a `PostModelSwitch` hook (`scripts/record_model.py`) that records the
  live model to `~/.karaoke-narration/model` at the moment it changes, and `stop_hook.py`
  prefers that file over the environment. Two residual caveats: the recording only starts
  once a switch has occurred in a session where the hook is installed, and the env vars
  still act as a manual override for installs with no hook runtime. Where neither source is
  present, nothing is stamped — which is the correct floor. A wrong model on a response is
  worse than no model.

### 2. The MCP server (`mcp/server.py`)

**Not wired up automatically** — installing this plugin does not start or register it.
It is a separate, manually-configured path for surfaces with no hook runtime (Claude
Desktop, Cowork, claude.ai via a custom connector). See `mcp/README.md` for the transport
matrix.

- **Takes no credentials.** `narrate()` is a pure function — text in, audio out. There is
  nothing in this server worth stealing and nothing it could leak into a transcript.
- **stdio mode** (Claude Code / Desktop config): runs on your machine, local file access,
  no hosting.
- **HTTP mode** (`--http`): if you expose this via a tunnel for use as a custom connector,
  **the endpoint is public while the tunnel is up.** Put authentication in front of it — the
  connector dialog supports OAuth and header-based auth. This plugin does not add its own
  auth layer.

## Media and text are untrusted input in the general sense

Piper and faster-whisper parse text and audio respectively. Keep them current. This plugin
does not sandbox them beyond what your OS already provides for a local subprocess.

## What changed in 2.0.0

One security-relevant behavioral change: model attribution now has a fresh source
(`PostModelSwitch` → `scripts/record_model.py`) instead of depending on hand-set environment
variables that went stale silently. See the bullet above, and `CHANGELOG.md`.

The rest of 2.0.0 is structural — hooks moved to exec form, which removes a layer of shell
quoting around interpolated paths, and `install.sh` replaced the assumption that hook
wiring could be done automatically. Neither widened what this package can reach.
