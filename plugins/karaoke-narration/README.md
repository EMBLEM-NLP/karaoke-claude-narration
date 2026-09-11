# karaoke-narration

Word-highlighted, tap-to-seek review player for narration scripts — and, on Claude Code,
automatic narration of every assistant turn.

Published from `EMBLEM-NLP/karaoke-claude-narration`, which is also a Claude Code plugin
marketplace. Self-contained: no monorepo or sibling repository is required. The current
version is in `VERSION`; do not restate it here, since a hand-copied number in prose is
exactly the drift `scripts/version-guard.sh` exists to catch and cannot see.

## Why

You can't see artifacts produced in a Claude environment without opening them. This closes
that gap: instead of trusting a "proceed" blind, you get a transcript synced to audio, word
by word, that you can tap through to jump straight to any point.

## Runtime requirements

Not bundled: `piper-tts`, `faster-whisper`, `ffmpeg`/`ffprobe`, and Python 3 with `numpy`.
`ffmpeg`/`ffprobe` are system binaries, not pip packages — pip alone will not install
them, and that gap is exactly what stalled a real Stop-hook run silently for several
turns before being caught. Install both halves:

```bash
apt-get install -y ffmpeg                                    # ffmpeg + ffprobe
pip install --break-system-packages piper-tts faster-whisper numpy
```

Run `scripts/preflight.sh --report` at any time to check what's actually present and
get the exact fix for whatever's missing — it also runs automatically at `SessionStart`
once the hooks are installed. Don't fix a preflight gap by running
`pip install -r requirements.txt`: that file also carries the separate MCP server's
dependencies (`mcp[cli]`, `fastapi`, `uvicorn`) and installing it as one shot can trigger
an unrelated `PyJWT` pip/apt conflict. Use the two commands above for narration alone.

## Install — the marketplace route first

**1. From the marketplace (preferred, and the only route that needs no settings edits).**

```
/plugin marketplace add EMBLEM-NLP/karaoke-claude-narration
/plugin install karaoke-narration@emblem-nlp
```

or the same thing from a terminal:

```bash
claude plugin marketplace add EMBLEM-NLP/karaoke-claude-narration
claude plugin install karaoke-narration@emblem-nlp
```

Three names are involved here and they are deliberately not all the same — copy the commands
rather than deriving them:

- the **repository** is `EMBLEM-NLP/karaoke-claude-narration` (what `marketplace add` takes)
- the **marketplace** is `emblem-nlp` (from `name` in `.claude-plugin/marketplace.json`)
- the **plugin** is `karaoke-narration` (from `name` in its `plugin.json`)

So the install target is `karaoke-narration@emblem-nlp` regardless of what the repo is
called, and renaming the repo later changes only the `marketplace add` line.

This registers all three hooks in `hooks/hooks.json` from the plugin itself — verified with
`claude plugin details`, which reports `Hooks (3) SessionStart, PostModelSwitch, Stop`. No
one edits `~/.claude/settings.json`, by hand or otherwise. Works the same in a local CLI and
in a remote/cloud session. Run `bash setup.sh --apply` separately for the runtime
dependencies; installing a plugin installs no software (see Runtime requirements).

**2. By hand, with `install.sh`.** A fallback for environments that cannot reach the
marketplace repo. It merges the hook entries into `~/.claude/settings.json` without
disturbing what is already there.

> **Do not run both routes at once.** Each supplies the same three hooks, so a machine with
> both wired narrates every turn twice. If you switch to the marketplace route, run
> `bash install.sh --uninstall` first — and then check `~/.claude/settings.json` yourself,
> because `--uninstall` matches on a `_karaoke` marker that Claude Code strips whenever it
> rewrites that file for its own reasons (adding `extraKnownMarketplaces`, for example).
> Observed directly: after a marketplace install, the markers were gone and `--uninstall`
> reported success while removing nothing.

```bash
bash install.sh              # dry run: prints the merged result, writes nothing
bash install.sh --apply      # writes it, after saving a .bak
bash install.sh --uninstall  # removes only this package's entries
```

These are **user-level** hooks: once written they run in every future Claude Code session
for this user, not only in the project you happened to install from. That is a deliberate,
separate step for that reason — read the dry run first, and `--uninstall` reverses it.
Restart the session afterwards so the hooks load.

**3. Without hooks at all.** The skill and the MCP server need no hook runtime — see the
table below. Invoke `build_karaoke.py` directly, or run `mcp/server.py` and call `narrate`.

## What runs automatically, and where

