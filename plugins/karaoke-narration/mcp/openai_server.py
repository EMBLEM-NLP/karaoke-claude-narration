#!/usr/bin/env python3
"""OpenAI/Codex MCP adapter for karaoke narration.

This file keeps the existing narration engine but changes the integration
contract: tools return structured objects and opaque narration IDs instead of
stringified JSON and server-local paths.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - lets pure tests import this module
    FastMCP = None  # type: ignore[assignment]


ROOT = Path(os.environ.get("KARAOKE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))
DATA = Path(
    os.environ.get(
        "KARAOKE_PLUGIN_DATA",
        os.environ.get("PLUGIN_DATA", Path.home() / ".karaoke-narration" / "openai"),
    )
)
BUILD = ROOT / "skills" / "karaoke-narration" / "scripts" / "build_karaoke.py"
PACK = ROOT / "skills" / "karaoke-narration" / "scripts" / "pack_standalone.py"
VALIDATE = ROOT / "interop" / "validate_timing.py"
MAX_TEXT_CHARS = int(os.environ.get("KARAOKE_MAX_TEXT_CHARS", "20000"))


def normalize_words(text: str) -> list[str]:
    """Normalize markdown-ish text for ground-truth comparison."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip().split()


def compare_texts(built_text: str, ground_truth: str) -> dict[str, Any]:
    truth = normalize_words(ground_truth)
    built = normalize_words(built_text)
    matcher = difflib.SequenceMatcher(None, truth, built, autojunk=False)
    diffs = [
        {
            "op": op,
            "truth": truth[i1:i2][:12],
            "built": built[j1:j2][:12],
        }
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
        if op != "equal"
    ]
    return {
        "matches": not diffs,
        "similarity": round(matcher.ratio(), 4),
        "differences": diffs[:25],
    }


def _status_path(narration_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", narration_id):
        raise ValueError("invalid narration_id")
    return DATA / "narrations" / narration_id / "status.json"


def _write_status(narration_id: str, status: dict[str, Any]) -> None:
    path = _status_path(narration_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")


def _read_status(narration_id: str) -> dict[str, Any]:
    path = _status_path(narration_id)
    if not path.exists():
        return {"ok": False, "error": "not_found", "narration_id": narration_id}
    return json.loads(path.read_text(encoding="utf-8"))


def _check_module(module: str) -> bool:
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
    ).returncode == 0


def preflight() -> dict[str, Any]:
    """Report runtime readiness without installing or writing anything."""
    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "piper_binary": shutil.which("piper") is not None,
        "numpy": _check_module("numpy"),
        "piper_module": _check_module("piper"),
        "faster_whisper": _check_module("faster_whisper"),
        "build_script": BUILD.exists(),
        "pack_script": PACK.exists(),
    }
    required = [
        "ffmpeg",
        "ffprobe",
        "piper_binary",
        "numpy",
        "piper_module",
        "faster_whisper",
        "build_script",
        "pack_script",
    ]
    missing = [name for name in required if not checks[name]]
    return {
        "ok": not missing,
        "checks": checks,
        "missing": missing,
        "fix": {
            "system": "apt-get install -y ffmpeg",
            "python": "pip install --break-system-packages piper-tts faster-whisper numpy",
        }
        if missing
        else None,
    }


