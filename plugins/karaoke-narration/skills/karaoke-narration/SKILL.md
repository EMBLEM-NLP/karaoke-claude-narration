---
name: karaoke-narration
description: Builds a word-highlighted, tap-to-seek "karaoke" review player for a narration script — the audio review lens for agent-generated content. Use whenever the user wants to visually triage narrated output, review a script before shipping it, or asks for word-by-word highlighting synced to TTS audio. Composes with narration-audio (Piper) for the audio itself and narrated-video-deck for turning a reviewed narration into a slide video.
compatibility: Requires piper (piper-tts), faster-whisper, ffmpeg/ffprobe, python3 with numpy. Install with `pip install --break-system-packages piper-tts faster-whisper numpy`. The player.html is a static file — usable anywhere, including Claude Desktop.
allowed-tools: Bash(piper:*) Bash(ffmpeg:*) Bash(ffprobe:*) Bash(python3:*) Read Write
metadata:
  version: 2.4.1
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
settings. It writes the same three hooks with this checkout's absolute paths
already substituted, and `--uninstall` reverses it.

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
not check (no Stop-hook record — hook off, or the reply was under `KARAOKE_MIN_CHARS`). Exit
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

## Delivery and iOS: four rules learned on a real phone (1.29.0)

Each of these cost a wrong diagnosis before it was found. They are stated as rules
because every one was violated by a version that passed its own checks.

**1. Deliver as an Artifact, never as a file attachment.** An attachment opens in a
static preview that does not execute JavaScript. This player is entirely
JavaScript - transcript, decode, playback, highlighting - so attached it shows only
its own boot markup, at any size, forever. Pack with `--artifact` and publish with
the Artifact tool. The static boot text now reads `loading player…`, distinct from
every string the script can write, so "script never ran" is visible on screen
instead of being mistaken for "still decoding".

```bash
python3 scripts/pack_standalone.py out/r.mp3 out/r.timing.json --artifact \
  --title "Something specific to this turn" -o out/r_artifact.html
```

**2. Do no audio work before a user gesture.** Established on a real iPhone: the
1.28.0 build, which constructed the `AudioContext` and called `decodeAudioData` at
page load, sat at its boot status with playback never enabled; the 1.29.0 build,
which defers every piece of audio work to the first tap, plays. Because the play
button was enabled only inside the decode's success path, any failure before that
point left it permanently dead. NOT established: why the load-time path failed. The
fix moves the base64 decode, the byte loop and `decodeAudioData` behind the tap
together, so it cures several rival causes at once and cannot tell them apart. An
earlier revision of this section stated as fact that WebKit withholds
`decodeAudioData`'s callbacks on a non-running context. That is unproven - the
eager-decode-then-unlock pattern used by howler.js and Tone.js works on iOS, which
cuts against it - and is withdrawn here rather than edited away. The template
renders the transcript at load, leaves the play button enabled, and on the first
tap - synchronously, before any promise hop - resumes the context, plays a one-frame
silent buffer (the standard WebKit audio-session unlock), and only then decodes.

**3. Test for `'running'`, never for `'suspended'`.** WebKit has a non-standard
`'interrupted'` state (phone call, Siri, backgrounding). A `=== 'suspended'` check
skips the resume in that state and reintroduces the identical hang. Both resume sites
now test `state !== 'running'`, a `statechange` handler tears down and asks for a tap,
and a closed context is rebuilt rather than resumed.

**4. A pass in desktop Chromium is not evidence for this class of bug.** Every build
that hung on the phone passed headless Chromium. `interop/check_reader_live.py` runs
the page in Chromium with Web Audio patched to two hostile behaviours - a decode that
never settles, and a context reporting `'interrupted'` until resumed - and requires
the transcript and an enabled play button to survive both. These are robustness
properties the reader must have whatever the true iOS mechanism is; they are not a
claim about how WebKit decodes. The pre-1.29.0 template fails both; that failure is
the check's negative control. The discriminating experiment nobody has yet run: on
the 1.28.0 artifact build, wait past the 20 s watchdog - a status change proves the
event loop was alive and decode genuinely never settled; no change puts the failure
upstream of decode. Then load the same file first-party in mobile Safari versus
inside the artifact frame, on the same device.

**On the model byline:** the trap this file already documents - a hand-typed model name
carried forward while the real model changed - was reproduced verbatim during 1.29.0's
own development, across a session that ran three different models. Pass `--model` only
with a value verified at that moment; the default of no attribution is the honest one.

