# Changelog

All notable changes to this standalone package are documented here.
Format follows Keep a Changelog; versioning follows SemVer 2.0.0.

## [2.4.1] - 2026-09-11 — correct the published repository identity

This is a documentation and manifest correction only. The marketplace repository was created
as `EMBLEM-NLP/karaoke-claude-narration`, while 2.4.0 still advertised the old
`karaoke-narration` repository slug.

### Changed
- `.claude-plugin/plugin.json` and the marketplace manifest now point `homepage` and
  `repository` at `https://github.com/EMBLEM-NLP/karaoke-claude-narration`.
- `README.md` now registers the marketplace with
  `EMBLEM-NLP/karaoke-claude-narration`, while keeping the install command as
  `karaoke-narration@emblem-nlp`.
- The README states the naming split explicitly: repository name, plugin name, and
  marketplace name are independent Claude Code plugin identifiers.

### Unchanged
- No hook wiring, narration pipeline, QC gate, MCP behavior, or generated artifact format
  changed in this release.

## [2.4.0] - 2026-09-11 — the marketplace manifest, verified by actually installing it

2.3.0 shipped with a "Known gap" saying the marketplace manifest was deferred because its
schema could not be confirmed. It could be, from the published JSON Schema and the plugin
marketplace documentation. This release closes that gap and, unlike the claim in 2.3.0's
entry, the result was verified end to end rather than reasoned about.

### Added
- `.claude-plugin/marketplace.json` at the **marketplace repo root** (one level above this
  plugin, which now lives at `plugins/karaoke-narration/`). Marketplace `name` is
  `emblem-nlp`, so the install id is `karaoke-narration@emblem-nlp`. Structured as an org
  marketplace: further plugins are additional entries in the same `plugins` array, because
  a user can register only one marketplace per name.
- Verified, not assumed:
  - `claude plugin validate .` → passed for the marketplace manifest
  - `claude plugin validate ./plugins/karaoke-narration` → passed for the plugin manifest
  - `claude plugin marketplace add` → `Successfully added marketplace: emblem-nlp`
  - `claude plugin install karaoke-narration@emblem-nlp` → installed, enabled, user scope
  - `claude plugin details` → `Hooks (3) SessionStart, PostModelSwitch, Stop`, registered
    from the plugin with **no `~/.claude/settings.json` hook entries at all**
- `README.md` install section rebuilt around that route, with `install.sh` demoted to the
  fallback it now is.

### Fixed / documented
- **`install.sh --uninstall` can silently remove nothing.** It identifies its own entries by
  a `_karaoke` marker written into each hook object. Claude Code strips unknown keys when it
  rewrites `~/.claude/settings.json` for its own reasons — observed here when a marketplace
  install added `extraKnownMarketplaces` and `enabledPlugins` to that file. After that, the
  markers were gone, `--uninstall` reported success, and all three hook entries remained.
  Anyone switching from the script route to the marketplace route would have been left with
  both wired and every turn narrated twice. Documented in `README.md` with the manual check,
  since the marker cannot be made reliable from inside this package.

### Note on the 2.3.0 entry below
Its "Known gap" paragraph is left as written rather than edited, per this package's practice
of correcting beneath rather than rewriting. This entry is that correction: the schema was
confirmable, and the reason given there — that it could not be confirmed in that session —
was true of that session only.

## [2.3.0] - 2026-09-11 — stop arguing with the reader's guardrails; make the dependency step its own step

A review of the 2.2.0 archive declined to install it, and was right to. `install.sh`'s header
told whatever agent read it that *"an agent is additionally refused permission to write hook
configuration at all… That refusal is aimed at agents, not at you"*, and `README.md` repeated
it. Whatever the intent, that is text addressed to an automated reader arguing that a safety
boundary does not apply to it — and a package that has to talk a reader out of its own checks
in order to get installed has a packaging problem, not a reader problem.

### Changed
- `install.sh` header and the matching `README.md` passage rewritten to state the mechanism
  without the argument: this writes **user-level** hooks into `~/.claude/settings.json`, they
  run in every future session for that user rather than only the project installed from, and
  that is why it is a deliberate separate step. Same instruction, no claim about who a
  guardrail is aimed at. `--dry-run` remains the default and `--uninstall` still reverses it.
- `install.sh` is now labelled a **fallback**, with the marketplace route named first. The
  underlying problem the removed text was talking around is that this package has never
  offered the supported install path, so hand-editing a settings file was the only route it
  had. That is the real fix, and it is not in this release — see Known gap.

