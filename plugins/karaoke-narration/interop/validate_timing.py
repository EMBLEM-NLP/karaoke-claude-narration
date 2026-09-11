#!/usr/bin/env python3
"""
validate_timing.py - conformance validator for karaoke timing manifests.

WHY THIS EXISTS
The published schema reference (references/word-timing-schema.md) documents two
keys - `words` and `duration`. The builder emits eight: attribution, blocks,
duration, qc, sentences, source_text, turns, words. Six of those are an
undocumented, unversioned contract that a second reader, or narrated-video-deck,
has to reverse-engineer from a sample file. This validator is the contract in
executable form.

DEPENDENCY-FREE ON PURPOSE. An interop tool that only runs where `jsonschema` is
installed is not an interop tool. Everything here is stdlib. `timing_schema.json`
sits beside this file for consumers who do want a standard JSON Schema.

VERSIONING. A manifest with no `schema_version` is treated as 1.0 and reported as
UNVERSIONED - not an error yet, because every manifest built so far lacks it, but
it is the thing to fix. --require-version turns it into a failure for CI.

Exit codes:  0 = conformant,  1 = non-conformant,  2 = could not read input.
"""
import argparse
import json
import sys

CURRENT = "1.0"
MIN_WORD_DUR = 0.08          # build_karaoke.py's align_words() floor
TOL = 0.051                  # rounding slack: manifests round to 3dp, ffmpeg to ~50ms

REQUIRED_TOP = {"words": list, "duration": (int, float)}
OPTIONAL_TOP = {
    "sentences": list, "blocks": list, "turns": list,
    "source_text": str, "attribution": dict, "qc": dict,
    "schema_version": str,
}


class Report:
    def __init__(self):
        self.errors, self.warnings, self.info = [], [], []

    def err(self, code, msg):
        self.errors.append({"code": code, "message": msg})

    def warn(self, code, msg):
        self.warnings.append({"code": code, "message": msg})

    def note(self, k, v):
        self.info.append({"key": k, "value": v})

    @property
    def ok(self):
        return not self.errors


def check_top_level(m, r):
    for k, t in REQUIRED_TOP.items():
        if k not in m:
            r.err("E-MISSING-KEY", f"required key `{k}` absent")
        elif not isinstance(m[k], t):
            r.err("E-TYPE", f"`{k}` should be {t}, got {type(m[k]).__name__}")
    for k, t in OPTIONAL_TOP.items():
        if k in m and not isinstance(m[k], t):
            r.err("E-TYPE", f"`{k}` should be {t.__name__}, got {type(m[k]).__name__}")
    unknown = set(m) - set(REQUIRED_TOP) - set(OPTIONAL_TOP)
    if unknown:
        r.warn("W-UNKNOWN-KEY",
               f"undocumented top-level key(s): {sorted(unknown)}. "
               f"A consumer cannot know whether these are load-bearing.")


def check_version(m, r, require):
    v = m.get("schema_version")
    if v is None:
        msg = ("no `schema_version`. A consumer has no way to detect a breaking "
               f"change; assuming {CURRENT}.")
        (r.err if require else r.warn)("E-NO-VERSION" if require else "W-NO-VERSION", msg)
        return CURRENT
    r.note("schema_version", v)
    if v.split(".")[0] != CURRENT.split(".")[0]:
        r.err("E-VERSION-MAJOR",
              f"major version {v} is not readable by this validator ({CURRENT})")
    return v


def check_words(m, r):
    words = m.get("words") or []
    dur = m.get("duration") or 0.0
    if not words:
        r.err("E-NO-WORDS", "`words` is empty; there is nothing to highlight")
        return
    prev_end = -1.0
    zero, short, overlap, outside = 0, 0, 0, 0
    for i, w in enumerate(words):
        if not isinstance(w, dict) or not {"w", "start", "end"} <= set(w):
            r.err("E-WORD-SHAPE", f"word[{i}] must be an object with w/start/end")
            return
        s, e = float(w["start"]), float(w["end"])
        if e < s:
            r.err("E-WORD-REVERSED", f"word[{i}] {w['w']!r} ends before it starts")
        if e == s:
            zero += 1
        elif e - s < MIN_WORD_DUR - 1e-9:
            short += 1
        if s < prev_end - 1e-9:
            overlap += 1
        if s < -1e-9 or e > dur + TOL:
            outside += 1
        prev_end = max(prev_end, e)
    if zero:
        r.err("E-ZERO-WIDTH", f"{zero} zero-width word(s); each is an untappable target")
    if short:
        r.warn("W-BELOW-FLOOR", f"{short} word(s) under the {MIN_WORD_DUR}s floor")
    if overlap:
        r.err("E-OVERLAP", f"{overlap} word(s) start before the previous one ends")
    if outside:
        r.err("E-OUT-OF-RANGE", f"{outside} word(s) fall outside [0, duration]")
    r.note("words", len(words))
    r.note("duration_s", round(float(dur), 3))


