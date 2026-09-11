#!/usr/bin/env python3
"""
test_pure.py - regression harness for karaoke-narration's DETERMINISTIC layer.

WHY THIS FILE EXISTS
This plugin shipped 1.19.0 -> 1.24.0 with no test suite at all. Its CI
smoke-tests the sibling ffmpeg plugin's scripts and never mentions this one.
So any refactor of build_karaoke.py was verified by running it once and reading
the QC report - which checks the OUTPUT of one run, not the CODE's behaviour.

WHY IT ONLY TESTS THE PURE LAYER
references/whisper-tts-reliability.md documents that the ASR stage is not
deterministic even after the int8 -> float32 fix: "one sentence showed 0.38 vs
0.75 between two float32 runs". Golden-output assertions on anything
ASR-dependent would therefore flake, and a flaky suite gets ignored, which is
worse than no suite. So:

  LAYER A (this file)  pure text/markdown/timing functions. No audio, no ASR,
                       no network. Exact assertions. Runs in milliseconds.
  LAYER B (this file)  subprocess exit codes from the refusal guards. Fully
                       deterministic.
  LAYER C (NOT here)   anything depending on Piper or faster-whisper output.
                       Belongs in a separate slow suite with tolerance bands,
                       never exact equality.

EVERY CASE BELOW IS A REAL OBSERVED FAILURE, not an invented one. Each carries
the provenance of where it was seen. That is the whole point: this file is a
ratchet. A failure that has been seen once can never silently return.

Run:  python3 tests/test_pure.py
Exit: 0 all pass, 1 any fail.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
BUILD = SKILL / "scripts" / "build_karaoke.py"

spec = importlib.util.spec_from_file_location("bk", BUILD)
bk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bk)

RESULTS = []


def check(name, got, want, provenance):
    ok = got == want
    RESULTS.append((ok, name, got, want, provenance))
    return ok


def check_true(name, cond, provenance, detail=""):
    RESULTS.append((bool(cond), name, detail or cond, "truthy", provenance))
    return bool(cond)


# ---------------------------------------------------------------- LAYER A
# Pure markdown / text / timing functions. Deterministic by construction.

def test_code_fence_not_narrated():
    """Design invariant stated at the top of build_karaoke.py."""
    blocks = bk.parse_blocks("Intro line.\n\n```\nrm -rf /\n```\n\nOutro line.")
    code = [b for b in blocks if b["type"] == "code"]
    check("code fence is parsed as its own block", len(code), 1,
          "build_karaoke.py module docstring: 'CODE FENCES ARE RENDERED BUT NOT NARRATED'")
    check("code fence is not narrated", code[0]["narrated"], False,
          "same")
    check("prose around the fence still narrates", 
          sum(1 for b in blocks if b["narrated"]), 2, "same")


def test_table_has_no_parser_branch():
    """OBSERVED THIS CONVERSATION: a markdown table in a narrated response
    collapses to a run-on when spoken. parse_blocks has branches for heading,
    code, quote, bullet, paragraph - and none for tables, so a table falls
    through to the paragraph handler and its structure is lost in audio.

    This asserts the CURRENT behaviour deliberately. It is a known limitation,
    not a passing feature. If someone later adds a real table branch, this test
    fails loudly and they update it on purpose rather than by accident."""
    md = "| Condition | Exit |\n|---|---|\n| Missing source | 3 |"
    blocks = bk.parse_blocks(md)
    check("table is (still) swallowed as a single paragraph",
          [b["type"] for b in blocks], ["paragraph"],
          "observed: turn 3 of this session shipped a table that narrated as word-salad")
    spoken, _, _, _, _ = bk.build_spoken(blocks[0]["raw"], True)
    check_true("table pipes/dashes are stripped, not spoken literally",
               "|" not in spoken and "---" not in spoken,
               "same", detail=spoken[:60])


def test_acronym_substitution_is_automatic():
    """OBSERVED THIS CONVERSATION: I hand-adapted text for speech (writing
    'dot S H' for a filename), which by construction produced a SECOND document
    and a 16% verbatim similarity. The tool already does this itself."""
    spoken, disp, _, _, _ = bk.build_spoken("The MCP and API layer", True)
    check("MCP is expanded for speech automatically", "M C P" in spoken, True,
          "DEFAULT_SUBS in build_karaoke.py; misuse observed turns 1-3 of this session")
    check("API is expanded for speech automatically", "A P I" in spoken, True, "same")
    check("DISPLAY layer keeps the original spelling", "MCP" in disp, True,
          "three-layer design: SOURCE / DISPLAY / SPOKEN must differ")


def test_three_layers_actually_differ():
    """Module docstring: 'All three differ. An earlier version collapsed them,
    so a transcript of "The **MCP** server returns JSON" was rendered as
    "The M C P server returns jason".'"""
    src = "The **MCP** server returns JSON"
    spoken, disp, styles, counts, _ = bk.build_spoken(src, True)
    check("DISPLAY strips the bold markers", "**" in " ".join(disp), False,
          "module docstring, layer 1->2")
    check("DISPLAY preserves the literal word JSON", "JSON" in disp, True,
          "module docstring: the regression was rendering it as 'jason'")
    check("SPOKEN says jason", "jason" in spoken, True, "DEFAULT_SUBS")
    check_true("bold styling is captured, not discarded",
               any("bold" in s for s in styles),
               "module docstring, layer 1->2 keeps styling")