## The second landmine: you cannot play audio from a URL in the artifact sandbox

The artifact preview blocks media from **both `data:` and `blob:` URLs** — each
fails with `MEDIA_ERR_SRC_NOT_SUPPORTED` (media error code 4), because both are
URL sources governed by the CSP `media-src` directive. Embedding the audio as a
base64 `data:` URI is therefore *not* sufficient on its own, and converting it to
a Blob URL fails the same way.

`player_embed_template.html` avoids URLs entirely: it base64-decodes the audio to
an `ArrayBuffer` in JS and hands that to **`AudioContext.decodeAudioData()`**.
No resource is fetched, so `media-src` never applies. This also dodges iOS
Safari's long-standing unreliability with `blob:` on media elements.

The trade-off is that an `AudioBufferSourceNode` is one-shot — it cannot be
paused, restarted, or repositioned. Play/pause/seek are therefore hand-managed by
tracking `startCtxTime` / `startOffset` against `audioCtx.currentTime` and
creating a fresh source node on every seek. Playback rate is folded into that
time math, so changing rate mid-play re-seeks to the correct position.

On iOS the `AudioContext` starts suspended; `resume()` must be called from a user
gesture. Every path that starts playback here originates in a click, so this is
handled — but preserve that property if you add new entry points.

**Also: don't rely on `<body>` for the background.** The host stylesheet
overrides it in some preview contexts, which renders the page white while only
explicitly-painted elements (like a fixed footer) stay dark. All styling hangs
off an `#app` wrapper with its own background for this reason.

## Model attribution: name is checkable, mode is not

Model **name and ID** can be verified against Claude's own system prompt at build
time ("This iteration of Claude is Claude Sonnet 5" is stated there directly) -
there is no excuse for a stale or hardcoded value. This failed in practice: five
consecutive builds shipped "Claude Opus 5" carried forward from one old
screenshot, never rechecked, while the actual model producing later turns had
changed. Re-derive it every build; never reuse a prior turn's value.

**Mode** (Max, High, whatever effort level is selected) is different in kind, not
just in reliability. It is a UI setting with no equivalent in the model's own
context - there is no signal to check, ever, from any turn. Every mode value
shipped so far was inferred from a screenshot of the compose bar, which is
observation of the person's screen, not self-knowledge. Treat it exactly like
`--tokens-in`: supplied and exact, or blank. Never inferred, never carried
forward.

## Token estimate: likely biased low, not just imprecise

Anthropic's newer tokenizer (Opus 5, Sonnet 5, and later) produces roughly 30%
*more* tokens than earlier models for the same text. The `o200k_base` estimate
here is OpenAI's tokenizer against Anthropic content already; on current-generation
models it is probably undercounting on top of that, not merely off in an
unknown direction. Worth stating in the UI as a real bias, not just noise.

On claude.ai (the consumer product, not the API): there is no per-message token
count exposed anywhere in the product. The only usage visibility is an aggregate
weekly percentage. `--tokens-in`/`--tokens-out` are only fillable at all when the
person is calling the API directly and has the response object in hand.

## Step lines are quotations, not summaries

Blockquote step lines must be **copied character-for-character from the actual
tool-call description strings**, one line per call, in call order. They are
quotations, not a summary written afterwards.

This has failed in practice, and the failure is invisible without side-by-side
comparison: a five-step turn shipped as four, with two lines silently truncated
("omitting fields that weren't supplied" lost "rather than inventing defaults")
and the final two calls merged into one invented line. Everything still read
plausibly, and `display_text_is_verbatim` still passed - because that gate only
proves the HTML matches the input file, never that the input file matches
reality.

**Every step group, not just the first.** A turn interleaves several groups
between paragraphs, and each belongs at its own position - the code already
supports multiple blockquote blocks, so collapsing them into one block at the top
is a choice, and the wrong one. Groups that occur after the build are still
knowable: their description strings are decided before the calls are made, so
write them into the file first and then make the calls with exactly those
strings. `present_files` has no description field; the app labels it
"Presented N files", so use that.

Tool *results* are not captured at all - only descriptions. The app can expand any
step to reveal its output, and that output is where the actual evidence lives.
This is a known, unclosed gap.

There is no automated check for this. The tool-call descriptions are not written
to disk, so nothing can diff them. The only safeguard is to copy each one rather
than recalling it, with the same discipline the response prose requires. If a
step line is being typed from memory, it is already wrong.

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
