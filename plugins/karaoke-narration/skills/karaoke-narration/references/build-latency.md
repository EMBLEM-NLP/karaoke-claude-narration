---
type: Constraint Reference
title: Build Latency on Single-CPU Containers
description: Measured cost of the float32 alignment stage on one core, why it is deliberate, and how to run a build that outlives a single tool call.
tags: [performance, cpu, whisper, float32, latency, sandbox]
---

# Build latency on single-CPU containers

## The failure

A 28-sentence narration build was killed twice by a command execution timeout,
stopping partway through synthesis. The first diagnosis attempt blamed recent
edits to `build_karaoke.py`. That was wrong — the same script had completed a
28-sentence build in the same environment earlier the same session.

## Measured, not estimated

On a container reporting `nproc` = 1:

| Stage | Cost |
|---|---|
| `WhisperModel("base", compute_type="float32")` load | **25.7 s**, once per build |
| Piper synthesis | per sentence, sequential |
| faster-whisper alignment, `beam_size=5` | per sentence, sequential |

The two per-sentence stages dominate and scale linearly with sentence count.
A build is therefore roughly `25.7s + (n × per-sentence cost)`, with no
parallelism available to amortise it.

## Why the slow configuration is correct anyway

Both expensive choices are deliberate and documented in
`whisper-tts-reliability.md`:

- **`compute_type="float32"`, not `int8`.** The same clip through the same
  loaded int8 model returned a different result on 3 of 3 consecutive calls,
  including a repetition-loop hallucination. float32 returned an identical
  result 3 of 3.
- **`beam_size=5`, no `initial_prompt`.** Greedy decoding with a prompt
  regularly produced zero segments or truncation.

Speed was traded for determinism on purpose. Do not "fix" the latency by
reverting either one — that reintroduces a documented correctness bug to solve
a performance problem.

## Running a build that outlives one tool call

The distinction that matters, verified directly rather than assumed:

```bash
# DOES NOT survive between tool calls — observed dying mid-synthesis
nohup bash scripts/finish_turn.sh state/turn.md > log 2>&1 &

# DOES survive — verified with a marker process checked in a later call
setsid nohup bash scripts/finish_turn.sh state/turn.md > log 2>&1 < /dev/null &
```

`nohup` only makes the process ignore `SIGHUP`. `setsid` puts it in a new
session with no controlling terminal, so it is not in the process group that
gets torn down when the invoking shell ends. Redirecting stdin from
`/dev/null` matters too: a background job that reads from a closed terminal
stops.

Then poll `log` across subsequent calls rather than blocking inside one.

## Practical guidance

- **Do not shorten the text to fit the timeout.** That is how a second draft
  gets written, which is the failure mode `--verify-against` exists to catch.
  Detach the build instead.
- If a genuinely faster path is needed, `--whisper-model tiny` is the lever to
  reach for first — it changes alignment accuracy, not determinism. Measure the
  resulting `avg_word_match_rate` against baseline via `scripts/qc_log.py`
  before adopting it.
- `narrated-video-deck`'s `SKILL.md` documents the same class of limit for its
  own whisper stage ("1-CPU containers: whisper base/int8 takes roughly 2–4
  minutes for 8 minutes of audio"). This is a property of the environment, not
  of either skill.
