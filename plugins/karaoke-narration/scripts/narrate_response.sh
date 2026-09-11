#!/usr/bin/env bash
# narrate_response.sh - narrate a real chat turn VERBATIM.
#
# Usage: narrate_response.sh <turn-dir> <title> "Label:file.md" ["Label:file.md" ...]
#
# Example, the common shape:
#   narrate_response.sh turns/007 "Narrated turn" \
#     "Thought process:reasoning.md" "Chat response:response.md"
#
# THE FILES ARE THE REPLY. The chat message must be their content, in order,
# byte for byte. Narrating a script written ALONGSIDE the reply is not narration:
# seven artifacts in the session that produced this wrapper reported
# source_matches_ground_truth as NOT CHECKED, because no ground truth existed.
# The gate only means something when the narrated file IS the message.
#
# Variadic because build_karaoke.py is: its input is documented as "one or more
# .md/.txt files, EACH FILE IS ONE TURN, rendered as its own labeled,
# separately-navigable section". A wrapper that hardcoded two was narrower than
# the tool underneath for no reason.
#
# WHY A TURN DIRECTORY AND NEVER A SHARED PATH
# Artifact publishing is keyed to the output file path, so republishing one path
# means every turn OVERWRITES the last. That is not hypothetical: a 34-word reply
# destroyed a 369-word narration and only the final turn survived at that URL.
# A per-turn directory is what makes a per-turn permanent link. Nothing here
# writes to a shared output, and that is the entire guarantee.
#
# The ground truth is the concatenation, written HERE rather than by hand,
# because a hand-maintained copy is a third text that can drift from the ones it
# claims to represent. Any gate failure exits non-zero BEFORE packing, so a build
# that did not pass is never publishable.
set -euo pipefail

DIR="${1:?usage: narrate_response.sh <turn-dir> <title> \"Label:file.md\" ...}"
TITLE="${2:?usage: narrate_response.sh <turn-dir> <title> \"Label:file.md\" ...}"
shift 2
[ "$#" -ge 1 ] || { echo "need at least one Label:file pair" >&2; exit 64; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$ROOT/skills/karaoke-narration/scripts"
I="$ROOT/interop"

mkdir -p "$DIR"
GT="$DIR/ground_truth.md"
: > "$GT"
FILES=(); LABELS=()
for pair in "$@"; do
  case "$pair" in
    *:*) ;;
    *) echo "argument '$pair' is not Label:file" >&2; exit 64 ;;
  esac
  label="${pair%%:*}"; file="${pair#*:}"
  [ -f "$file" ] || { echo "no such file: $file" >&2; exit 66; }
  LABELS+=("$label"); FILES+=("$file")
  cat "$file" >> "$GT"; printf '\n\n' >> "$GT"
done

W=$(cat "${FILES[@]}" | wc -w)
[ "$W" -gt 800 ] && echo "WARN: $W words > ~800; check_reader.py derives the phone ceiling at ~884" >&2
grep -qE '^\|' "${FILES[@]}" && echo "WARN: markdown table found; the parser swallows tables into one paragraph" >&2
grep -qE '(^|[^(])https?://' "${FILES[@]}" && echo "WARN: bare URL found; write links as [label](url), label one word" >&2

python3 "$S/build_karaoke.py" "${FILES[@]}" \
  --labels "${LABELS[@]}" \
  --verify-against "$GT" -o "$DIR/turn.mp3" \
  | sed -n '/=== KARAOKE QC REPORT ===/,$p'
python3 "$S/pack_standalone.py" "$DIR/turn.mp3" "$DIR/turn.timing.json" \
  --artifact --title "$TITLE" -o "$DIR/turn.html"
python3 "$I/validate_timing.py" "$DIR/turn.timing.json" | grep RESULT

# check_reader_live.py's own contract (see its docstring) is tri-state: exit 0
# pass, 1 a real simulation failure, 2 could not run at all (e.g. no
# playwright installed - it is documented as the "optional, heavier half").
# Treating 2 the same as 1 under `set -e` aborted this script even when the
# actual narration had already been built and had already passed every real
# QC gate - conflating "no signal" with "bad signal", the exact anti-pattern
# this package rejected elsewhere for source_matches_ground_truth.
set +e
CRL_OUT="$(python3 "$I/check_reader_live.py" "$DIR/turn.html" 2>&1)"
CRL_RC=$?
set -e
case "$CRL_RC" in
  0) echo "$CRL_OUT" | grep RESULT ;;
  1) echo "$CRL_OUT" >&2
     echo "check_reader_live: a real simulation failure - not publishable" >&2
     exit 1 ;;
  2) echo "check_reader_live: SKIPPED (could not run - $(echo "$CRL_OUT" | tail -1))" ;;
  *) echo "$CRL_OUT" >&2; exit "$CRL_RC" ;;
esac

echo "words: $W   publish: $DIR/turn.html"
