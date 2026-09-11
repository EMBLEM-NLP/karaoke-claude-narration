#!/usr/bin/env python3
"""ground_truth_from_export.py - extract a turn's text from Anthropic's official
conversation export, for use with build_karaoke.py --verify-against.

WHY THIS AND NOT COOKIE-BASED SCRAPING
The export is the sanctioned path: Anthropic hands you the data, so there is no
session cookie to leak into a transcript, no undocumented endpoint, no edge
control to evade, and no expiry treadmill. A cookie-based fetch would deliver
strictly less for strictly more risk - and would still miss the in-flight turn,
because a turn does not exist in any export or API until it is finished.

Scope, stated plainly: this gives ground truth for COMPLETED turns only. The
current turn is unreachable by any fetch. In Claude Code that gap is closed by
the Stop hook's last_assistant_message; on claude.ai it is not closable.

Usage:
  ground_truth_from_export.py export.json --conversation-name "..." --last
  ground_truth_from_export.py export.json --conversation-name "..." --index -2
"""
import argparse, json, sys


def assistant_turns(convo):
    out = []
    for m in convo.get("chat_messages", convo.get("messages", [])):
        if m.get("sender") != "assistant" and m.get("role") != "assistant":
            continue
        text = m.get("text") or ""
        if not text:
            parts = m.get("content") or []
            text = "\n\n".join(
                c.get("text", "") for c in parts
                if isinstance(c, dict) and c.get("type") == "text"
            )
        if text.strip():
            out.append(text)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--conversation-name", default=None,
                    help="substring match on the conversation title")
    ap.add_argument("--last", action="store_true", help="most recent assistant turn")
    ap.add_argument("--index", type=int, default=None,
                    help="assistant-turn index; negative counts from the end")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    data = json.load(open(a.export, encoding="utf-8"))
    convos = data if isinstance(data, list) else [data]
    if a.conversation_name:
        needle = a.conversation_name.lower()
        convos = [c for c in convos if needle in (c.get("name") or "").lower()]
    if not convos:
        sys.exit("no conversation matched")

    turns = assistant_turns(convos[0])
    if not turns:
        sys.exit("no assistant turns found")

    if a.index is not None:
        text = turns[a.index]
    elif a.last:
        text = turns[-1]
    else:
        for i, t in enumerate(turns):
            print(f"[{i}] {t[:90]!r}")
        return

    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
        print(f"wrote {len(text.split())} words -> {a.out}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
