#!/usr/bin/env python3
"""Karaoke narration MCP server - one codebase, two transports.

WHICH TRANSPORT, AND WHY IT MATTERS

  stdio   -> Claude Desktop (claude_desktop_config.json) and Claude Code.
             Runs on YOUR machine. Can read your files and keychain.
             NOT available in Cowork or claude.ai.

  http    -> Custom connector for claude.ai / Cowork / Desktop.
             Anthropic's cloud dials your URL, so it must be publicly
             reachable. It does NOT originate from your device, which means a
             deployed server cannot see your keychain, your browser on :9222,
             or ~/.claude/projects.

  hybrid  -> run http here, expose it with a tunnel. Satisfies the public-URL
             requirement while the process still runs locally with local access.
             The tunnel must stay up, and the endpoint needs its own auth.

CREDENTIALS: this server takes none. Narration is a pure function - text in,
audio out - so there is nothing here worth stealing and nothing to leak into a
transcript. Anything needing your secrets should use stdio and read them
locally; see references/credential-handling.md.

Run:
  python3 server.py                  # stdio (default)
  python3 server.py --http --port 8787
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "karaoke-narration" / "scripts"
BUILD = SKILL / "build_karaoke.py"
PACK = SKILL / "pack_standalone.py"

mcp = FastMCP("karaoke-narration")


@mcp.tool()
def narrate(
    text: str,
    model: str = "",
    model_id: str = "",
    mode: str = "",
    steps: str = "",
) -> str:
    """Turn a chat response into narrated audio with word-level highlighting.

    Returns a JSON report: output paths, QC checks, and per-sentence alignment
    confidence. Fails loudly rather than shipping audio that did not pass QC.

    text:     the response to narrate, verbatim
    model:    display name for the attribution byline, e.g. "Claude Opus 5"
    model_id: API model string, e.g. "claude-opus-5"
    mode:     effort mode, if known. Left blank rather than guessed
    steps:    newline-delimited tool-call descriptions, optionally prefixed
              "tool|", "edit|" or "file|"; groups separated by a "---" line
    """
    if not text.strip():
        return json.dumps({"ok": False, "error": "empty text"})

    work = Path(tempfile.mkdtemp(prefix="karaoke_mcp_"))
    src = work / "turn.md"
    src.write_text(text, encoding="utf-8")

    cmd = [sys.executable, str(BUILD), str(src), "--labels", "Chat response",
           "-o", str(work / "response.mp3")]
    if model:
        cmd += ["--model", model]
    if model_id:
        cmd += ["--model-id", model_id]
    if mode:
        cmd += ["--mode", mode]
    if steps.strip():
        sf = work / "steps.log"
        sf.write_text(steps, encoding="utf-8")
        cmd += ["--steps-file", str(sf)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    # exit 2 is the QC gate refusing to ship; surface it rather than hide it
    if r.returncode == 2:
        return json.dumps({"ok": False, "error": "QC gate failed - audio not shipped",
                           "report": r.stdout[-2000:]}, indent=2)
    if r.returncode != 0:
        return json.dumps({"ok": False, "error": f"build failed rc={r.returncode}",
                           "stderr": r.stderr[-1500:]}, indent=2)

    timing = work / "response.timing.json"
    subprocess.run([sys.executable, str(PACK), str(work / "response.mp3"), str(timing),
                    "-o", str(work / "response_standalone.html")],
                   capture_output=True, text=True, timeout=300)

    manifest = json.loads(timing.read_text())
    return json.dumps({
        "ok": True,
        "audio": str(work / "response.mp3"),
        "player": str(work / "response_standalone.html"),
        "duration_s": manifest["duration"],
        "words": len(manifest["words"]),
        "qc": manifest["qc"]["checks"],
        "avg_word_match_rate": manifest["qc"].get("avg_word_match_rate"),
        "low_confidence_sentences": manifest["qc"].get("low_confidence_sentences"),
    }, indent=2)


@mcp.tool()
def verify_against_ground_truth(built_text: str, ground_truth: str) -> str:
    """Diff a built turn against what was actually said, word by word.

    Exists because the in-flight turn is not retrievable from any API or export
    - a turn enters a store when it ends - so on claude.ai the only ground truth
    is a transcript supplied by the user.
    """
    import difflib, re

    def norm(t):
        t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
        t = t.replace("**", "").replace("`", "")
        return re.sub(r"\s+", " ", t).strip().split()

    a, b = norm(ground_truth), norm(built_text)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    diffs = [{"op": op, "truth": a[i1:i2][:10], "built": b[j1:j2][:10]}
             for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    return json.dumps({"similarity": round(sm.ratio(), 4),
                       "matches": not diffs, "differences": diffs[:20]}, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true",
                    help="serve over HTTP for use as a custom connector (needs a public URL)")
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    if a.http:
        mcp.settings.port = a.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