def check_sentences(m, r):
    sents = m.get("sentences")
    if sents is None:
        r.warn("W-NO-SENTENCES", "no `sentences`; sentence-level seek is unavailable")
        return
    total = 0
    for i, s in enumerate(sents):
        if not isinstance(s, dict):
            r.err("E-SENT-SHAPE", f"sentences[{i}] is not an object")
            return
        if "words" not in s:
            r.err("E-SENT-SHAPE", f"sentences[{i}] has no `words`")
            continue
        n = s["words"] if isinstance(s["words"], int) else len(s["words"])
        total += n
        if "start" in s and "end" in s and s["end"] < s["start"]:
            r.err("E-SENT-REVERSED", f"sentences[{i}] ends before it starts")
        mr = s.get("match_rate")
        if isinstance(mr, (int, float)) and mr < 0.6:
            r.warn("W-LOW-MATCH",
                   f"sentences[{i}] aligned at {mr:.0%}; likely fell back to "
                   f"proportional timing")
    n_words = len(m.get("words") or [])
    if total and total != n_words:
        r.err("E-WORD-COUNT-MISMATCH",
              f"sentences account for {total} words, `words` has {n_words}")
    r.note("sentences", len(sents))


def check_blocks_and_turns(m, r):
    blocks = m.get("blocks") or []
    if blocks:
        narrated = sum(1 for b in blocks if b.get("narrated"))
        r.note("blocks", f"{len(blocks)} ({len(blocks) - narrated} not narrated)")
        for i, b in enumerate(blocks):
            if "type" not in b:
                r.warn("W-BLOCK-SHAPE", f"blocks[{i}] has no `type`")
    turns = m.get("turns") or []
    if not turns:
        r.warn("W-NO-TURNS", "no `turns`; a multi-turn reader cannot segment this")
        return
    dur = float(m.get("duration") or 0)
    for i, t in enumerate(turns):
        if t.get("end", 0) > dur + TOL:
            r.err("E-TURN-RANGE", f"turns[{i}] ends after the audio does")
    r.note("turns", [t.get("label") for t in turns])


def check_attribution(m, r):
    a = m.get("attribution")
    if not a:
        r.warn("W-NO-ATTRIBUTION", "no attribution block; provenance is unrecorded")
        return
    if a.get("model") and not a.get("model_id"):
        r.warn("W-PARTIAL-ATTRIBUTION", "`model` set without `model_id`")
    if a.get("mode"):
        r.warn("W-MODE-PRESENT",
               f"`mode` is {a['mode']!r}. SKILL.md states mode is never "
               f"self-knowable - it must be supplied exactly or left blank.")
    tok = (a.get("tokens") or {}).get("output") or {}
    if tok and not tok.get("exact"):
        r.note("tokens_out", f"{tok.get('count')} (estimate, {tok.get('tokenizer')})")


def check_qc(m, r):
    qc = m.get("qc")
    if not qc:
        r.warn("W-NO-QC", "no qc block; this manifest carries no self-report")
        return
    checks = qc.get("checks") or {}
    failed = [k for k, v in checks.items() if v is False]
    if failed:
        r.err("E-QC-FAILED", f"the manifest reports its own failures: {failed}")
    if qc.get("passed") is not True:
        r.err("E-QC-NOT-PASSED", "qc.passed is not true")
    if "source_matches_ground_truth" not in checks:
        r.warn("W-NO-GROUND-TRUTH",
               "source was never compared to a ground truth; verbatim-ness is "
               "unproven, only internal consistency is")


def main():
    ap = argparse.ArgumentParser(description="Validate a karaoke timing manifest")
    ap.add_argument("manifest")
    ap.add_argument("--require-version", action="store_true",
                    help="fail when schema_version is absent (use in CI)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    a = ap.parse_args()

    try:
        m = json.load(open(a.manifest, encoding="utf-8"))
    except Exception as e:
        print(f"[validate_timing] cannot read {a.manifest}: {e}", file=sys.stderr)
        return 2

    r = Report()
    check_top_level(m, r)
    check_version(m, r, a.require_version)
    check_words(m, r)
    check_sentences(m, r)
    check_blocks_and_turns(m, r)
    check_attribution(m, r)
    check_qc(m, r)

    ok = r.ok and (not a.strict or not r.warnings)

    if a.json:
        print(json.dumps({"conformant": ok, "errors": r.errors,
                          "warnings": r.warnings, "info": r.info}, indent=2))
    else:
        print(f"=== timing manifest conformance: {a.manifest} ===")
        for i in r.info:
            print(f"  {i['key']:16} {i['value']}")
        print()
        for e in r.errors:
            print(f"  FAIL  {e['code']:22} {e['message']}")
        for w in r.warnings:
            print(f"  WARN  {w['code']:22} {w['message']}")
        if not r.errors and not r.warnings:
            print("  no findings")
        print(f"\n  RESULT: {'PASS' if ok else 'FAIL'} "
              f"({len(r.errors)} error(s), {len(r.warnings)} warning(s))")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
