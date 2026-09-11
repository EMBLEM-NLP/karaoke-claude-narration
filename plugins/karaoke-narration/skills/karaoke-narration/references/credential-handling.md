---
type: Constraint Reference
title: Credential Handling for Agent Tooling
description: Why encrypting a secret into a conversation does not protect it, and the three patterns that do work.
tags: [credentials, security, oauth, mcp, totp, threat-model]
---

# Credential handling

## Encrypting a secret into the transcript does not protect it

The proposal: encrypt a password so it can be handed to the model safely.

The flaw is structural, not cryptographic. To *use* a credential the model needs
it in plaintext, so the decryption key must travel the same channel as the
ciphertext. Both then sit in the transcript, and so, transitively, does the
plaintext. Encryption defends against a party that lacks the key; here the party
that must not have it and the party that must have it are the same channel.
A stronger cipher changes nothing.

This holds for every variant that keeps the secret flowing through the
conversation: passphrase-wrapped, key-derivation-based, split across messages.
Splitting is the most tempting and the least sound - both halves are in the same
transcript, so it is obfuscation, not encryption.

## TOTP seeds are worse than passwords

Two-factor codes cannot be delegated without destroying the factor:

- **Live relay** - codes expire in ~30s, so every action becomes a hand-off, and
  the model is still authenticating *as* the user.
- **Sharing the seed** - a seed is not a code; it generates all future codes.
  Handing it over converts "something you have" into "something the transcript
  has". This is strictly worse than sharing the password alone, because it
  removes the control that would otherwise bound the damage.

## What actually works

| Pattern | Mechanism | Why it holds |
|---|---|---|
| OAuth / MCP connectors | User authorises; platform holds a scoped token | Revocable, scoped, expiring, never transits the transcript |
| Local execution | Tool runs on the user's machine, reads the OS keychain | Credential never leaves the host |
| Scoped short-lived tokens | Read-only PAT for one repo, revoked after use | Blast radius bounded even if exposed |

The common thread: the credential either never reaches the model, or what reaches
it is narrow and revocable.

## This project already does it correctly

`gh-projects-mcp` requires local `gh` CLI auth and a CDP attach to the user's own
logged-in browser. `cod-cookie-jar` reads only from a debugging endpoint the
operator enabled themselves, with no on-disk decryption. Both keep the credential
on the user's machine by construction. That is the pattern - not an obstacle to
work around.

## And it would not solve the problem it was proposed for

The motivating goal was ground truth for the in-flight turn. No credential
achieves that: a turn enters any store when it *ends*, so a fetch returns
everything except the turn being written. That is a temporal property, not an
access-control one. See `token-accuracy.md` for the same distinction applied to
input tokens.
