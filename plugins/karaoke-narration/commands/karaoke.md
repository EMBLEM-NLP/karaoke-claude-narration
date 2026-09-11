---
description: Turn per-turn narration on or off, or show its status
---

Toggle automatic narration of each assistant response.

The Stop hook is installed but inert until enabled, because synthesizing speech
on every turn is slow and wasteful on short replies. This command flips the flag
file the hook checks.

Usage: `/karaoke on`, `/karaoke off`, `/karaoke status`

Run the matching command for the argument the user supplied ($ARGUMENTS):

- **on** — `mkdir -p ~/.karaoke-narration && touch ~/.karaoke-narration/enabled`
  then confirm narration is active from the next turn onward.
- **off** — `rm -f ~/.karaoke-narration/enabled` then confirm it is inactive.
- **status** — check whether `~/.karaoke-narration/enabled` exists and show the
  last few lines of `~/.karaoke-narration/hook.log` so the user can see whether
  the hook is actually firing, and why turns were skipped if they were.

If no argument was given, show status.
