#!/usr/bin/env python3
"""
audit_published.py - did the published artifact actually contain what was said?

WHY THIS EXISTS
Every other gate in this package checks the build against its own inputs.
`display_text_is_verbatim` proves the player renders what the source file said.
`source_matches_ground_truth` proves the narrated files match the ground truth
built from those same files. Neither can catch the failure that produced this
script: a QA fixture was narrated and published in place of the real reply, and
every gate passed, because the fixture matched itself perfectly.

Nothing inside the turn can catch that - the reply does not exist as data until
the turn ends. But one turn later it does: the Stop hook writes
`last_assistant_message`, the runtime's own record of what was really said, to
STATE_DIR/turns/<session>-<ts>/turn.md. Comparing the published text against
that record turns "trust the discipline" into a check that can go red.

RUN IT AT THE START OF THE NEXT TURN, on the previous turn's directory:
    python3 scripts/audit_published.py turns/007

WHY NOT A BYTE DIFF
Code fences are rendered but never narrated (parse_blocks marks them
narrated=False), so the narrated text legitimately differs from the raw reply
whenever the reply contains a fence. A raw comparison false-fails on those - the
exact bug found and fixed in 1.28.0 for --verify-against. This reuses
build_karaoke.py's own comparison instead of restating it: parse_blocks ->
narrated blocks only -> _strip_inline -> SequenceMatcher at the same 0.995
threshold. One comparison, one place, no drifting copy.

EXIT CODES - tri-state, deliberately
  0  published text matches what was actually said
  1  real divergence; the differing spans are printed
  2  could not check - no Stop-hook record to compare against (hook disabled, or
     the reply was under KARAOKE_MIN_CHARS so the hook skipped it)
Exit 2 is NOT a pass. Collapsing "nothing was compared" into "it matched" is the
vacuous-PASS mistake this package fixed for source_matches_ground_truth in
1.25.0 and repeated for check_reader_live.py until 2.1.0. It is not repeated here.
"""
import argparse
import difflib
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = ROOT / "skills" / "karaoke-narration" / "scripts" / "build_karaoke.py"
STATE_DIR = Path(os.environ.get("KARAOKE_STATE_DIR", Path.home() / ".karaoke-narration"))

# Same threshold build_karaoke.py uses for source_matches_ground_truth, so a
# divergence this reports and one the build gate reports mean the same thing.
THRESHOLD = 0.995


def load_build_module():
    spec = importlib.util.spec_from_file_location("bk", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def narrated_words(bk, text):
    """The words the pipeline would actually speak, normalised the same way
    build_karaoke.py normalises them. Quotes are excluded here for the same
    reason they are there: they are the step log, not the reply's prose."""
    blocks = bk.parse_blocks(text)
    joined = "\n".join(b["raw"] for b in blocks
                       if b.get("narrated") and b.get("type") != "quote")
    return bk._strip_inline(joined).split()


def find_stop_hook_record(after_mtime):
    """Newest Stop-hook turn.md written after the published turn was built.

    The Stop hook names its directory <session_id[:12]>-<unix_ts>, which does not
    encode which inline turn it corresponds to. Time ordering is what relates
    them: the hook fires when the turn this audit is about ended, so its record
    is the newest one written after that turn's directory was created.
    """
    turns = STATE_DIR / "turns"
    if not turns.is_dir():
        return None
    candidates = []
    for d in turns.iterdir():
        tm = d / "turn.md"
        if d.is_dir() and tm.is_file() and tm.stat().st_mtime >= after_mtime:
            candidates.append((tm.stat().st_mtime, tm))
    if not candidates:
        return None
    return max(candidates)[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("turn_dir", help="the turn directory that was published "
                                     "(the one narrate_response.sh wrote)")
    ap.add_argument("--against", default=None,
                    help="compare against this file instead of auto-locating "
                         "the Stop hook's record (for testing)")
    args = ap.parse_args()

    turn_dir = Path(args.turn_dir)
    published = turn_dir / "ground_truth.md"
    if not published.is_file():
        print(f"audit: COULD NOT CHECK - no {published} "
              f"(was this turn built by narrate_response.sh?)", file=sys.stderr)
        return 2

    if args.against:
        record = Path(args.against)
        if not record.is_file():
            print(f"audit: COULD NOT CHECK - no such file: {record}", file=sys.stderr)
            return 2
    else:
        record = find_stop_hook_record(published.stat().st_mtime)
        if record is None:
            print("audit: COULD NOT CHECK - no Stop-hook record found under "
                  f"{STATE_DIR / 'turns'} newer than this turn's build.",
                  file=sys.stderr)
            print("  The hook may be disabled (/karaoke status), or the reply may "
                  "have been under KARAOKE_MIN_CHARS and skipped.", file=sys.stderr)
            print("  This is NOT a pass - nothing was compared.", file=sys.stderr)
            return 2

    bk = load_build_module()
    said = narrated_words(bk, record.read_text(encoding="utf-8", errors="replace"))
    shipped = narrated_words(bk, published.read_text(encoding="utf-8", errors="replace"))

    if not said:
        print(f"audit: COULD NOT CHECK - the Stop-hook record {record} has no "
              "narrated words to compare.", file=sys.stderr)
        return 2

    sm = difflib.SequenceMatcher(None, said, shipped, autojunk=False)
    ratio = sm.ratio()

    if ratio >= THRESHOLD:
        print(f"audit: PASS - published text matches what was said "
              f"(similarity {ratio:.4f})")
        print(f"  published : {published}")
        print(f"  said      : {record}")
        return 0

    print(f"audit: FAIL - published text is NOT what was said "
          f"(similarity {ratio:.4f}, threshold {THRESHOLD})", file=sys.stderr)
    print(f"  published : {published}", file=sys.stderr)
    print(f"  said      : {record}", file=sys.stderr)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        print(f"    {tag}: said={said[i1:i2][:8]} published={shipped[j1:j2][:8]}",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
