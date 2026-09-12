---
type: Incident Reference
title: Delivery and iOS — Four Rules Learned on a Real Phone
description: Four rules for shipping a karaoke player that actually plays on iOS Safari, each learned from a version that passed its own checks and still failed on a real device.
tags: [ios, safari, webaudio, artifact, delivery]
---

# Delivery and iOS: four rules learned on a real phone (1.29.0)

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

See also [sandbox-audio-constraints.md](sandbox-audio-constraints.md) for the
underlying `data:`/`blob:` CSP failure these rules build on top of.
