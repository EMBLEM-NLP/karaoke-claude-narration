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
import hashlib
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

# Opt-in by default. Once enabled, narrate every non-empty assistant response:
# the product promise is "the chat response for each turn", not "long enough
# replies only". Set KARAOKE_EVERY_TURN=0 to restore the older length/code
# filter for installations that want to reduce local TTS work.
MIN_CHARS = int(os.environ.get("KARAOKE_MIN_CHARS", "220"))
EVERY_TURN = os.environ.get("KARAOKE_EVERY_TURN", "1") != "0"
ALLOW_TRANSCRIPT_FALLBACK = os.environ.get("KARAOKE_ALLOW_TRANSCRIPT_FALLBACK") == "1"


def log(msg):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass  # logging must never be the reason a hook fails


def recover_from_transcript(payload):
    """Fallback when last_assistant_message is absent (older Claude Code).

    This is opt-in only. The newest .jsonl under the projects dir may belong to
    another session, so it is not safe for the default verbatim-turn contract."""
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
    acknowledgements. In the default every-turn mode, only empty messages are
    skipped; the legacy length/code filter is available with
    KARAOKE_EVERY_TURN=0."""
    stripped = text.strip()
    if not stripped:
        return False, "empty"
    if EVERY_TURN:
        return True, ""
    if len(stripped) < MIN_CHARS:
        return False, f"below {MIN_CHARS} chars"
    # Strip fenced code before measuring prose - a reply that is almost entirely
    # code has little to narrate, and build_karaoke.py would skip the fences anyway.
    prose = re.sub(r"```.*?```", "", stripped, flags=re.S).strip()
    if len(prose) < MIN_CHARS // 2:
        return False, "mostly code"
    return True, ""


def write_manifest(out_dir, payload, text, source, status, error=None, files=None):
    manifest = {
        "schema_version": "1.0",
        "status": status,
        "session_id": payload.get("session_id") or "",
        "source": source,
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "created_at": int(time.time()),
    }
    if error:
        manifest["error"] = error
    if files:
        manifest["files"] = files
    try:
        (out_dir / "source_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as e:
        log(f"could not write source manifest for {out_dir.name}: {e}")


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
        if not ALLOW_TRANSCRIPT_FALLBACK:
            log("no last_assistant_message found; skipped to avoid narrating stale text")
            return 0
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
    write_manifest(out_dir, payload, text, source, "captured")

    mp3 = out_dir / "response.mp3"
    cmd = [
        sys.executable, str(BUILD), str(turn_md),
        "-o", str(mp3),
        "--labels", "Chat response",
        "--verify-against", str(turn_md),
    ]
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
            write_manifest(out_dir, payload, text, source, "qc_failed")
            log(f"QC gate failed for {out_dir.name}; audio not shipped")
            return 0
        if r.returncode != 0:
            err = r.stderr.strip()[:300]
            write_manifest(out_dir, payload, text, source, "build_failed", err)
            log(f"build failed rc={r.returncode}: {err}")
            return 0
        timing = mp3.with_suffix("").with_suffix(".timing.json")
        timing = out_dir / "response.timing.json"
        standalone = subprocess.run(
            [sys.executable, str(PACK), str(mp3), str(timing),
             "-o", str(out_dir / "response_standalone.html")],
            capture_output=True, text=True, timeout=120,
        )
        if standalone.returncode != 0:
            err = standalone.stderr.strip()[:300]
            write_manifest(out_dir, payload, text, source, "pack_failed", err)
            log(f"standalone pack failed rc={standalone.returncode}: {err}")
            return 0
        # Also the Artifact fragment. A remote session (claude.ai, Cowork) can
        # only deliver the player as an Artifact: a file attachment renders in a
        # static preview that never executes its script, so the reader sees an
        # empty shell showing the markup's boot text and nothing else.
        artifact = subprocess.run(
            [sys.executable, str(PACK), str(mp3), str(timing), "--artifact",
             "-o", str(out_dir / "response_artifact.html")],
            capture_output=True, text=True, timeout=120,
        )
        if artifact.returncode != 0:
            err = artifact.stderr.strip()[:300]
            write_manifest(out_dir, payload, text, source, "pack_failed", err)
            log(f"artifact pack failed rc={artifact.returncode}: {err}")
            return 0
        write_manifest(
            out_dir, payload, text, source, "ready",
            files=[
                "turn.md",
                "response.mp3",
                "response.timing.json",
                "response_standalone.html",
                "response_artifact.html",
            ],
        )
        log(f"narrated {out_dir.name} via {source} ({len(text)} chars)")
    except subprocess.TimeoutExpired:
        write_manifest(out_dir, payload, text, source, "timeout")
        log(f"build timed out for {out_dir.name}")
    except Exception as e:
        write_manifest(out_dir, payload, text, source, "failed", str(e)[:300])
        log(f"unexpected failure: {e}")
    return 0


if __name__ == "__main__":
    # Always exit 0. A narration side-effect must never stall or redirect the
    # agent loop, whatever goes wrong inside it.
    sys.exit(main())