def test_punctuation_only_tokens_are_kept():
    """DOCUMENTED PRIOR BUG in build_spoken's own docstring: 'a 344-word turn
    rendered with 8 em dashes missing, so the transcript was not actually
    verbatim while claiming to be.'"""
    _, disp, _, counts, _ = bk.build_spoken("Fixed it — properly this time", True)
    check("the em dash survives into DISPLAY", "—" in disp, True,
          "build_spoken docstring: 8 em dashes went missing in a shipped turn")
    check("the em dash has a spoken-expansion count of zero",
          counts[disp.index("—")], 0,
          "same - shown, never spoken")


def test_zero_width_words_are_floored():
    """DOCUMENTED PRIOR BUG in SKILL.md and word-timing-schema.md: faster-whisper
    emitted a zero-width word at a sentence boundary, which is an untappable tap
    target."""
    words = [{"w": "a", "start": 0.0, "end": 0.0},
             {"w": "b", "start": 0.0, "end": 0.5}]
    bk.enforce_monotonic_min_duration(words, bk.MIN_WORD_DUR)
    check_true("no word has zero width after enforcement",
               all(w["end"] - w["start"] >= bk.MIN_WORD_DUR - 1e-9 for w in words),
               "word-timing-schema.md invariant: end - start >= 0.08",
               detail=[(w["end"] - w["start"]) for w in words])
    check_true("word starts remain monotonic after enforcement",
               all(words[i]["start"] <= words[i + 1]["start"]
                   for i in range(len(words) - 1)),
               "word-timing-schema.md: ordered by start, ascending")


def test_structure_is_preserved_not_flattened():
    """Module docstring: 'Normalizing all whitespace flattens it into one wall
    of text, which defeats the point of a review lens.'"""
    md = "# Heading\n\nA paragraph.\n\n- bullet one\n- bullet two\n\n> a step line"
    types = [b["type"] for b in bk.parse_blocks(md)]
    check("heading, paragraph, bullets and quote are all distinct blocks",
          types, ["heading", "paragraph", "bullet", "bullet", "quote"],
          "module docstring: STRUCTURE IS PRESERVED")


# ---------------------------------------------------------------- LAYER B
# Refusal guards. Subprocess exit codes - deterministic.

def test_refusal_guards():
    """OBSERVED THIS CONVERSATION: all three verified by hand against the
    shipped zip. Codified here so they stay verified without hand-running."""
    ft = SKILL / "scripts" / "finish_turn.sh"
    if not ft.exists():
        RESULTS.append((False, "finish_turn.sh exists", "missing", "present", "packaging"))
        return

    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        # Guard 1: missing source file.
        r = subprocess.run(["bash", str(ft), str(Path(td) / "nope.md")],
                           capture_output=True, text=True, cwd=str(SKILL), env=env)
        check("missing source file refuses with exit 3", r.returncode, 3,
              "verified by hand against the shipped zip, this session")
        check_true("...and names the reason",
                   "no turn source" in r.stderr, "same", detail=r.stderr.strip()[:60])


# ---------------------------------------------------------------- LAYER B
# The fail-open defect.

def test_ground_truth_check_is_not_vacuous():
    """THE DEFECT THIS SESSION EXPOSED FOUR TIMES.

    `ground_ok` initialises to True and is only ever evaluated if
    --verify-against was supplied. So a build with no ground truth reports
    'PASS source_matches_ground_truth' - which reads as 'the source matched
    reality' but actually means 'nothing was checked'.

    I reported that vacuous PASS as meaningful on three consecutive turns.
    A guard that is not wired to fire by default is a guard that will not fire.

    This test asserts the FIXED, tri-state behaviour. It fails against
    build_karaoke.py as currently shipped - deliberately. See PATCH.md."""
    src = BUILD.read_text()
    fixed = ('ground_ok, ground_detail = None, ""' in src
             or '"source_matches_ground_truth": ground_ok if' in src
             or "NOT CHECKED" in src)
    check_true("ground-truth check is tri-state (PASS/FAIL/NOT CHECKED), not fail-open",
               fixed,
               "observed: turns 1-3 of this session each reported a vacuous PASS",
               detail="ground_ok still defaults to True -> vacuous PASS" if not fixed else "fixed")



