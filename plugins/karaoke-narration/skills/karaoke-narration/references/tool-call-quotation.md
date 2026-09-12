---
type: Incident Reference
title: Step Lines Are Quotations, Not Summaries
description: Blockquote step lines describing tool calls must be copied character-for-character from the actual description strings, not recalled or summarized afterward — a five-step turn once silently shipped as four.
tags: [step-lines, verbatim, tool-calls, audit]
---

# Step lines are quotations, not summaries

Blockquote step lines must be **copied character-for-character from the actual
tool-call description strings**, one line per call, in call order. They are
quotations, not a summary written afterwards.

This has failed in practice, and the failure is invisible without side-by-side
comparison: a five-step turn shipped as four, with two lines silently truncated
("omitting fields that weren't supplied" lost "rather than inventing defaults")
and the final two calls merged into one invented line. Everything still read
plausibly, and `display_text_is_verbatim` still passed - because that gate only
proves the HTML matches the input file, never that the input file matches
reality.

**Every step group, not just the first.** A turn interleaves several groups
between paragraphs, and each belongs at its own position - the code already
supports multiple blockquote blocks, so collapsing them into one block at the top
is a choice, and the wrong one. Groups that occur after the build are still
knowable: their description strings are decided before the calls are made, so
write them into the file first and then make the calls with exactly those
strings. `present_files` has no description field; the app labels it
"Presented N files", so use that.

Tool *results* are not captured at all - only descriptions. The app can expand any
step to reveal its output, and that output is where the actual evidence lives.
This is a known, unclosed gap.

There is no automated check for this. The tool-call descriptions are not written
to disk, so nothing can diff them. The only safeguard is to copy each one rather
than recalling it, with the same discipline the response prose requires. If a
step line is being typed from memory, it is already wrong.