| Surface | Skill (manual) | MCP server | `Stop` hook (every turn) |
|---|---|---|---|
| Claude Code CLI | yes | yes | **yes** — full support |
| Claude Cowork | yes | yes | partial — hooks run, but gaps have been reported |
| claude.ai chat (web/mobile) | yes | yes, via custom connector | **no** — no hook runtime exists |
| Claude Desktop chat tab | yes | yes | no |

The `Stop` hook is **inert until you enable it**:

```bash
mkdir -p ~/.karaoke-narration && touch ~/.karaoke-narration/enabled   # or: /karaoke on
```

Once on, it narrates every assistant turn over ~220 characters that isn't mostly code. See
`SECURITY.md` for exactly what it does and doesn't touch, and
`skills/karaoke-narration/SKILL.md` for the pipeline and its documented failure modes.

## Pipeline

Script text → Piper synthesis (per sentence) → faster-whisper word alignment (per isolated
clip, never full-file) → mastered MP3 + `timing.json` → `player.html`.

Per-sentence synthesis and per-clip alignment are not incidental: full-file Whisper over
synthetic TTS speech silently drops long spans. `SKILL.md` documents the measurement.

## Hooks

`hooks/hooks.json` declares three, all in exec form (`command` + `args[]`, spawned directly
rather than through a shell):

| event | script | why |
|---|---|---|
| `SessionStart` | `scripts/version-guard.sh --report` | reports version drift; read-only, no network, always exits 0 |
| `PostModelSwitch` | `scripts/record_model.py` | records the live model so narration attribution cannot go stale |
| `Stop` | `scripts/stop_hook.py` | narrates the finished turn; async, never blocks, always exits 0 |

`SessionStart` also runs `scripts/preflight.sh --report`, which reports missing runtime
dependencies instead of letting them surface as buried async failures in `hook.log`.

## Versioning

Four surfaces must agree: `VERSION`, `.claude-plugin/plugin.json`,
`skills/karaoke-narration/SKILL.md`'s `metadata.version`, and the newest `CHANGELOG.md`
entry. There is no `bump-version.sh` — change them together by hand, then confirm:

```bash
bash scripts/version-guard.sh --strict
```

`okf_version` in `skills/karaoke-narration/references/index.md` is deliberately *not* one of
them; it tracks the reference-bundle spec, and the guard reports it as drift if it ever
equals the release version.

## Narrating the current turn (beating the Stop hook's one-turn lag)

The `Stop` hook only ever narrates the *previous* reply — it fires after Claude
finishes responding, so it can never have the current turn's text in time to publish
it as part of that same turn. That lag isn't a bug to work around by hand: it's already
solved by `scripts/narrate_response.sh`.

```bash
scripts/narrate_response.sh turns/007 "Narrated turn" "Chat response:response.md"
```

Write the reply to a file first, run this before sending it, then publish the resulting
`turns/007/turn.html` via the Artifact tool in the same turn — **without** a `url`
parameter, so the turn claims its own permanent link instead of overwriting an earlier
one. That file is already packed with `--artifact`, so it renders correctly wherever
delivery has to go through the Artifact tool (Claude Code Remote, claude.ai). The script
uses the reply file itself as ground truth, so the verbatim gate is a real check, not a
decorative `NOT CHECKED`.

Then, at the start of the **next** turn, audit what you actually published:

```bash
python3 scripts/audit_published.py turns/007
```

Every build-time gate compares the build against its own inputs, so a file written beside
the reply — a QA fixture, a draft — passes all of them by matching itself. The real reply
only becomes data after the turn ends, when the Stop hook records
`last_assistant_message`; this compares the two. Exit 0 matched, 1 diverged (differing
spans printed), 2 could not check — which is not a pass.

See `skills/karaoke-narration/SKILL.md`'s "Narrating a real turn" section for the full
rules (one turn directory per turn, never a shared path; a new artifact URL per turn;
one-word link labels).

## Also in this package

- `mcp/` — MCP server exposing the pipeline as `narrate` / `verify_against_ground_truth`.
  **Not started automatically** by installing this package — see `mcp/README.md` for the
  transport matrix and `DEPLOY.md` for the claude.ai custom-connector route.
- `interop/` — conformance kit: a `timing.json` schema, a validator with a negative control,
  and a reader-portability checker.
- `commands/karaoke.md` — the `/karaoke on|off|status` toggle.

- [SECURITY.md](SECURITY.md) — threat model for both components
- [CHANGELOG.md](CHANGELOG.md)
