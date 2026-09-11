---
type: Constraint Reference
title: Token Count Accuracy
description: Why input tokens are unrecoverable and output tokens are only an estimate, verified against Anthropic's own documentation.
tags: [tokens, tokenizer, count_tokens, accuracy]
---

# Token count accuracy

## No published tokenizer for current models

A Claude tokenizer WAS reverse-engineered and published in 2023 (BPE, ~65K
vocabulary, ~70% overlap with GPT-4's `cl100k_base`) and is available via
HuggingFace and a few GitHub wrappers. It does not apply here: Anthropic's own
docs state Opus 5, Sonnet 5, and later models use a newer tokenizer producing
~30% more tokens than that older one for the same text. There is no published
vocabulary or formula for the current tokenizer. The only authoritative source
is the live `count_tokens` API endpoint - a service call, not a downloadable spec.

## Output: estimated locally, exact on request

The local estimate (`o200k_base`, OpenAI's tokenizer) is doubly approximate on
current Claude models: wrong vendor, and likely biased ~30% low given the
newer-tokenizer finding above. Whenever the output figure is only an estimate,
`build_karaoke.py` writes `<out>.source.txt` (the literal response text) and
`<out>.count_tokens.py` (a ready call to the real `count_tokens` endpoint)
alongside the audio. Running it with an API key returns the exact figure, which
feeds back in via `--tokens-out`.

## Input: not recoverable by any means

Input tokens require the full serialized request - system prompt, tool schemas,
conversation history, images - none of which the model producing a response can
see. This is not a tooling gap that a script can close; the information does not
exist on this side of the API boundary. `--tokens-in` remains the only path, and
only works for someone with the actual API response object in hand.

## claude.ai exposes neither

Confirmed via search: the consumer product shows only an aggregate weekly usage
percentage, no per-message token count in either direction. Both `--tokens-in`
and `--tokens-out` are fillable only when calling the API directly.