### Added
- `setup.sh` — installs the runtime dependencies the package does not bundle (`ffmpeg` via
  the system package manager, `piper-tts`/`faster-whisper`/`numpy` via pip), defaulting to a
  dry run that prints exactly what it would do. Deliberately separate from installing the
  plugin, because these are properties of the machine, not of the plugin: installing hooks
  installs no software, and an ephemeral container starts without them every time even when
  the plugin install itself persists. Narration-only by design — it does not install the MCP
  server's `mcp[cli]`/`fastapi`/`uvicorn`, whose one-shot install can hit an unrelated PyJWT
  pip/apt conflict.

### Known gap — the actual fix, not yet shipped
The marketplace manifest is **not** in this release. Publishing this package to a plugin
marketplace is what would let any environment install it with `/plugin install`, registering
`hooks/hooks.json` automatically with nobody editing a settings file at all — dissolving both
the reviewer's objection and the install-portability problem at once. It is deferred rather
than guessed: the manifest's filename and field names could not be confirmed from
authoritative documentation in the session that produced this release (no web access; two
research attempts were derailed by unrelated hook output leaking into their context), and a
manifest with invented field names fails silently at install, which is worse than shipping
none. Confirm the schema against the current Claude Code plugin docs, then add it.

### Unchanged
`hooks/hooks.json` already references every script through `${CLAUDE_PLUGIN_ROOT}`, which is
the correct form for a plugin-managed install, so it needs no change when the manifest lands.
No narration behaviour changed in this release.

## [2.2.0] - 2026-09-11 — the gate that catches publishing something other than the reply

Found the hard way: a QA fixture built while verifying 2.1.0 was narrated and published
over a real turn's narration at a shared artifact URL. Every existing gate passed, because
the fixture matched itself. The user read the artifact and saw 33 words of test text where
their answer should have been.

### Added
- `scripts/audit_published.py` — compares what was published against what was actually
  said. Every other gate in this package compares a build against its own inputs, which is
  why a file written beside the reply passes all of them. The reply is not data during the
  turn that produces it, so nothing inside that turn can check this; one turn later it is,
  because the `Stop` hook records `last_assistant_message`. This compares the two. Verified
  against the real incident: pointed at the published fixture and the Stop-hook record of
  the actual reply, it reports similarity 0.0604 and names the differing spans.
  - Reuses `build_karaoke.py`'s own comparison rather than restating it — `parse_blocks` →
    narrated blocks only → `_strip_inline` → `SequenceMatcher` at the same 0.995 threshold.
    A raw byte diff would false-fail on every reply containing a fenced code block, since
    fences are rendered but never narrated. That is the 1.28.0 `--verify-against` bug, and
    re-deriving the comparison in a new file would have reproduced it in a new place. There
    is a regression case for exactly this: a fenced reply that genuinely matches exits 0.
  - Tri-state exit — `0` matched, `1` diverged, `2` could not check (no Stop-hook record:
    hook disabled, or the reply fell under `KARAOKE_MIN_CHARS`). Exit 2 prints "This is NOT
    a pass". The same conflation was fixed for `source_matches_ground_truth` in 1.25.0 and
    for `check_reader_live.py` in 2.1.0; it is not repeated here.
- `SKILL.md` rule 4 — **a new artifact URL per turn, never republish over an old one.**
  Rule 2 already required a per-turn output directory; this is that rule at the publishing
  end, which is where it was still being violated. Passing the Artifact tool a `url` to
  update in place destroys that link's previous contents. Now reproduced twice: the 34-word
  reply in rule 2, and this release's fixture-over-a-real-turn.
- `README.md` and `SKILL.md`: the audit step documented as part of the loop — build,
  publish to a new URL, audit on the next turn.

### Changed
- `build_karaoke.py`: `_strip_inline` promoted from a nested closure to module level so
  `audit_published.py` can import it. Pure move, no behaviour change — it closed over
  nothing — and `tests/test_pure.py` still passes 25/25, including both `--verify-against`
  cases that exercise this path. Copying the four regexes into the new file instead would
  have created the "third text that can drift" this package warns about in
  `narrate_response.sh`.

## [2.1.0] - 2026-09-11 — dependency preflight, a broken sanctioned path fixed, and a lesson made findable

