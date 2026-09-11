---
type: Constraint Reference
title: Audio Delivery Inside the Artifact Sandbox
description: Why URL-based audio sources fail in the claude.ai artifact preview, and what works instead.
tags: [csp, media-src, web-audio, ios, safari, sandbox]
---

# Audio delivery constraints

## The failure

Assigning either a `data:` URI or a `blob:` URL to an `<audio>` element inside the
artifact preview fails with `MEDIA_ERR_SRC_NOT_SUPPORTED` (`audio.error.code === 4`).
Both are URL sources and therefore governed by the CSP `media-src` directive.
Observed on iOS Safari via the Claude mobile app.

Symptom when undiagnosed: the play button stays disabled and the readout sits at
`0:00 / 0:00`, because `loadedmetadata` never fires. This looks like a broken
button rather than a blocked resource, so **always bind an `error` listener to the
media element and surface `audio.error.code`** — otherwise the real cause is invisible.

## What works

`AudioContext.decodeAudioData()` accepts an `ArrayBuffer` already held in memory.
No resource is fetched, so `media-src` never applies. Base64-decode the embedded
audio with `atob()` into a `Uint8Array` and decode that.

This also sidesteps iOS Safari's long-standing unreliability with `blob:` URLs on
media elements.

## Costs of the Web Audio path

- `AudioBufferSourceNode` is **one-shot**: it cannot be paused, resumed, or
  repositioned. Every seek creates a new node.
- There is no `currentTime` on the node. Track position as
  `startOffset + (audioCtx.currentTime - startCtxTime) * playbackRate`.
- Changing playback rate mid-play requires re-seeking to the computed position,
  or the time math drifts.
- On iOS the context is created `suspended`; `resume()` must be called from a user
  gesture. Keep every playback entry point rooted in a click.

## Unrelated but adjacent

Do not rely on `<body>` for a page background here. The host stylesheet overrides
it in some preview contexts, which renders the page white while only
explicitly-painted elements (a fixed footer, for instance) stay dark. Paint an
inner wrapper element instead.
