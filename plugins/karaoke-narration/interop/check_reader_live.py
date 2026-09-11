#!/usr/bin/env python3
"""
check_reader_live.py - BEHAVIOURAL interop check for the packed karaoke reader.

WHY A LIVE CHECK EXISTS BESIDE check_reader.py
check_reader.py is a static scan. It passed every file that hung on an iPhone,
because it can only see that `webkitAudioContext` and `.resume()` are PRESENT -
not that decode ran before any gesture, not that the play button was enabled
only inside the decode's success path, not that a `=== 'suspended'` test skips
WebKit's non-standard 'interrupted' state. Presence is not sequencing.

WHY PASSING IN PLAIN CHROMIUM PROVES NOTHING
Every build that hung on an iPhone passed unmodified headless Chromium. Whatever
the true iOS mechanism - and it is NOT established; see the 1.29.1 changelog -
plain Chromium never exercised it. This script patches the Web Audio API to two
hostile behaviours and asserts the page still gives the reader a transcript and
a working play button. They are robustness properties the reader must have under
ANY mechanism; they are not a claim about how WebKit decodes.

THE TWO SIMULATIONS
  hang        decodeAudioData never settles, ever. The page must still render
              the transcript and leave the play button ENABLED - a button that
              only unlocks on decode success is dead the moment anything
              before that point fails, which is what real devices showed.
  interrupted the context reports 'interrupted' (a real, non-standard WebKit
              state) until resume() is called, and decode is held until then.
              Tapping play must lead to a decoded buffer - which requires the
              code to resume on ANY non-running state, not one named state.

NEGATIVE CONTROL - run this against the pre-1.29.0 template and it must FAIL
both simulations. A check that has never gone red is a light, not a gate.

Requires playwright (pip install playwright) and a Chromium binary. The static
check_reader.py deliberately has no such dependency; this file is the optional,
heavier half.

Exit codes:  0 = both simulations pass,  1 = a simulation failed,  2 = could not run.
"""
import argparse
import json
import os
import sys
import tempfile

DEFAULT_CHROMIUM = os.environ.get(
    "KARAOKE_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

WEBKIT_SIM = r"""
(() => {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  const mode = "__MODE__";
  const realDecode = AC.prototype.decodeAudioData;
  let state = (mode === 'interrupted') ? 'interrupted' : 'suspended';
  Object.defineProperty(AC.prototype, 'state', { get(){ return state; }, configurable: true });
  AC.prototype.resume = function(){ state = 'running'; return Promise.resolve(); };
  AC.prototype.decodeAudioData = function(buf, ok, err){
    if (mode === 'hang' || state !== 'running') return new Promise(function(){});  // never settles
    return realDecode.call(this, buf, ok, err);
  };
})();
"""


def wrap_if_fragment(html):
    if "<html" in html.lower():
        return html
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
            '<body>' + html + '</body></html>')


def run(page_path, chromium, timeout_ms):
    from playwright.sync_api import sync_playwright
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium, args=["--no-sandbox"])
        for mode in ("hang", "interrupted"):
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.add_init_script(WEBKIT_SIM.replace("__MODE__", mode))
            pg.goto("file://" + page_path)
            pg.wait_for_timeout(1500)
            boot_status = pg.eval_on_selector("#status", "e => e.textContent")
            transcript_n = pg.evaluate("() => document.querySelector('#transcript').children.length")
            btn_disabled = pg.evaluate("() => document.querySelector('#playBtn').disabled")
            r = {"boot_status": boot_status, "transcript_children": transcript_n,
                 "play_button_disabled": btn_disabled, "errors": errors}
            if mode == "hang":
                r["pass"] = transcript_n > 0 and not btn_disabled and not errors
                r["why"] = ("transcript rendered and play button enabled while decode hangs"
                            if r["pass"] else
                            "reader is stuck: transcript missing or play button disabled behind a decode that never completes")
            else:
                if not btn_disabled:
                    pg.click("#playBtn")
                    pg.wait_for_timeout(timeout_ms)
                decoded = pg.evaluate("() => (typeof audioBuffer !== 'undefined') && audioBuffer !== null")
                status = pg.eval_on_selector("#status", "e => e.textContent")
                r.update({"decoded_after_tap": decoded, "status_after_tap": status})
                blocked = "blocked" in status.lower() or "could not" in status.lower()
                r["pass"] = decoded and not blocked and not errors
                r["why"] = ("tap resumed an 'interrupted' context and decode completed"
                            if r["pass"] else
                            "tap did not lead to a decoded buffer: the code does not resume on a non-'suspended' state")
            results[mode] = r
            pg.close()
        b.close()
    return results


def main():
    ap = argparse.ArgumentParser(description="Simulate WebKit audio gating and check the reader survives it")
    ap.add_argument("html", help="packed reader (whole document or --artifact fragment)")
    ap.add_argument("--chromium", default=DEFAULT_CHROMIUM)
    ap.add_argument("--tap-wait-ms", type=int, default=4000)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    try:
        html = open(a.html, encoding="utf-8").read()
    except Exception as e:
        print(f"[check_reader_live] cannot read {a.html}: {e}", file=sys.stderr)
        return 2
    if not os.path.exists(a.chromium):
        print(f"[check_reader_live] no Chromium at {a.chromium} (set --chromium or KARAOKE_CHROMIUM)",
              file=sys.stderr)
        return 2
    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    tmp.write(wrap_if_fragment(html)); tmp.close()
    try:
        results = run(tmp.name, a.chromium, a.tap_wait_ms)
    except Exception as e:
        print(f"[check_reader_live] could not run the simulation: {e}", file=sys.stderr)
        return 2
    finally:
        os.unlink(tmp.name)

    ok = all(r["pass"] for r in results.values())
    if a.json:
        print(json.dumps({"interoperable": ok, "simulations": results}, indent=2))
    else:
        print(f"=== reader live check (WebKit audio gating simulated): {a.html} ===")
        for mode, r in results.items():
            print(f"  {'PASS' if r['pass'] else 'FAIL'}  {mode:12} {r['why']}")
            print(f"        transcript blocks {r['transcript_children']}, play button "
                  f"{'disabled' if r['play_button_disabled'] else 'enabled'}, "
                  f"boot status {r['boot_status']!r}"
                  + (f", after tap: decoded={r['decoded_after_tap']} status={r['status_after_tap']!r}"
                     if mode == 'interrupted' else ""))
            if r["errors"]:
                print(f"        JS errors: {r['errors']}")
        print(f"\n  RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
