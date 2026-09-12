---
type: Incident Reference
title: Model Attribution — Name Is Checkable, Mode Is Not
description: Why model name/ID must be re-derived every build while attribution mode can never be inferred, learned from five consecutive builds shipping a stale model name.
tags: [model-attribution, byline, verification]
---

# Model attribution: name is checkable, mode is not

Model **name and ID** can be verified against Claude's own system prompt at build
time ("This iteration of Claude is Claude Sonnet 5" is stated there directly) -
there is no excuse for a stale or hardcoded value. This failed in practice: five
consecutive builds shipped "Claude Opus 5" carried forward from one old
screenshot, never rechecked, while the actual model producing later turns had
changed. Re-derive it every build; never reuse a prior turn's value.

**Mode** (Max, High, whatever effort level is selected) is different in kind, not
just in reliability. It is a UI setting with no equivalent in the model's own
context - there is no signal to check, ever, from any turn. Every mode value
shipped so far was inferred from a screenshot of the compose bar, which is
observation of the person's screen, not self-knowledge. Treat it exactly like
`--tokens-in`: supplied and exact, or blank. Never inferred, never carried
forward.
