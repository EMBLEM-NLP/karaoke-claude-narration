#!/usr/bin/env python3
"""
stop_hook.py - Claude Code Stop hook. Narrates each assistant turn.

WHY A STOP HOOK AND NOT THE SKILL:
Skills are model-invoked - Claude decides whether to load one by matching the
request against the SKILL.md description. There is no supported frontmatter flag
that forces a skill to load every turn, and description-engineering is measurably
unreliable for this (community benchmarks put unoptimized auto-activation near a
coin flip). Deterministic "every turn" behavior comes from a hook. So the hook
owns automatic firing; the SKILL.md stays for manual and claude.ai use, where no
hook runtime exists at all.

WHY Stop AND NOT UserPromptSubmit:
UserPromptSubmit fires before Claude responds, so the response text does not yet
exist. Stop fires when Claude finishes responding and is the only per-turn event
that carries the assistant's completed text.

CONTRACT (Claude Code Stop payload, on stdin as JSON):
  session_id            - current session id
  transcript_path       - conversation JSONL; written asynchronously and MAY LAG
  stop_hook_active      - true when Claude is already continuing due to a stop
                          hook; used here purely as a re-entrancy guard
  last_assistant_message- the final assistant text of the turn (preferred source)

This hook NEVER blocks. It does not emit `decision: "block"` and always exits 0,
so it cannot trigger the Stop -> block -> Stop loop that the block cap exists to
contain. Failures degrade to a log line, never to a stalled agent.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# LOAD-BEARING FALLBACK, not incidental defaulting. CLAUDE_PLUGIN_ROOT is set
# only when Claude Code loads this as a real plugin. It is unset whenever the
# hook is wired up by hand - which is what install.sh does, and the only route
# available on surfaces where plugin installation is unavailable or refused.
# Resolving from __file__ is what makes those installs work at all.
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))
BUILD = PLUGIN_ROOT / "skills" / "karaoke-narration" / "scripts" / "build_karaoke.py"
PACK = PLUGIN_ROOT / "skills" / "karaoke-narration" / "scripts" / "pack_standalone.py"

STATE_DIR = Path(os.environ.get("KARAOKE_STATE_DIR", Path.home() / ".karaoke-narration"))
ENABLE_FLAG = STATE_DIR / "enabled"
LOG = STATE_DIR / "hook.log"
MODEL_FILE = STATE_DIR / "model"

# Opt-in by default. Synthesizing TTS on every turn is slow and wasteful on
# one-line acknowledgements, so narration stays off until explicitly enabled
# via `/karaoke on`. Set KARAOKE_ALWAYS=1 to bypass.
MIN_CHARS = int(os.environ.get("KARAOKE_MIN_CHARS", "220"))


def log(msg):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass  # logging must never be the reason a hook fails


def recover_from_transcript(payload):
    """Fallback when last_assistant_message is absent (older Claude Code).

    Deliberately ignores the payload's transcript_path: it is documented as
    lagging, and has been reported pointing at a stale file. The newest .jsonl
    under the projects dir is the more reliable choice."""
    try:
        candidates = list((Path.home() / ".claude" / "projects").rglob("*.jsonl"))
        if not candidates:
            return ""
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        last = ""
        with newest.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                content = rec.get("message", {}).get("content", [])
                parts = [c.get("text", "") for c in content
                         if isinstance(c, dict) and c.get("type") == "text"]
                if parts:
                    last = "\n\n".join(parts)
        return last
    except Exception as e:
        log(f"transcript fallback failed: {e}")
        return ""


def worth_narrating(text):
    """Skip what would be tedious or meaningless to listen to.

    Stop has no matcher, so it fires on every turn including one-word
    acknowledgements. Content filtering has to happen here or not at all."""
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return False, f"below {MIN_CHARS} chars"
    # Strip fenced code before measuring prose - a reply that is almost entirely
    # code has little to narrate, and build_karaoke.py would skip the fences anyway.
    prose = re.sub(r"```.*?```", "", stripped, flags=re.S).strip()
    if len(prose) < MIN_CHARS // 2:
        return False, "mostly code"
    return True, ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        log(f"unreadable payload: {e}")
        return 0

    # Re-entrancy guard. Not strictly required for a non-blocking hook, but
    # cheap, and correct if this ever grows a decision field.
    if payload.get("stop_hook_active"):
        return 0

    if not (ENABLE_FLAG.exists() or os.environ.get("KARAOKE_ALWAYS") == "1"):
        return 0

    text = payload.get("last_assistant_message") or ""
    source = "last_assistant_message"
    if not text.strip():
        text = recover_from_transcript(payload)
        source = "transcript fallback"
    if not text.strip():
        log("no assistant text found; nothing to narrate")
        return 0

    ok, why = worth_narrating(text)
    if not ok:
        log(f"skipped ({why})")
        return 0

    session = (payload.get("session_id") or "session")[:12]
    out_dir = STATE_DIR / "turns" / f"{session}-{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)
    turn_md = out_dir / "turn.md"
    turn_md.write_text(text, encoding="utf-8")

    mp3 = out_dir / "response.mp3"
    cmd = [sys.executable, str(BUILD), str(turn_md), "-o", str(mp3), "--labels", "Chat response"]
    # Model attribution. The Stop payload carries session_id, transcript_path
    # and last_assistant_message - never model identity - so this hook cannot
    # read the running model directly. It used to depend solely on KARAOKE_MODEL
    # / KARAOKE_MODEL_ID, which are set by hand and stale by default: five
    # consecutive builds once shipped a model name the session had already
    # switched away from.
    #
    # STATE_DIR/model closes that: record_model.py writes it from the
    # PostModelSwitch hook, the one event that fires exactly when the value
    # changes. Precedence is freshest-source-first - the recorded file, then the
    # env vars as a manual override for installs with no hook runtime, then
    # nothing. Stamping no attribution is the correct floor; per
    # build_karaoke.py's design note a wrong model is worse than none.
    model = model_id = None
    try:
        recorded = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
        model = recorded.get("model") or None
        model_id = recorded.get("model_id") or None
    except Exception:
        pass
    if not (model or model_id):
        model = os.environ.get("KARAOKE_MODEL")
        model_id = os.environ.get("KARAOKE_MODEL_ID")
    if model:
        cmd += ["--model", model]
    if model_id:
        cmd += ["--model-id", model_id]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=540)
        if r.returncode == 2:
            log(f"QC gate failed for {out_dir.name}; audio not shipped")
            return 0
        if r.returncode != 0:
            log(f"build failed rc={r.returncode}: {r.stderr.strip()[:300]}")
            return 0
        timing = mp3.with_suffix("").with_suffix(".timing.json")
        timing = out_dir / "response.timing.json"
        subprocess.run(
            [sys.executable, str(PACK), str(mp3), str(timing),
             "-o", str(out_dir / "response_standalone.html")],
            capture_output=True, text=True, timeout=120,
        )
        # Also the Artifact fragment. A remote session (claude.ai, Cowork) can
        # only deliver the player as an Artifact: a file attachment renders in a
        # static preview that never executes its script, so the reader sees an
        # empty shell showing the markup's boot text and nothing else.
        subprocess.run(
            [sys.executable, str(PACK), str(mp3), str(timing), "--artifact",
             "-o", str(out_dir / "response_artifact.html")],
            capture_output=True, text=True, timeout=120,
        )
        log(f"narrated {out_dir.name} via {source} ({len(text)} chars)")
    except subprocess.TimeoutExpired:
        log(f"build timed out for {out_dir.name}")
    except Exception as e:
        log(f"unexpected failure: {e}")
    return 0


if __name__ == "__main__":
    # Always exit 0. A narration side-effect must never stall or redirect the
    # agent loop, whatever goes wrong inside it.
    sys.exit(main())
