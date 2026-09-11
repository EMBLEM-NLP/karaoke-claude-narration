#!/usr/bin/env bash
# install.sh - wire the hooks into Claude Code by hand.
#
# PREFER THE MARKETPLACE INSTALL. This script is the fallback.
# `/plugin marketplace add` + `/plugin install` registers this package's hooks
# from hooks/hooks.json directly, touching no settings file at all. See README.
# Use this script only where that is unavailable - no network access to the
# marketplace repo, or a session already running that cannot take the
# `--plugin-dir` startup flag.
#
# WHAT IT DOES, PLAINLY
# It merges this package's hooks into ~/.claude/settings.json, leaving anything
# already there untouched. Those are USER-level hooks: once written, they run in
# every future Claude Code session for this user, not just this project. That is
# a real change to how the tool behaves from then on, which is why it is a
# deliberate, separate step rather than something the plugin does for you. Read
# the dry run before applying it, and use --uninstall to reverse it.
#
# Usage:
#   bash install.sh              # dry run: print what would change, write nothing
#   bash install.sh --apply      # merge the hooks in (a .bak is written first)
#   bash install.sh --uninstall  # remove only this package's hook entries
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
MODE="${1:---dry-run}"

command -v jq >/dev/null 2>&1 || {
  echo "install.sh needs jq to merge JSON without clobbering what is already there." >&2
  echo "Install it (apt-get install jq / brew install jq) and re-run." >&2
  exit 1
}

# The hook block, with this checkout's real path baked in. ${CLAUDE_PLUGIN_ROOT}
# is only substituted for genuine plugin loads; a hand-wired hook must carry an
# absolute path or it resolves to nothing.
BLOCK=$(jq -n --arg root "$HERE" '{
  SessionStart: [{
    matcher: "startup|resume",
    hooks: [{ type: "command", command: "bash",
              args: [($root + "/scripts/version-guard.sh"), "--report"],
              timeout: 10, _karaoke: true },
            { type: "command", command: "bash",
              args: [($root + "/scripts/preflight.sh"), "--report"],
              timeout: 10, _karaoke: true }]
  }],
  PostModelSwitch: [{
    hooks: [{ type: "command", command: "python3",
              args: [($root + "/scripts/record_model.py")],
              timeout: 10, _karaoke: true }]
  }],
  Stop: [{
    hooks: [{ type: "command", command: "python3",
              args: [($root + "/scripts/stop_hook.py")],
              async: true, timeout: 600,
              statusMessage: "Narrating this turn", _karaoke: true }]
  }]
}')

# Read the current settings without creating anything - a dry run must leave the
# filesystem exactly as it found it, including not conjuring an empty settings
# file for a user who has none.
if [ -f "$SETTINGS" ]; then
  jq -e . "$SETTINGS" >/dev/null 2>&1 || {
    echo "$SETTINGS is not valid JSON. Fix or move it before installing." >&2
    exit 1
  }
  CURRENT=$(cat "$SETTINGS")
else
  CURRENT='{}'
fi

if [ "$MODE" = "--uninstall" ]; then
  # Remove only entries this script added - identified by the _karaoke marker,
  # never by position - then drop any hook group left with no hooks in it.
  [ -f "$SETTINGS" ] || { echo "nothing to uninstall: $SETTINGS does not exist"; exit 0; }
  NEXT=$(printf '%s' "$CURRENT" | jq '
    .hooks |= (with_entries(
      .value |= (map(.hooks |= map(select(has("_karaoke") | not)))
                 | map(select((.hooks | length) > 0)))
    ) | with_entries(select((.value | length) > 0)))
    | if (.hooks | length) == 0 then del(.hooks) else . end
  ')
  cp "$SETTINGS" "$SETTINGS.bak"
  printf '%s\n' "$NEXT" > "$SETTINGS"
  echo "removed karaoke-narration hooks from $SETTINGS (backup: $SETTINGS.bak)"
  exit 0
fi

# Append rather than replace: another tool's Stop hook must survive this.
NEXT=$(printf '%s' "$CURRENT" | jq --argjson block "$BLOCK" '
  .hooks = ((.hooks // {}) as $h
    | reduce ($block | keys_unsorted[]) as $event ($h;
        .[$event] = ((.[$event] // []) + $block[$event])))
')

if [ "$MODE" != "--apply" ]; then
  echo "DRY RUN - nothing written. Target: $SETTINGS"
  echo
  echo "Resulting hooks section would be:"
  printf '%s\n' "$NEXT" | jq '.hooks'
  echo
  echo "Re-run with --apply to write it."
  exit 0
fi

mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak"
printf '%s\n' "$NEXT" > "$SETTINGS"
echo "installed into $SETTINGS$([ -f "$SETTINGS.bak" ] && echo " (backup: $SETTINGS.bak)")"
echo
echo "Narration is still OFF. It stays inert until you enable it:"
echo "  mkdir -p ~/.karaoke-narration && touch ~/.karaoke-narration/enabled"
echo "or run /karaoke on inside Claude Code. Restart the session to load the hooks."
