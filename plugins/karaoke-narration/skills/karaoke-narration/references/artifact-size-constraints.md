---
type: Constraint Reference
title: Standalone Artifact Size in the claude.ai Mobile Preview
description: Empirically observed load failure at large embedded-audio file sizes, and the fix.
tags: [artifact, mobile, file-size, base64, bitrate]
---

# Artifact size constraint (empirical, not documented)

## What happened

A standalone karaoke player with 263s of embedded base64 audio at 128kbps mp3
(~5.7MB total HTML) failed to load in the claude.ai mobile app artifact preview:
"Couldn't load file", no further detail. A smaller player from the same
pipeline, ~2MB, loaded and played correctly.

Checked Anthropic's own documentation before writing this down: **there is no
published byte-size limit for this specific rendering path.** The documented
30MB figure is for the file-creation tool's upload/download surface, a
different code path from an artifact's own embedded content loaded in the
in-app preview. So this is empirical, not official - a real, reproduced result
from this project, not a confirmed platform ceiling.

## The fix

`pack_standalone.py`'s dominant size cost is the base64-embedded audio, not the
JS/CSS shell. `build_karaoke.py`'s default `--bitrate` is now `32k` mono
(was `128k`). This is spoken-word content, not music - 32k mono loses nothing
that matters for reviewing whether words line up with audio. On a 263s clip
this cut the standalone artifact from ~5.7MB to ~1.5MB, verified to still load
and play correctly, with loudness holding at -17.0 LUFS against a -16 target
(re-encoding lossy-to-lossy always drifts slightly; this is normal, not a defect).

## Guardrail

`pack_standalone.py` prints a warning above 4000 KB and a softer note above
2500 KB, framed as empirical bands with margin, not as if they were documented
limits - because they aren't. If a future response is long enough to still
exceed even 32k mono, the options in order of preference: lower the bitrate
further (speech stays intelligible well below 32k), or don't embed - fall back
to the multi-file `player.html` loader for local/Claude Code use where real
file access exists and this constraint doesn't apply.