def narrate_text(
    text: str,
    title: str = "Narrated response",
    label: str = "Chat response",
    model: str | None = None,
    model_id: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Build a narration bundle and return an opaque ID plus QC metadata."""
    if not text or not text.strip():
        return {"ok": False, "error": "empty_text"}
    if len(text) > MAX_TEXT_CHARS:
        return {
            "ok": False,
            "error": "text_too_large",
            "max_chars": MAX_TEXT_CHARS,
            "actual_chars": len(text),
        }

    narration_id = token_urlsafe(18)
    out_dir = DATA / "narrations" / narration_id
    out_dir.mkdir(parents=True, exist_ok=False)
    source = out_dir / "source.md"
    ground_truth = out_dir / "ground_truth.md"
    source.write_text(text, encoding="utf-8")
    ground_truth.write_text(text + "\n", encoding="utf-8")

    safe_title = html.escape(title.strip()[:120] or "Narrated response")
    started = time.time()
    status: dict[str, Any] = {
        "ok": None,
        "state": "running",
        "narration_id": narration_id,
        "created_at": int(started),
        "title": safe_title,
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    _write_status(narration_id, status)

    mp3 = out_dir / "turn.mp3"
    cmd = [
        sys.executable,
        str(BUILD),
        str(source),
        "--labels",
        label,
        "--verify-against",
        str(ground_truth),
        "-o",
        str(mp3),
    ]
    if model:
        cmd += ["--model", model]
    if model_id:
        cmd += ["--model-id", model_id]
    if mode:
        cmd += ["--mode", mode]

    run = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if run.returncode != 0:
        status.update(
            {
                "ok": False,
                "state": "failed",
                "error": "qc_gate_failed" if run.returncode == 2 else "build_failed",
                "returncode": run.returncode,
                "stdout_tail": run.stdout[-2000:],
                "stderr_tail": run.stderr[-2000:],
                "elapsed_s": round(time.time() - started, 2),
            }
        )
        _write_status(narration_id, status)
        return status

    timing = out_dir / "turn.timing.json"
    player = out_dir / "turn.html"
    packed = subprocess.run(
        [
            sys.executable,
            str(PACK),
            str(mp3),
            str(timing),
            "--artifact",
            "--title",
            safe_title,
            "-o",
            str(player),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if packed.returncode != 0:
        status.update(
            {
                "ok": False,
                "state": "failed",
                "error": "pack_failed",
                "stderr_tail": packed.stderr[-2000:],
                "elapsed_s": round(time.time() - started, 2),
            }
        )
        _write_status(narration_id, status)
        return status

    validation = None
    if VALIDATE.exists():
        validation = subprocess.run(
            [sys.executable, str(VALIDATE), str(timing)],
            capture_output=True,
            text=True,
            timeout=120,
        )

    manifest = json.loads(timing.read_text(encoding="utf-8"))
    status.update(
        {
            "ok": True,
            "state": "ready",
            "duration_s": manifest.get("duration"),
            "word_count": len(manifest.get("words", [])),
            "qc": manifest.get("qc", {}),
            "timing_schema_result": validation.stdout.strip() if validation else "not_checked",
            "player_available": player.exists(),
            "elapsed_s": round(time.time() - started, 2),
        }
    )
    _write_status(narration_id, status)
    return status


def get_status(narration_id: str) -> dict[str, Any]:
    """Return status and QC metadata for a narration ID."""
    try:
        return _read_status(narration_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def get_player(narration_id: str) -> dict[str, Any]:
    """Return the packed player HTML for a narration ID."""
    try:
        status = _read_status(narration_id)
        if not status.get("ok"):
            return status
        player = _status_path(narration_id).parent / "turn.html"
        if not player.exists():
            return {"ok": False, "error": "player_not_found", "narration_id": narration_id}
        return {
            "ok": True,
            "narration_id": narration_id,
            "content_type": "text/html",
            "html": player.read_text(encoding="utf-8"),
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def verify_against_ground_truth(narration_id: str, ground_truth: str) -> dict[str, Any]:
    """Compare stored source text with supplied ground truth."""
    try:
        source = _status_path(narration_id).parent / "source.md"
        if not source.exists():
            return {"ok": False, "error": "not_found", "narration_id": narration_id}
        comparison = compare_texts(source.read_text(encoding="utf-8"), ground_truth)
        return {"ok": comparison["matches"], "narration_id": narration_id, **comparison}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def delete_narration(narration_id: str) -> dict[str, Any]:
    """Delete one narration bundle."""
    try:
        directory = _status_path(narration_id).parent
        if not directory.exists():
            return {"ok": False, "error": "not_found", "narration_id": narration_id}
        shutil.rmtree(directory)
        return {"ok": True, "narration_id": narration_id, "deleted": True}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def register_tools(mcp: Any) -> None:
    mcp.tool()(preflight)
    mcp.tool()(narrate_text)
    mcp.tool()(get_status)
    mcp.tool()(get_player)
    mcp.tool()(verify_against_ground_truth)
    mcp.tool()(delete_narration)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if FastMCP is None:
        print("mcp package is not installed; run pip install mcp[cli]==1.29.0", file=sys.stderr)
        return 1

    mcp = FastMCP("karaoke-narration")
    register_tools(mcp)
    if args.http:
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
