#!/usr/bin/env python3
"""JSON-safe Stop-hook entrypoint for Codex and Claude-compatible runtimes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    payload = sys.stdin.read()
    hook = Path(__file__).resolve().with_name("stop_hook.py")
    try:
        subprocess.run(
            [sys.executable, str(hook)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=590,
        )
    except Exception:
        pass
    print(json.dumps({"continue": True, "suppressOutput": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