Found by installing this package for real in a fresh Claude Code Remote session and
hitting every gap this release closes, in order, on the way to a working narration.

### Added
- `scripts/preflight.sh --report`, wired as a second `SessionStart` hook entry
  alongside `version-guard.sh`. Checks `ffmpeg`/`ffprobe`/`piper` on PATH and
  `numpy`/`piper`/`faster_whisper` importable, `tiktoken` reported as optional. Real
  install attempts failed on these three times in sequence — `numpy` missing, then
  `ffmpeg`, then `faster-whisper` — each visible only as a buried async failure in
  `~/.karaoke-narration/hook.log`, never up front. Deliberately scoped to only the
  narration path's own minimal dependencies: recommending `pip install -r
  requirements.txt` here would also pull in the separate MCP server's dependencies
  (`mcp[cli]`, `fastapi`, `uvicorn`) and reproduce a real `PyJWT` pip/apt conflict hit
  during the same install attempt. Read-only, no network, always exits 0 — same
  safety contract as `version-guard.sh`.
- `README.md`: an `apt-get install -y ffmpeg` line next to the existing pip command.
  `ffmpeg`/`ffprobe` are system binaries, not pip packages, and the README's install
  section never said so — a real, silent gap, not a documentation nicety.
- `README.md` and `SKILL.md`: both now point at `scripts/narrate_response.sh` from the
  `Stop`-hook section itself, not just from further down the file. Added after a real
  session read the hook section, concluded the Stop hook's one-turn lag (it can only
  narrate the *previous* reply, never the one it fires on) was unavoidable, and spent
  several turns manually reinventing a worse version of a script the package already
  shipped in 1.30.0.

### Fixed
- `skills/karaoke-narration/scripts/finish_turn.sh` — its own header calls it "the ONLY
  sanctioned way to produce a turn artifact," but it packed only the plain
  (non-`--artifact`) HTML variant, directly contradicting this file's own rule one
  section up: "Deliver as an Artifact, never as a file attachment... a file attachment
  renders in a static preview that does not execute JavaScript." Reproduced live: a
  manually-built plain HTML file, sent as an attachment, showed a stuck "loading
  player…" screen indefinitely. Now emits both variants, matching the convention
  `stop_hook.py` already used — `response_standalone.html` for local file access,
  `response_artifact.html` for the Artifact tool — and stages both.
- `scripts/narrate_response.sh` conflated `check_reader_live.py`'s own documented
  exit code 2 ("could not run" — e.g. `playwright` not installed) with exit code 1
  (a real simulation failure), aborting under `set -e` in both cases even when the
  narration itself had already been built and had already passed every real QC gate.
  Found running this release's own end-to-end verification without `playwright`
  installed. Now branches on the exit code: 1 still aborts as a genuine failure, 2
  prints a clear "SKIPPED (could not run - ...)" line and the script still publishes
  the artifact it already correctly built. `playwright` added to `preflight.sh` as an
  optional check so the gap is visible up front rather than discovered mid-publish.

### Unchanged
`build_karaoke.py`, `pack_standalone.py`, `stop_hook.py`, `record_model.py`, the MCP
server, `validate_timing.py`, and `check_reader_live.py` itself — all confirmed already
correct for this release's use case. This release is a preflight addition, two
sibling-script exit-code/packing fixes, and documentation findability; the core
narration pipeline's behavior did not change.

## [2.0.0] - 2026-09-10 — standalone repo, current hook spec, and an install path that survives being refused

Major because the package no longer sits inside a monorepo, the shipped layout changed, and
the hook definitions moved to a form older Claude Code builds do not parse.

### Added
- `scripts/record_model.py` and a `PostModelSwitch` hook entry — the first fresh source of
  model identity the Stop path has ever had. `stop_hook.py` documented at length that the
  Stop payload carries no model, leaving `KARAOKE_MODEL`/`KARAOKE_MODEL_ID` — set by hand,
  stale by default — as the only option; five consecutive builds once shipped a model name
  the session had already moved off. `PostModelSwitch` fires exactly when that value
  changes, so recording it there is the one place the answer is reliably correct.
  Precedence is now recorded-file → env vars → no attribution.
- `install.sh`, a human-run installer that merges the hooks into `~/.claude/settings.json`
  with `jq`, defaulting to `--dry-run` and offering `--uninstall`. It exists because both
  documented install routes proved unavailable in practice: `/plugin install` needs a
  marketplace listing this package does not have, and `--plugin-dir` is a startup flag that
  cannot be applied to an already-running session. On some surfaces an agent is refused
  permission to write hook configuration at all — as a category, independent of which file
  or tool it goes through — so the step had to become something a person runs. Entries carry
  a `_karaoke` marker so `--uninstall` removes exactly what was added and nothing adjacent.
- `statusMessage` on the Stop hook. A build budgeted at 540 s previously ran with no
  indication that anything was happening.

### Changed
- Both hooks migrated from shell-form `command` strings to exec form (`command` + `args[]`).
  Paths are substituted per element and spawned directly, so `${CLAUDE_PLUGIN_ROOT}` no
  longer passes through a shell parser and no longer needs hand-quoting.
- `stop_hook.py`'s `CLAUDE_PLUGIN_ROOT` fallback is documented as load-bearing rather than
  incidental: it is unset for every hand-wired install, which is the only kind `install.sh`
  performs.
- `SECURITY.md` rewritten for standalone distribution; the model-attribution entry moved
  from "known limitation, no fix at this layer" to a description of the fix and its two
  residual caveats.
- `README.md` rewritten around the three runtimes that actually exist.

### Removed
- `skills/karaoke-narration/assets/demo/` (~1.4 MB). Demo audio, timing and readers are
  reproducible from `build_karaoke.py` and do not belong in version control.
- The `../emblem-agi-out/...` sibling-tree copy at the end of `finish_turn.sh`, dead in a
  standalone checkout.
- `metadata.marketplace` from `SKILL.md`, and the monorepo `homepage`/`repository` URLs from
  `plugin.json`.
- `scripts/claude_code_settings.example.json`, superseded by `install.sh`. It was a template
  requiring a manual `ABSOLUTE_PATH_TO_PLUGIN` substitution, still written in shell form, and
  it predated `PostModelSwitch` — a hand-edit fallback that contradicted the shipped
  `hooks/hooks.json` is worse than no fallback. `install.sh` emits the same three hooks with
  real paths already filled in.

### Fixed
- `interop/README.md` listed `finish_turn.portable.patch` among its artifacts; no such file
  has ever shipped. The gap it claimed to close was already fixed inside `finish_turn.sh`
  via the `KARAOKE_OUT_DIR` override, and the table now says so.
- `interop/README.md` described the `schema_version` migration as pending work.
  `build_karaoke.py` has emitted `"schema_version": "1.0"` since before this release, so
  `--require-version` is documented as a live gate rather than a future one.
- `references/index.md` cited `docs/SOP.md §2`, a monorepo document absent from this
  package; the rule it referenced is now stated inline. Same for the `emblem-agi SOP.md C2`
  citation in `version-guard.sh`'s drift message.

## [1.30.0] - 2026-09-09 — a wrapper for narrating a real turn, and the rules it enforces

The player worked; using it correctly turned out to be the harder half. Everything here
comes from delivering narration to a phone for a whole session and getting it wrong three
distinct ways.

### Added
- `scripts/narrate_response.sh` — narrates a real chat turn verbatim. Takes a turn
  directory, a title, and any number of `Label:file` pairs; writes the ground-truth
  concatenation itself, builds with `--verify-against`, packs the artifact fragment, and
  runs the timing and live-reader checks. Any gate failure exits non-zero **before** packing,
  so a build that did not pass is never publishable.
  Variadic because `build_karaoke.py` is: its input is "one or more .md/.txt files, EACH
  FILE IS ONE TURN". A wrapper hardcoding two was narrower than the tool underneath.
- SKILL.md gains "Narrating a real turn": narrate the reply itself rather than a script
  written beside it; one output directory per turn; publish and let the artifact card speak.
  Plus the parser constraints that change how you must write — no tables, one-word link
  labels, fenced code, ~800 words.

### Why these are rules and not suggestions
- **The fidelity gate was decorative for seven builds.** Each reported
  `source_matches_ground_truth: NOT CHECKED`, because the narrated script was composed
  alongside the reply and no ground truth existed. A gate with nothing to compare against
  reports nothing, which is indistinguishable from passing if you do not read it.
- **A shared output path destroys history.** Artifact publishing is keyed to the path, so
  republishing one "latest" path means every turn overwrites the last. A 34-word reply
  destroyed a 369-word narration; only the final turn survived at that URL.
- **A multi-word link label fails the verbatim gate.** `clean_token` maps one source token
  to one display token, so `[latest narration](url)` renders as two tokens against one
  expected. Caught by the gate on a real build, which is the gate doing its job.

### Unchanged
Player, builder and the interop kit are exactly as shipped in 1.29.2. `stop_hook.py` needed
no change: it narrates `last_assistant_message`, so it was verbatim by construction all
along. The fidelity failure was in manual use of the tool, not in the plugin.

### Known gap
No automated test covers the wrapper. `tests/test_pure.py` imports `build_karaoke.py` and
tests pure Python; the wrapper is bash and the package has no harness for shell entry points.
Its guarantees are exercised by running it once per release, not on every change.

## [1.29.2] - 2026-09-09 — on-device diagnosability, from the review's third lens

Error paths and status text only; playback behaviour unchanged.

### Fixed
- `decodeInto()`'s `.catch` had no rethrow, so it RESOLVED on every decode failure
  and `ensureAudioReady()` reported a generic "produced no audio buffer" in place
  of the real `DOMException`. Rethrown.
- WebKit's legacy error callback can pass `null` or a bare `DOMException` with an
  empty message, rendering "Decode failed: null". The rejection is now normalised
  to name/message plus buffer size, context state and sample rate - one string
  that separates a codec rejection, a detached buffer and a non-running context on
  a device with no debugger.
- The decoding status now reads `decoding (ctx <state>, <rate> Hz)`. The reviewer's
  point stands: that readout alone would have answered the suspended-context
  question on the phone, with no further instrumentation.

### Changed
- `--bitrate` help states that values below 32k switch LAME to MPEG-2 LSF at
  22050 Hz - a less-exercised WebKit decode path than the 44.1 kHz default. It
  decoded and played on the test iPhone, but the only reason to go below 32k was a
  size theory the 167 KB test refuted. Default remains 32k; prefer shorter turns
  over lower bitrate when size matters.

### Reviewed and left alone
- "decodeAudioData detaches the ArrayBuffer, so retry is impossible": stale against
  the shipped code. `b64ToArrayBuffer()` runs inside the promise executor, so every
  retry builds a fresh buffer.
- The base64 payload was verified byte-clean by the review; `atob` is ruled out as
  a cause of the original failure. Remaining candidates: the byte loop under memory
  pressure, the script dying earlier, or a decode that never settled.

## [1.29.1] - 2026-09-09 — correction: the fix stands, the stated cause does not

Documentation and comments only; no behaviour change from 1.29.0.

### Corrected
- 1.29.0's entry below, the template comments, SKILL.md and `check_reader_live.py`
  stated as fact that WebKit withholds both `decodeAudioData` callbacks on a
  non-running context. An adversarial review refuted that as unproven: WebKit's
  decoder posts its result through the event loop without consulting context
  state, and the eager-decode-then-unlock pattern used by howler.js and Tone.js
  works on iOS. The 1.29.0 fix moved the base64 decode, the byte loop AND
  `decodeAudioData` behind the first tap together, so it cures several rival
  causes at once and cannot identify which was real. What IS established, on the
  device: 1.28.0 never enabled playback; 1.29.0 plays. The 1.29.0 text is left as
  written; this entry is the correction beneath it.
- A boot comment in the template still blamed "a JS memory ceiling", a diagnosis
  the 167 KB-versus-1.1 MB test had already refuted. Withdrawn in place.
- `check_reader_live.py` now describes its two simulations as robustness
  properties the reader must have under any mechanism, not as WebKit behaviour.

### Still true and unchanged
- A file attachment renders in a static preview that does not execute
  JavaScript; delivery must be an Artifact. Verified independently of the decode
  question: identical failure at 167 KB and 1.1 MB, hardcoded boot text on
  screen, no dynamic content of any kind.
- `=== 'suspended'` skips WebKit's `'interrupted'` state and would block playback
  resume; `!== 'running'` is correct. This gates resume, not decode.

### The experiment that would settle it
On the 1.28.0 artifact build, wait past the 20 s watchdog. A status change proves
the event loop was alive and decode genuinely never settled; no change places the
failure upstream of `decodeAudioData`. Then load the identical file first-party in
mobile Safari and inside the artifact frame, on the same device.

## [1.29.0] - 2026-09-09 — the player did not work on a phone, and the checks said it did

Found by delivering narration to an iPhone and getting `decoding audio…` with no
transcript and no playback, every time. Three diagnoses were wrong before the right
one; each is recorded in the skill's new "Delivery and iOS" section rather than
overwritten.

### Fixed
- **Deadlock on iOS.** `AudioContext` was constructed and `decodeAudioData` called at
  page load, outside any gesture; WebKit never invoked either callback; the play
  button was enabled only inside that callback. Decode is now gesture-gated: resume,
  silent-buffer unlock, then decode, all from the first tap. Transcript renders at
  load and never waits on audio. (`player_embed_template.html`)
- **`'interrupted'` state unhandled.** Both resume sites tested `=== 'suspended'`,
  which skips WebKit's non-standard `'interrupted'` and reproduces the same hang.
  Now `!== 'running'`, with `statechange`/`visibilitychange` teardown and rebuild of
  a closed context.
- **Dead entry points.** Word-click, turn-head click and Space early-returned on no
  buffer, so before the first play-button tap they silently did nothing. All route
  through one `startAt()` that loads on demand.
- **Watchdog race.** A decode settling after the 25 s watchdog had reported would
  wipe the report with `setStatus('')`. Guarded with a cancelled flag.
- **`--bitrate` below 32k silently ignored.** LAME cannot encode under 32 kbps at the
  hard-coded 44100 Hz (MPEG-1 Layer III floor) and clamped: `--bitrate 16k` produced a
  byte-identical 32k file. Sample rate now follows bitrate (22050 Hz under 32k).
  Verified `bit_rate=16000`; a 3-minute player fell from 1113 KB to 616 KB.
  (`build_karaoke.py`)
- **Boot status indistinguishable from mid-decode.** The markup's hard-coded status
  was the same string `decodeInto()` writes, so a page whose script never ran looked
  identical to one still decoding. Now `loading player…`, visible only when the
  script did not run.
- `markerTimes` was an implicit sloppy-mode global; declared.
- `finish_turn.sh` hard-coded `/mnt/user-data/outputs`, which exists in one
  environment; now honours `KARAOKE_OUT_DIR`, then that path if present, else `./out`.

### Added
- `pack_standalone.py --artifact`: emits the fragment the Artifact tool needs (host
  supplies doctype/head/body). Exits non-zero if the fragment would carry no script.
  **A file attachment renders in a static preview that never runs JavaScript**; this
  is the only delivery that works on claude.ai and the one SKILL.md always intended.
- `pack_standalone.py --title`, HTML-escaped; the default produced artifacts named
  "Chat response — response".
- `schema_version: "1.0"` on every manifest.
- `interop/`: `validate_timing.py`, `check_reader.py`, `timing_schema.json` (the
  conformance kit), and `check_reader_live.py`, which simulates WebKit's audio gating
  in Chromium and fails the pre-1.29.0 template — its negative control. The static
  `check_reader.py` passed every file that hung on the phone; presence of
  `.resume()` is not sequencing.
- `stop_hook.py` also writes `response_artifact.html` per turn.
- `#app` gets `min-height:100dvh` with the `vh` fallback, for the iOS dynamic toolbar.

