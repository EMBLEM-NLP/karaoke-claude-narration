---
type: Schema Reference
title: timing.json Word-Level Schema
description: Contract between the alignment stage and the karaoke player.
tags: [timing, manifest, schema, json, words]
---

# timing.json schema (word-level)

```json
{
  "words": [
    { "w": "This", "start": 0.0, "end": 0.26 },
    { "w": "is",   "start": 0.26, "end": 0.42 }
  ],
  "duration": 9.641
}
```

Distinct from `narrated-video-deck`'s `timing.json`, which is **section**-level
(`sections[].slide/start_s/end_s`). Same filename, different contract — do not
feed one pipeline's manifest to the other without converting.

## Invariants

- `words` is ordered by `start`, ascending, and never overlaps.
- `end - start >= 0.08` for every word. faster-whisper occasionally emits a
  zero-width word at a sentence boundary; `align_words()` floors it, because a
  zero-width word is an untappable tap target and the highlight cannot land on it.
- `start` is absolute against the final concatenated track, not relative to its
  sentence. Offsets come from the known per-sentence sample cursor, not from ASR.
- Gaps between sentences are real silence and belong to no word. The player treats
  a position more than 0.6 s past a word's `end` as "no active word" rather than
  holding the previous highlight.
- `duration` is the full track length from the concatenated PCM, and is >= the
  last word's `end`.

## Consumers

`scripts/player.html` and `scripts/player_embed_template.html` both read this
shape. A player must not assume word count matches the source script's token
count — ASR may merge or split tokens, and punctuation rides on the preceding word.
