---
okf_version: "0.1"
type: Knowledge Bundle Index
title: Karaoke Narration Reference Bundle
description: Word-timing manifest schema and sandbox audio-delivery constraints supporting the karaoke-narration skill.
---

# Karaoke Narration Reference Bundle

Conforms to Open Knowledge Format (OKF) v0.1. `okf_version` declares the **specification**
version, not this package's release version. They are independent axes: the spec version
moves when the bundle format changes, the release version when the package ships. Equality
between them is evidence one was copied from the other, which is why `version-guard.sh`
reports it as drift rather than as agreement.

- [word-timing-schema.md](word-timing-schema.md) — the `timing.json` word-level contract
- [sandbox-audio-constraints.md](sandbox-audio-constraints.md) — why URL-based audio fails in the artifact preview
- [whisper-tts-reliability.md](whisper-tts-reliability.md) — why int8 quantization was silently corrupting alignment, and how it was isolated
- [credential-handling.md](credential-handling.md) — why encrypting a secret into a conversation cannot protect it, and what does
- [token-accuracy.md](token-accuracy.md) — no published tokenizer for current models; why input can never be recovered
- [artifact-size-constraints.md](artifact-size-constraints.md) — an embedded-audio HTML artifact that failed to load on mobile, and why
- [build-latency.md](build-latency.md) — measured cost of the float32 alignment stage on one core, and how to run a build that outlives a single tool call
- [ios-audio-delivery.md](ios-audio-delivery.md) — four rules learned shipping a working karaoke player to a real iPhone
- [model-attribution.md](model-attribution.md) — why model name must be re-derived every build while attribution mode can never be inferred
- [tool-call-quotation.md](tool-call-quotation.md) — why step lines describing tool calls must be verbatim quotations, never a recalled summary
