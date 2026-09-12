---
name: karaoke-narration
description: Builds a word-highlighted, tap-to-seek "karaoke" review player for a narration script — the audio review lens for agent-generated content. Use whenever the user wants to visually triage narrated output, review a script before shipping it, or asks for word-by-word highlighting synced to TTS audio. Composes with narration-audio (Piper) for the audio itself and narrated-video-deck for turning a reviewed narration into a slide video.
compatibility: Requires piper (piper-tts), faster-whisper, ffmpeg/ffprobe, python3 with numpy. Install with `pip install --break-system-packages piper-tts faster-whisper numpy`. The player.html is a static file — usable anywhere, including Claude Desktop.
allowed-tools: Bash(piper:*) Bash(ffmpeg:*) Bash(ffprobe:*) Bash(python3:*) Read Write
metadata:
  version: 2.5.0
  author: emblem-nlp
  plugin: karaoke-narration
---

# Karaoke Narration

Pipeline: script text → per-sentence Piper synthesis → per-clip word alignment →
mastered MP3 + `timing.json` → static HTML player with word highlighting and tap-to-seek.

**Why this exists:** you can't see artifacts this environment produces without opening
them. This closes that loop for narration specifically — instead of trusting a
"proceed" blind, you get a scannable transcript you can tap through and a highlight
that proves the audio and the words actually line up.

## The landmine this route avoids

`narration-audio`'s SKILL.md documents that **full-file Whisper on synthetic TTS
speech silently drops long spans and under-reports coverage by ~80%.** That rules out
the obvious approach (synthesize the whole script, then run Whisper over the whole
file for word timestamps).

The fix: Piper already synthesizes **per sentence** (to dodge its own long-utterance
buzz defect), which means every sentence's exact sample-offset in the final track is
already known with zero ASR. So Whisper is only ever run on **one short, isolated
sentence clip at a time**, with the ground-truth sentence text passed as
`initial_prompt` — this is the "short isolated clips" case the parent skill's own
warning says is safe, and it's timing-only, not transcription, since the words are
already known.

## Workflow

```bash
pip install --break-system-packages piper-tts faster-whisper numpy
python3 scripts/build_karaoke.py script.txt -o out/narration.mp3
```

Produces `out/narration.mp3` and `out/narration.timing.json`
(`{"words": [{"w": "...", "start": 0.0, "end": 0.31}, ...], "duration": 9.5}`).

**For viewing inside claude.ai (the default case): pack a standalone artifact.**

```bash
python3 scripts/pack_standalone.py out/narration.mp3 out/narration.timing.json \
  -o out/narration_review.html
```

This embeds the audio as base64 and the timing inline into one file with no
load step. Required here, not optional: claude.ai's artifact preview renders HTML
in a sandboxed iframe that cannot `fetch()` sibling files sitting next to it in the
outputs folder, and the multi-file `player.html` loader's file `<input>` only sees
files already on the device — not ones just generated server-side. The first version
of this skill shipped `player.html` alone and its play button was correctly disabled
because nothing had loaded; `pack_standalone.py` is the fix, and is now the path
that actually gets used for in-chat review. Always pack standalone before presenting
a karaoke review artifact to the user in this environment — don't hand over the bare
`.mp3` + `.timing.json` pair and expect them to load it manually.

**For local/Claude Code use, where real file access exists**, `player.html` (the
multi-file loader) or `player.html?src=narration` (fetch from a sibling file over an
actual server) both still work and avoid re-embedding audio on every edit.

## Automatic per-turn narration is a hook, not this skill

**If you want the CURRENT turn's own narration** — not the previous one — the Stop
hook below cannot do it; skip ahead to "Narrating a real turn" instead. `Stop` fires
only after a reply already exists, so it structurally can't narrate the turn it fires
on. That is a real constraint, not a packaging gap, and no hook wiring changes it.

This skill is manually invoked. To narrate **every** turn automatically, the
plugin ships a **Stop hook** (`hooks/hooks.json` -> `scripts/stop_hook.py`).

That split is deliberate and not a workaround. Skills are model-invoked: Claude
decides whether to load one by matching the request against this `description`
field. No frontmatter flag forces a skill to load every turn - `user-invocable`
and `disable-model-invocation` only *restrict* invocation, they never compel it -
and description-engineering measures unreliable for this purpose. A Stop hook
fires deterministically. So the hook owns automatic firing; this skill stays for
manual use and for surfaces with no hook runtime.

