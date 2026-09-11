#!/usr/bin/env bash
# finish_turn.sh - the ONLY sanctioned way to produce a turn artifact.
#
# WHY THIS EXISTS
# Every safeguard in this pipeline - the verbatim gate, the typed step log,
# incremental segment writing - fires only if build_karaoke.py actually runs.
# Nothing forced that. A turn shipped a sixteen-hour-old HTML from a previous
# turn simply because the build was never invoked; no check could fire, because
# no check ran. The failure mode wasn't a wrong artifact, it was an absent one
# masquerading as current.
#
# So this script refuses in the three situations that produced that failure:
#   1. no turn source file for this turn
#   2. source byte-identical to the last build (nothing new was written)
#   3. empty step log (tool calls happened but were never recorded)
#
# Usage: scripts/finish_turn.sh <turn-source.md>
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:?usage: finish_turn.sh <turn-source.md>}"
STATE=state
HASHFILE="$STATE/last_build.sha256"

[ -f "$SRC" ] || { echo "REFUSED: no turn source at $SRC — nothing was written this turn." >&2; exit 3; }

if [ ! -s "$STATE/steps.log" ]; then
  echo "REFUSED: state/steps.log is empty — tool calls were made but never logged." >&2
  exit 4
fi

NEWHASH=$(sha256sum "$SRC" | cut -d' ' -f1)
if [ -f "$HASHFILE" ] && [ "$NEWHASH" = "$(cat "$HASHFILE")" ]; then
  echo "REFUSED: $SRC is byte-identical to the last build." >&2
  echo "         That means this turn's text was never written — exactly the" >&2
  echo "         condition that let a stale artifact ship as current." >&2
  exit 5
fi

# Ground truth, when available. On claude.ai the only source of it is the user
# pasting a response back; save that to state/ground_truth.txt and the build
# gates on it. Absent the file, no check fires - it must not manufacture
# confidence on turns where nothing was pasted.
GT_ARGS=()
if [ -s "$STATE/ground_truth.txt" ]; then
  GT_ARGS=(--verify-against "$STATE/ground_truth.txt")
  echo "ground truth present: build will fail if the source diverges from it"
fi

python3 scripts/build_karaoke.py "$SRC" --labels "Chat response" \
  --attribution-file "$STATE/attribution.json" \
  --steps-file "$STATE/steps.log" \
  "${GT_ARGS[@]}" \
  -o test/response.mp3
# Two variants, same as stop_hook.py: plain for local file access (Claude Code,
# Desktop), --artifact for the Artifact tool (Claude Code Remote, claude.ai). A
# file attachment renders in a static preview that never executes JavaScript,
# so shipping only the plain variant left this "sanctioned" path unusable
# wherever delivery has to go through the Artifact tool - the same failure a
# manual build hit before this fix.
python3 scripts/pack_standalone.py test/response.mp3 test/response.timing.json \
  -o test/response_standalone.html
python3 scripts/pack_standalone.py test/response.mp3 test/response.timing.json \
  --artifact --title "Chat response" -o test/response_artifact.html

# Record this build into the across-build drift log. Never fatal: a broken
# logger must not block a good build.
python3 scripts/qc_log.py --append test/response.timing.json || true

echo "$NEWHASH" > "$HASHFILE"
# Portability. /mnt/user-data/outputs exists only in the claude.ai container.
# On Claude Code, Desktop or a local checkout it does not, and mkdir -p either
# fails or creates a stray root-level tree. Honour an explicit override, fall
# back to the sandbox path when it is really present, else stage locally.
if [ -n "${KARAOKE_OUT_DIR:-}" ]; then
  OUT="$KARAOKE_OUT_DIR"
elif [ -d /mnt/user-data/outputs ]; then
  OUT=/mnt/user-data/outputs/karaoke-demo
else
  OUT="$PWD/out"
fi
mkdir -p "$OUT"
cp test/response_standalone.html "$OUT"/
cp test/response_artifact.html "$OUT"/
echo "staged -> $OUT (response_standalone.html for local file access, response_artifact.html for the Artifact tool)"

echo "OK: built from $SRC ($(wc -w < "$SRC") words), staged to $OUT."
