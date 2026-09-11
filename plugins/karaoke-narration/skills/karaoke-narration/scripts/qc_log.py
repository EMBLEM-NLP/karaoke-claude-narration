#!/usr/bin/env python3
"""
qc_log.py - across-build drift detection for karaoke-narration.

WHAT THIS ADDS THAT THE QC GATE DOES NOT
build_karaoke.py's QC gate is a WITHIN-build check: it asserts this run's
numbers against fixed thresholds. It cannot see that avg_word_match has been
sliding for six builds while never once crossing a threshold, or that loudness
drifted after a codec change. That is an ACROSS-build question and needs
history, which nothing was keeping.

TWO DESIGN CONSTRAINTS, both learned the hard way in this project:

1. SPLIT BY DETERMINISM. references/whisper-tts-reliability.md documents the
   ASR stage as non-deterministic even after the int8 -> float32 fix: "one
   sentence showed 0.38 vs 0.75 between two float32 runs". So ASR-derived
   metrics need wide bands, while ffmpeg-derived ones (loudness, true peak,
   distortion) are deterministic and any real movement in them is signal.
   Applying one threshold to both would either drown in ASR noise or miss real
   audio-chain regressions. Same split the test harness uses.

2. ROBUST STATISTICS, NOT MEAN AND STDEV. Build counts here are small and
   outliers are expected (the exact thing we are hunting). One bad build would
   inflate stdev enough to hide the next three. Median and median-absolute-
   deviation do not have that failure mode. Threshold is the modified z-score
   of Iglewicz & Hoaglin, |z| > 3.5.

3. REFUSE TO REPORT ON A THIN BASELINE. With three builds, "drift" is a
   coin flip dressed up as a number. Below MIN_BASELINE this prints
   INSUFFICIENT BASELINE and exits 0. Saying nothing is correct; saying
   something confident would repeat the vacuous-PASS mistake this project
   already made once.

STRUCTURAL metrics (words, sentences, blocks) are logged as CONTEXT and never
alerted on: they vary with whatever text was fed in, so movement there is input
variation, not pipeline drift. Recording them makes a real alert interpretable
- a match-rate dip on a build that was 4x longer than baseline means something
different than one on a comparable build.

Usage:
  qc_log.py --append <timing.json> [--label TEXT]   record a build
  qc_log.py --report                                compare latest vs baseline
  qc_log.py --report --all                          full history table
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.environ.get("KARAOKE_STATE_DIR", Path.home() / ".karaoke-narration"))
HISTORY = STATE / "qc_history.jsonl"

MIN_BASELINE = 5          # builds required before drift is reported at all
MOD_Z_LIMIT = 3.5         # Iglewicz & Hoaglin outlier threshold

# metric -> (kind, human label, higher_is_better or None if two-sided)
METRICS = {
    "avg_word_match_rate":  ("asr",        "avg word match",    True),
    "low_confidence_count": ("asr",        "low-conf sentences", False),
    "resplit_sentences":    ("asr",        "re-split sentences", False),
    "loudness_lufs":        ("audio",      "loudness LUFS",     None),
    "true_peak_dbtp":       ("audio",      "true peak dBTP",    None),
    "distortion_pct_mp3":   ("audio",      "distortion %",      False),
    "words":                ("structural", "words",             None),
    "sentences":            ("structural", "sentences",         None),
    "duration":             ("structural", "duration s",        None),
}


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mad(xs, med):
    """Median absolute deviation, scaled to be a consistent estimator of sigma."""
    if not xs:
        return None
    return median([abs(x - med) for x in xs])


def modified_z(x, med, m):
    """Iglewicz & Hoaglin modified z-score. Returns None when MAD is zero,
    which is common and meaningful for deterministic metrics: it means every
    prior build agreed exactly, so ANY deviation is worth surfacing."""
    if m is None or m == 0:
        return None
    return 0.6745 * (x - med) / m


def extract(timing_path):
    d = json.loads(Path(timing_path).read_text())
    q = d.get("qc", {})
    lc = q.get("low_confidence_sentences")
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "avg_word_match_rate": q.get("avg_word_match_rate"),
        "low_confidence_count": len(lc) if isinstance(lc, list) else (lc or 0),
        "resplit_sentences": q.get("resplit_sentences"),
        "loudness_lufs": q.get("loudness_lufs"),
        "true_peak_dbtp": q.get("true_peak_dbtp"),
        "distortion_pct_mp3": q.get("distortion_pct_mp3"),
        "words": q.get("words"),
        "sentences": q.get("sentences"),
        "duration": d.get("duration"),
        # Tri-state from the fail-closed fix: None means no ground truth was
        # supplied. Logged so a run of unverified builds is visible as a
        # pattern rather than being invisible one build at a time.
        "ground_truth_checked": q.get("checks", {}).get("source_matches_ground_truth"),
    }


def load():
    if not HISTORY.exists():
        return []
    out = []
    for line in HISTORY.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def cmd_append(args):
    rec = extract(args.append)
    if args.label:
        rec["label"] = args.label
    STATE.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[qc_log] recorded build -> {HISTORY} (history now {len(load())} builds)")
    return 0


def cmd_report(args):
    hist = load()
    if not hist:
        print("[qc_log] no history yet. Record builds with --append <timing.json>.")
        return 0

    if args.all:
        print(f"\n=== QC HISTORY ({len(hist)} builds) ===")
        hdr = f"  {'when':<20} {'words':>6} {'match':>7} {'LUFS':>7} {'peak':>7} {'GT':>4}"
        print(hdr)
        for r in hist:
            gt = {True: "yes", False: "FAIL", None: "--"}.get(r.get("ground_truth_checked"), "?")
            print(f"  {r['ts'][:19]:<20} {r.get('words') or 0:>6} "
                  f"{(r.get('avg_word_match_rate') or 0):>7.3f} "
                  f"{(r.get('loudness_lufs') or 0):>7.1f} "
                  f"{(r.get('true_peak_dbtp') or 0):>7.1f} {gt:>4}")

    latest, baseline = hist[-1], hist[:-1]
    print(f"\n=== DRIFT: latest build vs {len(baseline)} prior ===")

    if len(baseline) < MIN_BASELINE:
        print(f"  INSUFFICIENT BASELINE - {len(baseline)} prior builds, need {MIN_BASELINE}.")
        print("  Reporting drift from this little history would be noise presented as")
        print("  a finding. Nothing is claimed. Keep recording builds.")
        # Still surface the one thing that needs no baseline at all.
        unverified = sum(1 for r in hist if r.get("ground_truth_checked") is None)
        if unverified:
            print(f"\n  Note (needs no baseline): {unverified} of {len(hist)} builds ran with")
            print("  NO ground truth supplied. That is not a failure, but a long run of")
            print("  them means verbatim fidelity is unverified, not verified.")
        return 0

    alerts = []
    for key, (kind, label, higher_better) in METRICS.items():
        vals = [r.get(key) for r in baseline if isinstance(r.get(key), (int, float))]
        cur = latest.get(key)
        if not vals or not isinstance(cur, (int, float)):
            continue
        med = median(vals)
        m = mad(vals, med)
        z = modified_z(cur, med, m)
        flag = ""
        if kind == "structural":
            flag = "context"
        elif z is None:
            # Zero MAD: every prior build identical. Deterministic metrics land
            # here routinely (distortion 0.00 every time), so exact-match is the
            # expectation and any movement is real.
            flag = "DRIFT" if cur != med else "stable"
        elif abs(z) > MOD_Z_LIMIT:
            flag = "DRIFT"
        else:
            flag = "stable"

        line = (f"  {flag:<8} {label:<20} now {cur:>8.3f}   baseline median {med:>8.3f}"
                + (f"   modified-z {z:>6.2f}" if z is not None else "   (zero MAD)"))
        print(line)
        if flag == "DRIFT" and kind != "structural":
            direction = "worse" if (higher_better is True and cur < med) or \
                                   (higher_better is False and cur > med) else "changed"
            alerts.append(f"{label} {direction}: {cur:.3f} vs median {med:.3f}")

    print()
    if alerts:
        print("  ALERTS:")
        for a in alerts:
            print(f"    - {a}")
        print("\n  An ASR-metric alert is worth a manual listen before it is worth a")
        print("  code change - that stage is documented as non-deterministic. An")
        print("  audio-metric alert (loudness, peak, distortion) is deterministic and")
        print("  almost always a real change in the encode chain.")
        return 1
    print("  No drift beyond noise.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--append", metavar="TIMING_JSON")
    ap.add_argument("--label", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.append:
        return cmd_append(a)
    if a.report:
        return cmd_report(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