### Where it actually runs

| Surface | Skill | Stop hook |
|---|---|---|
| Claude Code CLI | yes | **yes** - full support |
| Claude Cowork | yes | partial - hooks run here, but report gaps |
| claude.ai chat (web/mobile) | yes | **no** - no hook runtime |
| Claude Desktop chat tab | yes | no |

On claude.ai the skill can be uploaded and toggled on, but nothing fires it every
turn. That is a product boundary, not a packaging problem - do not try to solve it
with a cleverer description.

### Why Stop and not UserPromptSubmit

`UserPromptSubmit` fires *before* Claude responds, so the response text does not
exist yet. `Stop` is the only per-turn event carrying the assistant's completed
text, exposed as `last_assistant_message`.

### Design constraints in stop_hook.py

- **Opt-in.** Inert until `~/.karaoke-narration/enabled` exists (`/karaoke on`).
  `Stop` has no matcher and fires on every turn including one-word replies;
  synthesizing speech for all of them is slow and wasteful.
- **Content filtered.** Skips replies under `KARAOKE_MIN_CHARS` (default 220) and
  those that are mostly fenced code.
- **Never blocks.** Always exits 0, never emits `decision: "block"`, so it cannot
  cause the Stop -> block -> Stop loop. Failures degrade to a log line.
- **Async.** Declared `"async": true` so TTS latency never stalls the agent loop.
- **Transcript fallback ignores `transcript_path`.** That field is documented as
  lagging and has been reported stale; the fallback picks the newest `.jsonl`.

If the plugin hook does not fire, run `bash install.sh --apply` from the package
root for the settings-based route - plugin `Stop` hooks specifically have been
reported not firing on some versions while the identical script worked from
settings. It writes the same four hooks with this checkout's absolute paths
already substituted, and `--uninstall` reverses it.

### The other UserPromptSubmit: delivering what Stop already built (2.5.0)

The section above explains why *automatic narration* cannot use `UserPromptSubmit` -
the reply doesn't exist yet when it fires. That is a different question from
*delivery*. `scripts/pending_narration.sh` uses `UserPromptSubmit` for exactly
that: not to narrate, but to notice, at the start of the next turn, that `Stop`
already built a player nobody has seen yet.

This matters in a session with no listener for the files `stop_hook.py` writes -
a remote/headless container where nothing plays audio or forwards HTML on its
own. Left alone, narration is built correctly and then sits on disk forever.
`pending_narration.sh` scans `~/.karaoke-narration/turns/*/` each turn for a
`response_standalone.html` with no sibling `.sent` marker, and if it finds one,
emits `hookSpecificOutput.additionalContext` naming the file and instructing
Claude to send it via `SendUserFile` and then `touch` the `.sent` marker itself.
The script never creates that marker - only Claude does, after confirming the
send actually happened, since the script has no way to know that.

Fast (a local directory scan, no `async`) and silent when there is nothing
pending (exit 0, no output) - most turns pay nothing for it.

## Narrating a real turn (1.30.0, rule 4 and the audit added in 2.2.0)

Use `scripts/narrate_response.sh`. Four rules, each of which was learned by breaking it.

**1. Narrate the reply itself, not a script written beside it.** Compose the message as
files, build from those files with themselves as ground truth, then send that exact text.
Seven artifacts were built the other way and every one reported
`source_matches_ground_truth: NOT CHECKED` — the gate had nothing to compare against, so it
was decorative. The wrapper concatenates the inputs into the ground truth itself; do not
hand-maintain that copy, or it becomes a third text that can drift.

```bash
scripts/narrate_response.sh turns/007 "Narrated turn" \
  "Thought process:reasoning.md" "Chat response:response.md"
```

Any number of `Label:file` pairs work — each becomes its own labeled, navigable section,
because `build_karaoke.py` treats every input file as one turn.

**2. One output directory per turn, never a shared path.** Artifact publishing is keyed to
the output path, so republishing a single "latest" path means each turn overwrites the last.
Observed: a 34-word reply destroyed a 369-word narration and only the final turn survived at
that URL. Per-turn paths are what make per-turn permanent links.

**3. Publish it, and let the card speak for itself.** The artifact card renders in the
conversation on its own, so the reply needs no link in its text. This matters beyond tidiness:
a link's label is narrated, and a multi-word label fails the verbatim gate (`clean_token` maps
one source token to one display token). Omitting the link removes the whole class of problem.

