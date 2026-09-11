---
type: Investigation Reference
title: Whisper Reliability on Synthetic TTS Audio
description: Why per-sentence ASR alignment was unreliable, the dead ends ruled out, and the actual fix.
tags: [whisper, faster-whisper, determinism, int8, quantization, reliability]
---

# Whisper reliability on synthetic TTS audio

## Symptom

Fallback rate (sentences where ASR's returned token count didn't exactly match
the expected count) was 10-12 out of 13 sentences on a real 233-word response,
versus 2 of 3 on a 3-sentence test string. The short test never exposed this.

## First (wrong) hypothesis: sentence complexity

Assumed long, acronym-dense sentences were harder to align. Partially true, but
not the dominant effect - see the determinism finding below, which came first
chronologically once instrumented.

## Dead end 1: exact-count matching was too brittle

The original design discarded ALL of a sentence's ASR timing the moment the
returned count didn't exactly equal expected - so one misrecognized word
("highlighted" heard as "translated") threw away 22 good timings along with the
1 bad one. Fixed by replacing exact-match-or-discard with `difflib`-based fuzzy
sequence alignment (`align_spoken_tokens()`): real matches keep their real
timing, only genuinely unmatched stretches get interpolated between their
nearest real neighbors. This surfaced `avg_word_match_rate` as an honest
continuous metric instead of a boolean, which is what made the next problem
visible instead of averaged away.

## Dead end 2: assumed beam_size=1 + initial_prompt was the cause

Isolated on individual failing clips: `beam_size=1` (greedy decoding) combined
with passing the known sentence as `initial_prompt` regularly produced zero
segments, 3-4 word truncation, or phrase-repetition loops. Switching to
`beam_size=5` with no prompt recovered real content in every tested case.
**Genuine improvement, but not sufficient alone** - see below.

## The actual root cause: int8 quantization, not decoding strategy

Running the identical clip through the identical loaded model 3 times produced
3 different results - including a straight repetition-loop hallucination
("the more, the more, the, the that that that...") on one call and, on a
separate fresh model load, a well-documented Whisper hallucination artifact
("Thank you for watching my video") that has nothing to do with the input audio
at all. That ruled out sentence content as the explanation.

Tested and ruled out, in order:
- `temperature=0.0` (disables Whisper's stochastic sampling fallback chain) -
  no effect. Still 3 different results across 3 runs.
- `cpu_threads=1` (removes multi-thread parallel-reduction order as a variance
  source) - no effect, including a hallucination on the very first call.

Isolated by direct comparison: `compute_type="float32"` on the same clip
returned the **identical 24-word result, bit-for-bit, on 3 of 3 consecutive
calls**, with substantially better content than any `int8` run. `int8`
quantization was the actual source of both the run-to-run non-determinism and a
real share of the accuracy loss - not the beam search algorithm, not threading,
not decoding policy.

## Result

`avg_word_match_rate` on the same 233-word response went from a chaotic
24-69% swinging wildly between identical runs, to a stable 83-86%. This is a
large, real improvement - not a full solve. Run-to-run variance is much
smaller but not zero at full-pipeline scale (one sentence showed 0.38 vs 0.75
between two float32 runs); the isolated single-clip test was perfectly
reproducible, so something sentence-specific still varies occasionally even
under float32. Not yet root-caused further - flagged, not hidden.

## Practical takeaway

If a future change to this pipeline (different Whisper model size, different
TTS voice, different clip lengths) brings back a low `avg_word_match_rate` or
run-to-run instability, **check `compute_type` before anything else.** It is by
far the largest lever found here, larger than decoding parameters, larger than
prompting strategy.

## Checked against faster-whisper's own documentation

Queried the official faster-whisper docs (via Context7) after reaching the
float32 conclusion. **The docs do not support the finding above, and mildly
contradict it.** They describe int8 as delivering the same accuracy as
openai/whisper with lower memory, and present 8-bit quantization purely as an
efficiency improvement suitable for edge deployment. No non-determinism is
documented for int8 anywhere in the official material.

So treat the result above as an empirical observation specific to this
workload - short, isolated, synthetic-TTS clips with flat prosody, which is
well outside typical Whisper input - and not as documented library behavior.
It reproduced consistently here (3 of 3 identical float32 results vs 3 of 3
divergent int8 results on the same clip and same loaded model), but the
mechanism is not confirmed by upstream docs and could be workload-specific
rather than a general property of int8.
