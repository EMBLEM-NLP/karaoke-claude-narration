# karaoke-interop — conformance kit v1.0

Three artifacts that close the interoperability gaps found in v1.28.0.
Stdlib only, no install step.

| file | closes |
|---|---|
| `timing_schema.json` | the published reference documented 2 of the 8 keys the builder emits, with no version field |
| `validate_timing.py` | that contract, executable, with a negative control |
| `check_reader.py` | reader portability: external deps, sandbox rules, iOS, and the size ceiling as a derived number |

A fourth gap — the hardcoded `/mnt/user-data/outputs` path in the mandated
entrypoint — was closed in the entrypoint itself rather than by a shipped patch
file: `finish_turn.sh` honours `KARAOKE_OUT_DIR`, falls back to the sandbox path
only when it genuinely exists, and otherwise stages to `./out`.

## Use

```sh
python3 validate_timing.py out/narration.timing.json
python3 validate_timing.py out/narration.timing.json --require-version --strict   # CI
python3 check_reader.py out/narration_review.html --timing out/narration.timing.json
```

Exit codes: `0` conformant, `1` findings, `2` unreadable input. Both take `--json`.

## Verified against the real artifacts

Re-derived for 2.0.0 against a freshly built 93-word / 40s narration:

```
attributed build          PASS  0 errors, 0 warnings          --require-version --strict
same build, unattributed  FAIL  0 errors, 1 warning           W-NO-ATTRIBUTION, promoted by --strict
its reader                PASS  0 blocking, 2 advisory        blob: x2, <audio> x1
deliberately broken       FAIL  5 errors, 1 warning           <- the negative control
```

The middle row is the interesting one: an otherwise-clean build fails `--strict` purely for
lacking provenance. That is the gate working. Supply attribution — via the recorded model
file, or `--model`/`--model-id` — and it clears, which is the first row.

The negative control matters. A validator that has never gone red is a light, not
a gate — the H10 rule from `obc-remediation-pack`, applied here to itself.

## The size ceiling is derived, not asserted

`check_reader.py` measures code bytes and bytes-per-second of embedded audio,
then solves against the observed mobile load limit. On the current build:

```
code 54,168 B + 5,347 B/s audio, 2.31 words/s
-> 2,000,000 B ceiling reached at 6.1 min / ~841 words
```

Re-derive per build rather than trusting this number; a bitrate or template
change moves it.

## `schema_version` — migration complete

`build_karaoke.py` emits `"schema_version": "1.0"` in every manifest it writes.
The addition was backward compatible, since existing readers ignore unknown keys.

That closes the `W-NO-VERSION` warning above at the source, so `--require-version`
is now safe to run as a hard gate rather than an aspiration — it is enabled in the
CI invocation under **Use**. A manifest that still trips it is one produced before
this version, not a conformant build.
