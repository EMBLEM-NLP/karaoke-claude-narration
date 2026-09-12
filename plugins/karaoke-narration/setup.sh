#!/usr/bin/env bash
# setup.sh - install the runtime dependencies this package needs but does not bundle.
#
# WHY THIS IS SEPARATE FROM INSTALLING THE PLUGIN
# Installing the plugin (marketplace or install.sh) registers hooks. It does not
# install software. These dependencies are a property of the MACHINE, not of the
# plugin: ffmpeg/ffprobe are OS packages that pip cannot provide, and the Python
# packages land in the interpreter the hooks will run under. So this is its own
# step, run once per machine - or once per container, since an ephemeral cloud
# container starts without them every time even when the plugin install itself
# persists in user config.
#
# Skipping this does not fail loudly at install time. It fails later, inside an
# async Stop hook, as a line in ~/.karaoke-narration/hook.log that nobody is
# watching - which is exactly how a real install sat broken for several turns,
# reporting nothing, before anyone looked. scripts/preflight.sh exists to
# surface that at session start; this script is what fixes what it reports.
#
# Usage:
#   bash setup.sh            # show what is missing and what would be installed
#   bash setup.sh --apply    # install it
set -uo pipefail

MODE="${1:---dry-run}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Narration-only dependencies - this is all requirements.txt carries as of
# 2.5.0. The MCP server and its requirements (mcp[cli], fastapi, uvicorn) moved
# to a separate repo, karaoke-claude-narration-connector, with its own install
# path in that repo's mcp/README.md.
PIP_PKGS="piper-tts faster-whisper numpy"
APT_PKGS="ffmpeg"

need_apt=0
need_pip=0

command -v ffmpeg  >/dev/null 2>&1 || need_apt=1
command -v ffprobe >/dev/null 2>&1 || need_apt=1
for m in numpy piper faster_whisper; do
  python3 -c "import $m" >/dev/null 2>&1 || need_pip=1
done

if [ "$need_apt" -eq 0 ] && [ "$need_pip" -eq 0 ]; then
  echo "setup: everything this package needs is already present."
  echo "       (run 'bash $HERE/scripts/preflight.sh --report' for the full picture)"
  exit 0
fi

echo "setup: missing dependencies detected."
[ "$need_apt" -eq 1 ] && echo "  system : $APT_PKGS   (ffmpeg provides both ffmpeg and ffprobe)"
[ "$need_pip" -eq 1 ] && echo "  python : $PIP_PKGS"
echo ""

if [ "$MODE" != "--apply" ]; then
  echo "DRY RUN - nothing installed. Commands that --apply would run:"
  [ "$need_apt" -eq 1 ] && echo "  apt-get update && apt-get install -y $APT_PKGS"
  [ "$need_pip" -eq 1 ] && echo "  pip install --break-system-packages $PIP_PKGS"
  echo ""
  echo "Re-run with --apply to install. Both need the privileges your system"
  echo "requires for them - prefix with sudo if that is how this machine works."
  exit 0
fi

rc=0

if [ "$need_apt" -eq 1 ]; then
  echo "==> installing system packages"
  # A stale package index is the common first failure here; refresh before
  # installing rather than reporting a confusing 404 on a package that exists.
  apt-get update && apt-get install -y $APT_PKGS || {
    echo "setup: system package install failed. If this is a permissions error," >&2
    echo "       re-run as: sudo bash setup.sh --apply" >&2
    rc=1
  }
fi

if [ "$need_pip" -eq 1 ]; then
  echo "==> installing python packages"
  pip install --break-system-packages $PIP_PKGS || {
    echo "setup: pip install failed." >&2
    rc=1
  }
fi

echo ""
echo "==> verifying"
bash "$HERE/scripts/preflight.sh" --report

exit "$rc"