### Known, not fixed
- `footer{position:fixed}` and the hard-coded 164px transcript clearance are flagged
  by review as fragile in a short iOS iframe; left alone because the working device
  showed them rendering correctly, and a layout change was not going to be verified
  on that device this release.
- `stop_hook.py` still stamps `KARAOKE_MODEL`/`KARAOKE_MODEL_ID` from the environment
  if set. Leave them unset. The byline trap this project documents was reproduced
  during this very release.

## [1.28.0] - 2026-07-27 — fenced-coda convention, and the bug that shipping it found

### Fixed
- **Half of turn 6's response never reached the build.** 3 of 8 sections (83
  of 337 words) were appended after the narration ran, separated only by a
  `---` divider — never stated in words as excluded. Same root cause as turns
  1 and 3 in different clothes: reporting a build's own results requires
  writing them after the build, and nothing forced that boundary to be
  explicit.
- **The fix is not a new convention to remember — it's the tool's own
  existing exemption.** A fenced code block is already shown in the display
  and never narrated (`parse_blocks`'s `narrated: False` for `type: code`),
  the same rule that already governs why a bash command in a response isn't
  read aloud. Any post-hoc build-report coda now goes inside a fence:
  mechanically excluded by the parser, not by a divider I have to explain.
- **Testing that convention surfaced a real bug in `--verify-against`.** The
  ground-truth comparison built `truth` from the raw file (code fence
  included) but `mine` only from narrated blocks (fence excluded) — apples to
  oranges. A file containing a fenced coda FAILED verify-against *itself*.
  Fixed by stripping fences from `truth` the same way `mine` already excludes
  them. Verified both directions: the self-comparison now passes, and a
  genuine divergence (unrelated text) still fails — a fix that also silenced
  real mismatches would be worse than the bug it replaced.
- Harness now 25 assertions (two new: the fence fix, and a guard that it
  didn't make the check fail-open again).

## [1.27.0] - 2026-07-27 — build latency resolved and documented

### Added
- `references/build-latency.md` — the 1-CPU constraint that killed two builds,
  written down with measured numbers rather than estimates: `WhisperModel("base",
  float32)` costs **25.7 s just to load** on one core, before any per-sentence
  work. Registered in the OKF bundle index.

### Resolved
- Narration builds timing out at ~28 sentences. **Cause was neither the code nor
  the recent edits** — the same script completed a 28-sentence build in the same
  environment earlier. It is `nproc` = 1 against a deliberately slow alignment
  config (`float32` + `beam_size=5`), both chosen for determinism per
  `whisper-tts-reliability.md` and correctly left alone.
- The fix is in how the build is launched. `nohup … &` does **not** survive
  between tool calls; `setsid nohup … < /dev/null &` does. `nohup` only ignores
  SIGHUP, while `setsid` moves the process into a new session with no
  controlling terminal. Verified with a marker process observed alive in a
  later call, not assumed. First build to complete under this method: 16
  sentences, 319 words, 95% avg match.

### Explicitly rejected
- Shortening narration text to fit the timeout. That manufactures a second
  draft, which is the exact failure `--verify-against` exists to catch.

## [1.26.0] - 2026-07-26 — drift detection + packaging fix

### Added
- `scripts/qc_log.py` — across-build drift detection. The QC gate is a
  *within*-build check against fixed thresholds; it cannot see a metric sliding
  over six builds while never crossing one. This keeps history and compares.
  - **Split by determinism**, same as the test harness: ASR-derived metrics get
    wide bands (that stage is documented non-deterministic), ffmpeg-derived ones
    (loudness, true peak, distortion) are deterministic so any movement is real.
  - **Median + MAD, not mean + stdev.** Build counts are small and outliers are
    the thing being hunted; one bad build would inflate stdev enough to mask the
    next three. Threshold is the Iglewicz & Hoaglin modified z-score, |z| > 3.5.
  - **Refuses to report below 5 prior builds.** Claiming drift from three builds
    would repeat the vacuous-PASS mistake in a new place.
  - Structural metrics (words, sentences, duration) are logged as context and
    never alerted on — they track the input, not the pipeline.
  - Logs the tri-state ground-truth value, so a long run of unverified builds is
    visible as a pattern rather than invisible one build at a time.
- `finish_turn.sh` now records every build into the drift log (non-fatal).
- Two harness fixtures locking in both fixes below. Suite: 23 assertions.

### Fixed
- **A 63MB voice model was packaged into the 1.25.0 release zip**, inflating it
  from 1.8MB to 65MB. Cause: `--voices-dir` defaulted to the *relative* path
  `"voices"`, so the model cached into whatever directory the build ran from —
  three copies landed on disk and one ended up inside the package. The default
  is now absolute (under the same state dir the Stop hook uses), and a
  `.gitignore` excludes `voices/`, `state/`, `test/`, `__pycache__/`.
  **1.25.0 should not be distributed.**

### Known, unresolved
- Narration builds time out in a 1-CPU container at ~28 sentences. Diagnosed as
  CPU contention (`nproc` = 1), not the code: the same script completed 28
  sentences earlier in the same environment. `narrated-video-deck`'s SKILL.md
  documents the same class of limit for whisper on 1-CPU containers.

## [1.25.0] - 2026-07-26 — regression harness + fail-closed ground-truth gate

### Added
- `skills/karaoke-narration/tests/test_pure.py` — the first test suite this
  plugin has ever had. 20 assertions, stdlib only, no dependencies, runs in
  milliseconds. Deliberately scoped to the DETERMINISTIC layer: pure
  markdown/text/timing functions plus subprocess refusal codes. Nothing
  downstream of ASR is asserted exactly, because
  `references/whisper-tts-reliability.md` documents that stage as
  non-deterministic even after the float32 fix (0.38 vs 0.75 on the same
  sentence across two runs). A flaky suite gets ignored, which is worse than
  no suite.
- Every case carries the provenance of the real failure it encodes — missing
  em dashes, zero-width words, the three-layer collapse, the table gap, the
  three refusal exit codes. None are invented.

### Fixed
- **`source_matches_ground_truth` was fail-open.** `ground_ok` initialised to
  `True` and was only evaluated when `--verify-against` was supplied, so a
  build with no ground truth printed `PASS` — which reads as "the source
  matched reality" but means "nothing was compared". Now tri-state:
  `None` = NOT CHECKED, excluded from the overall pass computation (rather
  than hard-failing legitimate builds, since on claude.ai ground truth cannot
  exist until the turn has ended), and printed as `NOT CHECKED` with an
  explanation. Verified the FAIL path still fails after the change.

### Contract note (judgment call, flagged rather than buried)
- `timing.json` now emits `null` rather than `true` for
  `qc.checks.source_matches_ground_truth` when no ground truth was supplied.
  Checked both shipped players (`player.html`, `player_embed_template.html`):
  neither reads `qc.checks`, so no shipped consumer breaks. Classified MINOR
  on that basis. An external consumer of the manifest that treats the key as
  strictly boolean would need updating — hence this note.



All notable changes to this standalone package are documented here.
Format follows Keep a Changelog; versioning follows SemVer 2.0.0.

## [1.24.0] - 2026-07-26 — standalone refactor

Extracted from the `emblem-agi` monorepo (where it shipped as `plugins/karaoke-narration`
at the same `1.23.0` this package's logic was built from) for independent distribution.
No narration behavior changed — every change below is packaging, documentation, or
drift-safety infrastructure this plugin loses by leaving the monorepo, restored locally.

### Added
- `VERSION` — this plugin's own single source of truth, since it no longer shares the
  monorepo's root `/VERSION`. Per `emblem-agi/docs/SOP.md` §11: "if a plugin ships on a
  genuinely independent schedule, move VERSION into the plugin directory."
- `scripts/version-guard.sh` — adapted from the monorepo's shared, glob-based version
  of this script, rescoped to check only this plugin's own surfaces (no `plugins/*/`
  wildcard, since there's only one plugin here now).
- `hooks/hooks.json`: a `SessionStart` entry running the new version-guard in `--report`
  mode. Satisfies the same hook-safety table the monorepo's `docs/SOP.md` §7 states for
  every hook: no network, no filesystem writes, fixed-vocabulary output, always exits 0,
  bounded runtime (~50ms, 10s timeout).
- `LICENSE` — this plugin previously relied on the monorepo root's LICENSE file, which
  does not travel with a standalone extraction.
- `SECURITY.md` — the monorepo's root `SECURITY.md` covered only `ffmpeg-video-conversion`'s
  threat model and never mentioned this plugin's `Stop` hook or MCP server. This is that
  gap closed, scoped correctly to what this plugin actually does.

### Fixed / clarified
- `scripts/stop_hook.py`: added an inline comment at the exact line reading
  `KARAOKE_MODEL`/`KARAOKE_MODEL_ID`, documenting the known staleness risk described in
  `SKILL.md` ("five consecutive builds shipped 'Claude Opus 5'" after the model had
  changed) at the point in the code where it can actually occur, not just in prose
  elsewhere. Not a behavior change — the hook already correctly omits attribution when
  these vars are unset; this makes the risk visible to the next person editing the file.
- `README.md`: no longer assumes a shared monorepo root (`docs/SOP.md`, root `NOTICE`,
  sibling plugins). Rewritten to be self-contained for standalone install.

### Unchanged
- The Stop hook's opt-in gate, content filtering, async/timeout behavior, and local-only
  TTS/ASR pipeline are exactly as they were at `1.23.0`. See the monorepo's own
  `CHANGELOG.md` (versions 1.19.0–1.23.0) for the history of that pipeline's development.
- The MCP server (`mcp/server.py`) is unchanged and still not auto-wired — installing this
  plugin does not start it; see `mcp/README.md`.

## Prior history

Versions 1.19.0 through 1.23.0 were developed inside `emblem-agi`. See that repository's
`CHANGELOG.md` for the ground-truth-verification, MCP server, and credential-handling design
history that produced the code this package now ships standalone.