**4. A new artifact URL per turn — never republish over an old one.** Rule 2 gives each turn
its own output directory; this is the same rule at the publishing end. Passing the Artifact
tool a `url` to update in place overwrites that link's previous contents, so the earlier
turn's narration is gone. Reproduced twice now: once as the 34-word reply in rule 2, and
again when a QA fixture built during testing was published over a real turn's narration at a
shared URL. Publish without `url`; let each turn claim its own permanent link.

**Then audit it on the next turn.** Every gate above compares the build against its own
inputs, so a fixture that matches itself passes all of them — which is exactly how the
failure in rule 4 shipped green. The reply only becomes checkable data after the turn ends,
when the Stop hook records `last_assistant_message`. So at the start of the next turn:

```bash
python3 scripts/audit_published.py turns/007
```

Exit 0 published-matches-said, 1 a real divergence with the differing spans printed, 2 could
not check (no Stop-hook record - hook off, or the reply was under `KARAOKE_MIN_CHARS`). Exit
2 is not a pass. It reuses `build_karaoke.py`'s own comparison rather than restating it, so a
fenced code block does not false-fail the way a raw diff would.

Writing constraints the parser imposes, all verified against it:

- **No tables.** `parse_blocks` swallows a table into one run-on paragraph — pinned by the
  regression suite. Use bullets.
- **Links as `[label](url)` with a one-word label**, for the reason in rule 3.
- **Code stays fenced** — rendered in the player, never spoken, by design.
- **~800 words per turn.** `check_reader.py` derives the phone's load ceiling at ~884.
  Split longer material across turns rather than summarising it; summarising is the defect
  rule 1 exists to prevent.

Note that `stop_hook.py` never had this problem: it narrates `last_assistant_message`, which
is the actual reply, so it is verbatim by construction. Rule 1 is about using the tool by
hand — which is the only mode available where the hook cannot be registered.

## Delivery and iOS

Four rules learned shipping a working player to a real phone — file-attachment
delivery, audio-context timing, WebKit's non-standard `'interrupted'` state, and
why a desktop Chromium pass proves nothing for this class of bug — are in
[references/ios-audio-delivery.md](references/ios-audio-delivery.md). The
underlying `data:`/`blob:` sandbox failure they build on is in
[references/sandbox-audio-constraints.md](references/sandbox-audio-constraints.md).

## Model attribution and token estimates

Why model name/ID must be re-derived every build while attribution mode can never
be inferred: [references/model-attribution.md](references/model-attribution.md).
Why the token estimate is a real, directional bias rather than generic
imprecision, and why input tokens are unrecoverable at all:
[references/token-accuracy.md](references/token-accuracy.md).

## Step lines are quotations, not summaries

Blockquote step lines describing tool calls must be copied character-for-character
from the actual description strings, not recalled afterward — full incident and
rules in [references/tool-call-quotation.md](references/tool-call-quotation.md).

## Known-good behavior, verified in a smoke test

- Word starts/ends are monotonic and non-overlapping across sentence boundaries.
- A zero-width word (start == end) surfaced once at a sentence boundary during
  testing — `align_words()` now floors every word to an 80 ms minimum so every word
  stays a valid tap target. If you see a mistimed tap after editing the script,
  check this floor first before assuming the alignment model is wrong.
- Gaps between sentences (silence) are correctly excluded from the active-word
  highlight — `findActive()` in `player.html` returns "no active word" rather than
  freezing on the last word of the previous sentence.

## Bundled resources

- `scripts/build_karaoke.py` — synthesis + per-clip alignment + timing manifest
- `scripts/player.html` — the review UI (dark, single-file, no build step)
- `assets/demo/` — a working demo pair (`demo.mp3` + `demo.timing.json` +
  `player.html`) so you can confirm the pipeline works before wiring it into a real
  script — open `assets/demo/player.html?src=demo`

## Next, not today

- Tap-to-navigate currently seeks and plays; a "loop this sentence" mode would help
  triage a single suspect line faster.
- No sentence-level jump (prev/next section) yet — word-level only.
- Not yet wired into `narrated-video-deck`'s `timing-manifest-schema.md`; doing so
  would let a reviewed karaoke script hand off directly into slide-deck timing
  rather than re-deriving it.
