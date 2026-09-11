#!/usr/bin/env python3
"""
check_reader.py - interoperability audit of a packed standalone karaoke reader.

WHAT IT ANSWERS
  1. Will this file work with no network?          (external dependency scan)
  2. Will it work in the claude.ai artifact sandbox? (storage + media-src rules)
  3. Will it work on iOS Safari?                    (AudioContext gesture handling)
  4. How much longer can a turn get before it stops loading on mobile?

WHY A SEPARATE TOOL
The reader is shipped as one ~1MB file that is ~90% base64. Grepping it naively
produces false positives - "blob:" and "<audio" occur inside base64 by chance.
Every scan here strips payload blobs first, so a finding is a finding.

The size ceiling is derived, not asserted: measured code bytes plus measured
bytes-per-second of audio, solved against the observed mobile load limit
(references/artifact-size-constraints.md: ~2MB loaded, ~5.7MB did not).

Exit codes:  0 = interoperable,  1 = findings,  2 = could not read input.
"""
import argparse
import json
import os
import re
import sys

PAYLOAD = re.compile(r"[A-Za-z0-9+/=]{2000,}")
DEFAULT_CEILING = 2_000_000        # bytes; empirical, not a documented limit

# (label, pattern, severity, why it matters)
EXTERNAL = [
    ("script src",   r"<script[^>]+src\s*=",              "FAIL", "needs the network to run"),
    ("stylesheet",   r"<link[^>]+rel=[\"']?stylesheet",   "FAIL", "needs the network to style"),
    ("absolute url", r"[\"'](?:https?:)?//[a-z0-9.-]+\.", "FAIL", "remote resource"),
    ("fetch()",      r"\bfetch\s*\(",                      "FAIL", "sandbox iframe cannot fetch siblings"),
    ("XHR",          r"\bXMLHttpRequest\b",                "FAIL", "same"),
    ("worker",       r"new\s+Worker\s*\(",                 "WARN", "worker scripts are a second file"),
    ("@import",      r"@import\b",                         "FAIL", "remote or sibling stylesheet"),
]
STORAGE = [
    ("localStorage",   r"\blocalStorage\b"),
    ("sessionStorage", r"\bsessionStorage\b"),
    ("indexedDB",      r"\bindexedDB\b"),
    ("serviceWorker",  r"navigator\.serviceWorker"),
]
MEDIA_BAD = [
    ("blob: URL",  r"blob:",                 "media-src blocks blob: in the artifact sandbox"),
    ("createObjectURL", r"URL\.createObjectURL", "produces a blob: URL"),
    ("<audio> element", r"<audio\b",         "an element sourced by URL is governed by media-src"),
    ("data:audio", r"data:audio",            "media-src blocks data: too"),
]
MEDIA_GOOD = [
    ("decodeAudioData",   r"decodeAudioData"),
    ("createBufferSource", r"createBufferSource"),
]
IOS = [
    ("webkitAudioContext", r"webkitAudioContext"),
    ("ctx.resume()",       r"\.resume\s*\(\s*\)"),
]


def strip_payload(html):
    return PAYLOAD.sub("<<PAYLOAD>>", html)


def scan(code, table):
    out = []
    for row in table:
        label, pat = row[0], row[1]
        n = len(re.findall(pat, code, re.I))
        out.append((label, n, row[2] if len(row) > 2 else None,
                    row[3] if len(row) > 3 else None))
    return out


def main():
    ap = argparse.ArgumentParser(description="Audit a standalone karaoke reader for interop")
    ap.add_argument("html")
    ap.add_argument("--timing", help="matching timing.json, for the word-ceiling estimate")
    ap.add_argument("--ceiling", type=int, default=DEFAULT_CEILING,
                    help=f"mobile load ceiling in bytes (default {DEFAULT_CEILING})")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    try:
        raw = open(a.html, encoding="utf-8", errors="replace").read()
    except Exception as e:
        print(f"[check_reader] cannot read {a.html}: {e}", file=sys.stderr)
        return 2

    total = os.path.getsize(a.html)
    code = strip_payload(raw)
    code_bytes = len(code.encode("utf-8", "replace"))
    payload_bytes = total - code_bytes
    findings, notes = [], []

    for label, n, sev, why in scan(code, EXTERNAL):
        if n:
            findings.append((sev, "EXTERNAL", f"{label} x{n} - {why}"))
    for label, n, _, _ in scan(code, [(l, p, None, None) for l, p in STORAGE]):
        if n:
            findings.append(("FAIL", "STORAGE",
                             f"{label} x{n} - unsupported in claude.ai artifacts"))
    for label, n, why, _ in scan(code, [(l, p, w, None) for l, p, w in MEDIA_BAD]):
        if n:
            findings.append(("WARN", "MEDIA",
                             f"{label} x{n} - {why}; dead code or a surface-dependent path"))
    good = {l: n for l, n, _, _ in scan(code, [(l, p, None, None) for l, p in MEDIA_GOOD])}
    if not good.get("decodeAudioData"):
        findings.append(("FAIL", "MEDIA",
                         "no decodeAudioData - the only route that bypasses media-src"))
    ios = {l: n for l, n, _, _ in scan(code, [(l, p, None, None) for l, p in IOS])}
    for label, n in ios.items():
        if not n:
            findings.append(("WARN", "IOS", f"{label} absent - iOS playback may not start"))

    # --- size ceiling ---------------------------------------------------------
    dur = words = None
    if a.timing and os.path.exists(a.timing):
        try:
            t = json.load(open(a.timing, encoding="utf-8"))
            dur, words = float(t.get("duration") or 0), len(t.get("words") or [])
        except Exception:
            pass
    notes.append(("total bytes", f"{total:,}"))
    notes.append(("code / payload", f"{code_bytes:,} / {payload_bytes:,} "
                                    f"({payload_bytes * 100 // max(total, 1)}% payload)"))
    notes.append(("headroom", f"{a.ceiling - total:+,} bytes vs {a.ceiling:,} ceiling"))
    if total > a.ceiling:
        findings.append(("FAIL", "SIZE",
                         f"{total:,} bytes exceeds the {a.ceiling:,} observed load ceiling"))
    if dur and words and dur > 0:
        bps = payload_bytes / dur                      # embedded bytes per audio second
        wps = words / dur
        max_dur = max((a.ceiling - code_bytes) / bps, 0)
        notes.append(("measured rate", f"{bps:,.0f} B/s audio, {wps:.2f} words/s"))
        notes.append(("ceiling reached at",
                      f"{max_dur / 60:.1f} min / ~{int(max_dur * wps):,} words"))
        if words > int(max_dur * wps) * 0.8:
            findings.append(("WARN", "SIZE",
                             f"this turn is within 20% of the estimated word ceiling"))

    if a.json:
        print(json.dumps({
            "interoperable": not any(f[0] == "FAIL" for f in findings),
            "findings": [{"severity": s, "area": ar, "message": m} for s, ar, m in findings],
            "notes": dict(notes)}, indent=2))
    else:
        print(f"=== reader interop audit: {a.html} ===")
        for k, v in notes:
            print(f"  {k:20} {v}")
        print()
        if not findings:
            print("  no findings - self-contained, sandbox-safe, iOS-safe")
        for sev, area, msg in sorted(findings, key=lambda f: f[0]):
            print(f"  {sev:5} {area:9} {msg}")
        fails = sum(1 for f in findings if f[0] == "FAIL")
        print(f"\n  RESULT: {'PASS' if not fails else 'FAIL'} "
              f"({fails} blocking, {len(findings) - fails} advisory)")
    return 1 if any(f[0] == "FAIL" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
