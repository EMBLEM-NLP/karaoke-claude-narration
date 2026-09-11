#!/usr/bin/env bash
# pending_narration.sh - UserPromptSubmit bridge for karaoke-narration.
#
# This remote container has no listener for the files stop_hook.py produces -
# nothing plays or forwards them. This script closes that gap: it looks for
# any turn's response_standalone.html that hasn't been marked delivered yet
# and surfaces its path as additional context, so Claude notices at the start
# of the next turn and sends it to the user via SendUserFile.
#
# Delivery is marked by creating an empty "<turn-dir>/.sent" file after the
# send succeeds - Claude does this, not this script, since only Claude knows
# whether SendUserFile actually ran.
set -uo pipefail

STATE_DIR="${KARAOKE_STATE_DIR:-$HOME/.karaoke-narration}"
TURNS_DIR="$STATE_DIR/turns"

[ -d "$TURNS_DIR" ] || exit 0

pending=()
for d in "$TURNS_DIR"/*/; do
  [ -d "$d" ] || continue
  html="${d%/}/response_standalone.html"
  sent="${d%/}/.sent"
  if [ -f "$html" ] && [ ! -f "$sent" ]; then
    pending+=("$html")
  fi
done

[ ${#pending[@]} -eq 0 ] && exit 0

python3 - "${pending[@]}" <<'PY'
import json, sys

files = sys.argv[1:]
lines = [
    "karaoke-narration produced new turn audio that has not reached the user yet "
    "(this remote container has no listener - narration hooks only write to disk).",
    "Send each file below to the user now via SendUserFile, then mark it delivered "
    "by creating an empty file at the same path with .sent appended, e.g.:",
    "  touch \"<dir-of-the-file-below>/.sent\"",
    "",
]
for f in files:
    lines.append(f"- {f}")

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "\n".join(lines),
    }
}))
PY
