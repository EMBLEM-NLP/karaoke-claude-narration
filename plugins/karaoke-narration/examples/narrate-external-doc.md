# Narrating a generated doc from another repo

Worked example, using gh-projects-mcp's generated tool inventory
(`docs/TOOL_INVENTORY.md`, produced by `npm run docs:tools` in that repo — see
[gh-projects-mcp#docs/TOOL_INVENTORY.md](https://github.com/EMBLEM-NLP/gh-projects-mcp/blob/main/docs/TOOL_INVENTORY.md))
as the doc being narrated. The same steps apply to any generated reference doc
you want turned into a karaoke player.

There are two separate features here — don't conflate them:

- **`/karaoke on`** makes the `Stop` hook narrate *every future assistant reply*
  automatically, turn by turn. It only ever narrates what Claude actually says
  next; it cannot narrate a doc that already exists on disk. See the main
  [SKILL.md](../skills/karaoke-narration/SKILL.md#automatic-per-turn-narration-is-a-hook-not-this-skill).
- **`scripts/narrate_response.sh`** narrates an existing file (or set of files)
  as one manually-triggered "turn." This is what you want for a standalone doc
  like a tool inventory.

## Why you can't just point it at the whole file

`narrate_response.sh` treats whatever files you pass it as the verbatim
ground truth — no hand-written summary in between — and the pipeline enforces
a hard ceiling of roughly 800 words per turn (`check_reader.py` derives the
phone playback limit at ~884). A generated inventory covering dozens of tools
will usually blow past that. Check first:

```bash
wc -w /path/to/gh-projects-mcp/docs/TOOL_INVENTORY.md
```

If it's over ~800 words (a 45-tool inventory is roughly 1,400), split by
section instead of narrating it in one shot — one turn per category, or a
short hand-authored overview turn plus separate deep-dive turns. Narrating a
*summary* of the doc instead of the doc itself is exactly what rule 1 in
SKILL.md exists to prevent, so split the real content rather than compressing it.

## Splitting a generated doc into per-turn slices

`docs/TOOL_INVENTORY.md` is organized under `## <Category>` headings (Auth &
diagnostics, Projects, Project fields, …). Cut it into one file per category
first, then narrate each as its own turn:

```bash
cd /path/to/gh-projects-mcp
awk '/^## /{n++} {print > ("/tmp/tool-inventory-part-" n ".md")}' docs/TOOL_INVENTORY.md
```

Then, from this plugin's root, narrate one slice as a turn:

```bash
scripts/narrate_response.sh turns/gh-tool-inventory-01 "gh-projects-mcp: Auth & diagnostics, Projects" \
  "Tool inventory:/tmp/tool-inventory-part-1.md"
```

Repeat with a fresh, incrementing turn directory
(`turns/gh-tool-inventory-02`, `...-03`, …) for each remaining slice — never
reuse a directory or republish over an existing artifact URL (SKILL.md rules
2 and 4): each slice is its own permanent link.

## What you get

Each invocation produces `turns/gh-tool-inventory-NN/turn.html` — a packed,
standalone karaoke player (word-highlighted, tap-to-seek) you can send with
`SendUserFile` or publish as an Artifact. The QC gate in
`narrate_response.sh` (word count, table/URL lint, verbatim-source check,
reader simulation) runs on every slice before it's considered publishable, so
a slice that fails one of those checks tells you to fix the source doc
(remove a table, shorten the section) rather than shipping broken narration.

## Keeping this current

If `gh-projects-mcp` regenerates its inventory (`npm run contract:write &&
npm run docs:tools`) and the section boundaries change, re-run the `awk` split
above — it's derived from the live `## ` headings, not a fixed list, so it
tracks the doc automatically.
