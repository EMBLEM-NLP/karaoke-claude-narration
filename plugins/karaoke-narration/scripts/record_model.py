#!/usr/bin/env python3
"""
record_model.py - PostModelSwitch hook. Records the model now in effect.

WHY THIS EXISTS
stop_hook.py cannot learn which model produced a turn: the Stop payload carries
session_id, transcript_path and last_assistant_message, never model identity.
Before this hook the only source was KARAOKE_MODEL / KARAOKE_MODEL_ID, set by
hand and therefore stale by default - five consecutive builds once shipped a
model name the session had already switched away from.

PostModelSwitch fires exactly when that value changes, which makes it the only
event that can keep the attribution honest. It writes the new model to
STATE_DIR/model; stop_hook.py prefers that file over the env vars.

Deliberately not fatal in any branch: a missing or malformed payload leaves the
previous recording untouched rather than writing a wrong one. Attribution that
is absent is recoverable; attribution that is confidently wrong is not.
"""
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("KARAOKE_STATE_DIR", Path.home() / ".karaoke-narration"))


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    # The event names the model in effect after the switch. Accept either the
    # nested or flat spelling; neither is guaranteed across versions, and a
    # shape we do not recognise must not overwrite a good previous value.
    model = payload.get("model") or payload.get("to") or {}
    if isinstance(model, dict):
        display = model.get("displayName") or model.get("name") or ""
        ident = model.get("id") or model.get("model") or ""
    else:
        display, ident = str(model), ""

    if not (display or ident):
        return 0

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "model").write_text(
            json.dumps({"model": display, "model_id": ident}) + "\n", encoding="utf-8"
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
