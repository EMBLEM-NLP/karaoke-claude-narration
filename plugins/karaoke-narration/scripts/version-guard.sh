#!/usr/bin/env bash
# version-guard.sh - detects version drift within this package. Adapted from a
# monorepo-wide guard that globbed over sibling plugins under a shared root;
# this package ships on its own, so there is no root above it and no siblings.
#
# Modes:
#   --report         human-readable summary; always exits 0 (safe as a SessionStart hook)
#   --check-changed  same checks, quiet when clean; always exits 0 (safe as a PostToolUse hook)
#   --strict         exits 1 on any drift (use in CI only)
#
# Guarantees, so this is safe to run automatically on every session:
#   - reads only; never writes, never deletes
#   - no network access
#   - no arguments interpolated into a shell
#   - always exits 0 unless --strict was explicitly passed
set -uo pipefail

MODE="${1:---report}"
STRICT=0
[ "$MODE" = "--strict" ] && STRICT=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"   # this plugin's own root - no monorepo above it

SRC="$ROOT/VERSION"
drift=0
out=""
say() { out="${out}$1
"; }

if [ ! -f "$SRC" ]; then
  say "version-guard: no VERSION file at $ROOT - cannot establish source of truth"
  [ "$MODE" != "--check-changed" ] && printf '%s' "$out"
  exit $(( STRICT ))
fi

TRUTH="$(tr -d '[:space:]' < "$SRC")"

if ! printf '%s' "$TRUTH" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'; then
  say "DRIFT VERSION content '$TRUTH' is not valid SemVer 2.0.0"
  drift=1
fi

compare() { # label expected actual
  if [ -z "$3" ]; then
    say "MISS  $1: no version found"
    drift=1
  elif [ "$2" != "$3" ]; then
    say "DRIFT $1: '$3' != VERSION '$2'"
    drift=1
  else
    say "OK    $1: $3"
  fi
}

# --- Axis 1: artifact version surfaces (must all equal VERSION) ---

pj="$ROOT/.claude-plugin/plugin.json"
if [ -f "$pj" ]; then
  v=$(grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$pj" | head -n1 | sed 's/.*"\([^"]*\)"$/\1/')
  compare "plugin.json" "$TRUTH" "$v"
fi

for sk in "$ROOT"/skills/*/SKILL.md; do
  [ -f "$sk" ] || continue
  v=$(awk '/^---$/{n++;next} n==1 && /^[[:space:]]+version:[[:space:]]*/{sub(/^[[:space:]]+version:[[:space:]]*/,"");gsub(/["\047]/,"");print;exit}' "$sk")
  compare "SKILL.md metadata.version (${sk#$ROOT/})" "$TRUTH" "$v"
done

CL="$ROOT/CHANGELOG.md"
if [ -f "$CL" ]; then
  v=$(grep -m1 -oE '^##[[:space:]]*\[?[0-9]+\.[0-9]+\.[0-9]+[^]]*\]?' "$CL" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?')
  compare "CHANGELOG.md newest entry" "$TRUTH" "$v"
fi

if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  t=$(git -C "$ROOT" describe --tags --exact-match 2>/dev/null || true)
  if [ -n "$t" ]; then
    compare "git tag (v-prefix stripped)" "$TRUTH" "${t#v}"
  else
    say "INFO  git: working tree is not on an exact release tag (expected between releases)"
  fi
else
  say "INFO  not a git checkout - tag check skipped"
fi

# --- Axis 2: spec-conformance versions (must NOT equal VERSION) ---

for idx in "$ROOT"/skills/*/references/index.md; do
  [ -f "$idx" ] || continue
  v=$(sed -n 's/^okf_version:[[:space:]]*//p' "$idx" | head -n1 | tr -d '"'\''[:space:]')
  if [ -z "$v" ]; then
    say "MISS  okf_version absent in ${idx#$ROOT/}"
    drift=1
  elif [ "$v" = "$TRUTH" ]; then
    say "DRIFT okf_version '$v' equals the artifact version - axis collapse: the spec version and the release version are independent and must not track each other (see skills/*/references/index.md)"
    drift=1
  else
    say "OK    okf_version: $v (spec axis, correctly independent)"
  fi
done

if [ "$MODE" = "--check-changed" ] && [ "$drift" -eq 0 ]; then
  exit 0
fi

printf '%s' "$out"
if [ "$drift" -ne 0 ]; then
  echo "version-guard: drift detected. Fix VERSION, plugin.json, or SKILL.md by hand (this standalone package has no bump-version.sh - see README)."
fi
[ "$STRICT" -eq 1 ] && exit "$drift"
exit 0