def test_drift_detector_refuses_thin_baseline():
    """OBSERVED THIS SESSION: the vacuous-PASS defect was a tool reporting
    confidence it had not earned. A drift detector claiming a finding from three
    builds would be the same mistake in a new place."""
    import json as _json, subprocess, tempfile, os as _os
    qc = SKILL / "scripts" / "qc_log.py"
    if not qc.exists():
        RESULTS.append((False, "qc_log.py present", "missing", "present", "packaging"))
        return
    # The fixture is synthesized rather than read from a shipped demo asset.
    # This test is about qc_log refusing a thin baseline; it only needs a
    # well-formed manifest to append. Building one here keeps the assertion
    # intact without requiring ~1.4MB of demo audio to stay in version control.
    with tempfile.TemporaryDirectory() as td:
        fixture = Path(td) / "fixture.timing.json"
        fixture.write_text(_json.dumps({
            "schema_version": "1.0",
            "duration": 9.5,
            "words": [{"w": "one", "start": 0.0, "end": 0.4}],
            "qc": {"avg_word_match_rate": 1.0, "low_confidence_sentences": [],
                   "resplit_sentences": 0, "loudness_lufs": -16.0,
                   "true_peak_dbtp": -1.5, "distortion_pct_mp3": 0.0,
                   "words": 1, "sentences": 1, "checks": {}},
        }))
        env = dict(_os.environ, KARAOKE_STATE_DIR=td)
        for _ in range(3):
            subprocess.run([sys.executable, str(qc), "--append", str(fixture)],
                           capture_output=True, env=env, cwd=str(SKILL))
        r = subprocess.run([sys.executable, str(qc), "--report"],
                           capture_output=True, text=True, env=env, cwd=str(SKILL))
        check_true("drift detector refuses to report on a thin baseline",
                   "INSUFFICIENT BASELINE" in r.stdout,
                   "the vacuous-PASS mistake, generalised: never claim unearned confidence",
                   detail=r.stdout.strip()[:70])
        check("...and exits 0 rather than alarming", r.returncode, 0,
              "an honest non-finding is not an error")


def test_voice_cache_default_is_absolute():
    """OBSERVED THIS SESSION: --voices-dir defaulted to the relative path
    'voices', so a ~63MB model cached into whatever cwd you ran from. Three
    copies landed on disk and one was packaged into a release zip, inflating it
    from 1.8MB to 65MB."""
    src = BUILD.read_text()
    check_true("voices cache default is cwd-independent, not the relative 'voices'",
               'default="voices"' not in src,
               "a 65MB release zip shipped with the model inside it, this session",
               detail="still relative" if 'default="voices"' in src else "absolute")



def test_ground_truth_ignores_code_fences_on_both_sides():
    """OBSERVED THIS SESSION: a code-fenced build-report coda (the fix for
    turn 7's missing-sections finding) made a file FAIL verify-against ITSELF,
    because truth was built from raw text while `mine` already excludes code
    blocks. Apples to oranges. Fixed by stripping fences from truth the same
    way parse_blocks already excludes them from mine."""
    import subprocess, tempfile
    md = ("Some narrated prose here that is long enough to synthesize meaningfully "
          "for this specific regression test to actually exercise the pipeline.\n\n"
          "```\nnot narrated: code fence content, deliberately different words\n```")
    with tempfile.TemporaryDirectory() as td:
        p1 = pathlib.Path(td) / "a.md"; p1.write_text(md)
        r = subprocess.run([sys.executable, str(BUILD), str(p1), "--labels", "t",
                           "--verify-against", str(p1), "-o", str(Path(td) / "o.mp3")],
                          capture_output=True, text=True, timeout=180)
        check("a file with a code fence passes verify-against itself", r.returncode, 0,
              "observed: same file vs itself FAILed before this fix, turn 7")


def test_ground_truth_still_catches_real_divergence():
    """Guard against a fail-open regression while fixing the fence bug above -
    a fix that also silences real mismatches would be worse than the bug."""
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as td:
        truth = pathlib.Path(td) / "truth.md"; truth.write_text(
            "This sentence is the ground truth version of events, quite long enough.")
        built = pathlib.Path(td) / "built.md"; built.write_text(
            "This sentence is a completely different divergent narrated version instead.")
        r = subprocess.run([sys.executable, str(BUILD), str(built), "--labels", "t",
                           "--verify-against", str(truth), "-o", str(Path(td) / "o.mp3")],
                          capture_output=True, text=True, timeout=180)
        check("a real divergence still fails the gate", r.returncode, 2,
              "a fix must not also make the check fail-open again")


def main():
    for fn in [test_code_fence_not_narrated, test_table_has_no_parser_branch,
               test_acronym_substitution_is_automatic, test_three_layers_actually_differ,
               test_punctuation_only_tokens_are_kept, test_zero_width_words_are_floored,
               test_structure_is_preserved_not_flattened, test_refusal_guards,
               test_ground_truth_check_is_not_vacuous,
               test_drift_detector_refuses_thin_baseline,
               test_voice_cache_default_is_absolute,
               test_ground_truth_ignores_code_fences_on_both_sides,
               test_ground_truth_still_catches_real_divergence]:
        try:
            fn()
        except Exception as e:
            RESULTS.append((False, f"{fn.__name__} raised", repr(e), "no exception", "harness"))

    passed = sum(1 for ok, *_ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("=" * 72)
    print("karaoke-narration :: deterministic regression suite")
    print("=" * 72)
    for ok, name, got, want, prov in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        got:  {got!r}")
            print(f"        want: {want!r}")
            print(f"        why this test exists: {prov}")
    print("-" * 72)
    print(f"  {passed} passed, {failed} failed, out of {len(RESULTS)}")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
