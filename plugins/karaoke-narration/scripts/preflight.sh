#!/usr/bin/env bash
# preflight.sh - checks that the narration pipeline's runtime dependencies are
# actually present, and reports the exact fix if not.
#
# WHY THIS EXISTS
# Dependency gaps in this pipeline surfaced only as buried async failures in
# ~/.karaoke-narration/hook.log during real use - numpy missing, then ffmpeg,
# then faster-whisper, across three separate turns before narration ever
# produced a real file. Nothing checked for them up front.
#
# WHY THIS IS SEPARATE FROM version-guard.sh
# Different concern: version-guard checks that shipped version strings agree
# with each other; this checks that the runtime the pipeline needs is actually
# present. Keeping them apart means each failure mode is diagnosed by name.
#
# SCOPE, ON PURPOSE
# Only the narration path's own minimal dependencies are checked and
# recommended here: piper-tts, faster-whisper, numpy, ffmpeg/ffprobe. The MCP
# server moved to a separate repo at 2.5.0 (karaoke-claude-narration-connector,
# see that repo's mcp/README.md) with its own dependency set (mcp[cli],
# fastapi, uvicorn), deliberately NOT checked or recommended by this script -
# conflating the two, back when both lived in one requirements.txt, is what
# produced a real PyJWT pip/apt conflict during testing: installing the FULL
# file (narration deps + MCP server deps together) pulled in mcp[cli], which
# pulled in a PyJWT version pip tried to uninstall over an apt-managed one.
# The narration path alone never touches PyJWT.
#
# Modes:
#   --report   human-readable summary; always exits 0 (safe as a SessionStart hook)
#
# Guarantees, so this is safe to run automatically on every session:
#   - reads only; never writes, never installs, never deletes
#   - no network access
#   - always exits 0
set -uo pipefail

MODE="${1:---report}"

PIP_CMD='pip install --break-system-packages piper-tts faster-whisper numpy'
APT_CMD='apt-get install -y ffmpeg'

missing=0
out=""
say() { out="${out}$1
"; }

check_bin() { # name
  if command -v "$1" >/dev/null 2>&1; then
    say "OK    $1 on PATH"
  else
    say "MISS  $1 not on PATH"
    missing=1
  fi
}

check_py() { # module
  if python3 -c "import $1" >/dev/null 2>&1; then
    say "OK    python module: $1"
  else
    say "MISS  python module: $1"
    missing=1
  fi
}

check_py_optional() { # module, note
  if python3 -c "import $1" >/dev/null 2>&1; then
    say "OK    python module: $1 (optional)"
  else
    say "INFO  python module: $1 not found - optional, $2"
  fi
}

check_bin ffmpeg
check_bin ffprobe
check_bin piper
check_py numpy
check_py piper
check_py faster_whisper
check_py_optional tiktoken "used only for local output-token estimates; build_karaoke.py degrades gracefully without it"
check_py_optional playwright "used only by interop/check_reader_live.py's optional live-reader simulation; narrate_response.sh already skips it cleanly (exit 2) rather than failing when absent"

printf '%s' "$out"

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "preflight: narration will fail until the above are fixed."
  echo "  system binaries : $APT_CMD"
  echo "  python packages : $PIP_CMD"
  echo "Do NOT run 'pip install -r requirements.txt' to fix this - that also pulls"
  echo "in the separate MCP server's dependencies (mcp[cli], fastapi, uvicorn) and"
  echo "can hit an unrelated PyJWT pip/apt conflict. Use the narration-only command above."
fi

exit 0
