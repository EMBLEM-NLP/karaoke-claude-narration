#!/usr/bin/env python3
"""
pack_standalone.py - Embed an mp3 + timing.json pair into ONE self-contained
player HTML file (base64 audio, inline JSON). No fetch, no file picker, no
sibling-file dependency.

Why this exists: player.html's file-loader / ?src= fetch path assumes it can
either read local files via a picker or fetch a sibling file over HTTP. Neither
holds inside claude.ai's sandboxed artifact preview - the iframe can't fetch
sibling output files, and the file <input> only sees files already on the
device, not ones just generated server-side. Embedding the data removes the
loading step entirely, which is what an in-chat review artifact actually needs.

Usage:
  python3 scripts/pack_standalone.py out/narration.mp3 out/narration.timing.json -o out/narration_standalone.html
"""
import argparse, base64, html, json, os, re, sys

TEMPLATE_MARKER_AUDIO = "__AUDIO_BASE64_DATA_URI__"
TEMPLATE_MARKER_TIMING = "__TIMING_JSON_INLINE__"
TEMPLATE_MARKER_LABEL = "__SOURCE_LABEL__"
TEMPLATE_MARKER_TRANSCRIPT = "__STATIC_TRANSCRIPT_FALLBACK__"

def html_escape(s):
    """Escape a user-supplied title. It lands inside <title>, and an unescaped
    '<' there would truncate the element and swallow the rest of the head."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _block_text(block):
    text = block.get("text")
    if text:
        return text
    sentences = block.get("sentences") or []
    return " ".join(s.get("text", "") for s in sentences).strip()


def static_transcript_html(timing):
    """Render a no-JS transcript so file previews are never empty players."""
    blocks = timing.get("blocks") or []
    if not blocks:
        text = timing.get("source_text") or " ".join(
            str(w.get("w", "")) for w in timing.get("words", [])
        )
        return f'<div class="blk p"><div>{html.escape(text)}</div></div>'

    out = []
    for block in blocks:
        text = _block_text(block)
        if not text:
            continue
        escaped = html.escape(text)
        kind = block.get("type")
        if kind == "heading":
            level = min(max(int(block.get("level") or 1), 1), 3)
            out.append(f'<div class="blk h{level}">{escaped}</div>')
        elif kind == "bullet":
            out.append(
                '<div class="blk bullet">'
                '<span class="marker">&bull;</span>'
                f"<div>{escaped}</div>"
                "</div>"
            )
        elif kind == "code":
            out.append(f'<div class="blk code">{escaped}</div>')
        else:
            out.append(f'<div class="blk p"><div>{escaped}</div></div>')

    if out:
        return "\n".join(out)
    return '<div class="blk p"><div></div></div>'


def to_artifact_fragment(html):
    """Strip the outer document so the Artifact host can supply its own.

    Keeps <title> (the artifact's name), the whole <style> block, and the body's
    inner content including the <script>. Everything the player needs is already
    inline - base64 audio, timing JSON - so nothing external is referenced and the
    artifact CSP is satisfied without changes.

    Fails loudly rather than silently emitting a broken page: a fragment that
    quietly lost its script would reproduce the exact symptom this mode exists to
    fix, and would be indistinguishable from it on the reader's screen."""
    parts = []
    m = re.search(r"<title>.*?</title>", html, re.S)
    if m:
        parts.append(m.group(0))
    m = re.search(r"<style>.*?</style>", html, re.S)
    if not m:
        sys.exit("[pack_standalone] --artifact: no <style> block found in the template")
    parts.append(m.group(0))
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not m:
        sys.exit("[pack_standalone] --artifact: no <body> found in the template")
    body = m.group(1)
    if "<script>" not in body:
        sys.exit("[pack_standalone] --artifact: body carries no <script>; the player "
                 "would be inert, which is the failure this mode exists to prevent")
    parts.append(body.strip())
    return "\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Pack mp3 + timing.json into one self-contained player HTML.")
    ap.add_argument("mp3", help="path to the narration mp3")
    ap.add_argument("timing", help="path to the matching timing.json")
    ap.add_argument("-o", "--out", required=True, help="output standalone .html path")
    ap.add_argument("--template", default=os.path.join(os.path.dirname(__file__), "player_embed_template.html"))
    ap.add_argument("--artifact", action="store_true",
                    help="emit a fragment for the Artifact tool instead of a whole document. "
                         "REQUIRED for claude.ai delivery: a file ATTACHMENT is rendered by a "
                         "static preview that never executes JavaScript, and this player is "
                         "entirely JavaScript - transcript, decode, playback - so attached it "
                         "shows only its own empty shell with the markup's initial "
                         "'decoding audio...' and no transcript. Observed on iOS at both 167 KB "
                         "and 1.1 MB, while the identical file was perfect in Chromium. An "
                         "artifact runs scripts; the host supplies doctype/head/body, so those "
                         "wrappers are stripped here.")
    ap.add_argument("--title", default=None,
                    help="page title. Defaults to 'Chat response - <mp3 stem>', which as an "
                         "artifact name reads as 'Chat response - response': generic and "
                         "redundant, and indistinguishable from every other narration in a "
                         "gallery. Pass something specific to the turn.")
    args = ap.parse_args()

    # A data: URI lets static/no-JS previews fall back to the browser's native
    # audio controls. The Web Audio player strips the prefix before decoding.
    with open(args.mp3, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    data_uri = "data:audio/mpeg;base64," + b64

    with open(args.timing, encoding="utf-8") as f:
        timing = json.load(f)  # validate it parses before embedding

    with open(args.template, encoding="utf-8") as f:
        html = f.read()

    label = os.path.splitext(os.path.basename(args.mp3))[0]
    html = html.replace(TEMPLATE_MARKER_AUDIO, data_uri)
    html = html.replace(TEMPLATE_MARKER_TIMING, json.dumps(timing))
    html = html.replace(TEMPLATE_MARKER_LABEL, label)
    html = html.replace(TEMPLATE_MARKER_TRANSCRIPT, static_transcript_html(timing))

    if args.title:
        html = re.sub(r"<title>.*?</title>",
                      "<title>" + html_escape(args.title) + "</title>", html, count=1, flags=re.S)

    if args.artifact:
        html = to_artifact_fragment(html)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(args.out) / 1024
    print(f"[pack_standalone] wrote {args.out} ({size_kb:.0f} KB, {len(timing['words'])} words, "
          f"{timing['duration']:.1f}s audio)")
    # Empirically observed, not a documented platform limit: a ~2MB standalone
    # HTML loaded fine in the claude.ai mobile artifact preview; a ~5.7MB one
    # failed to load at all ("Couldn't load file"), no error detail given. No
    # Anthropic doc specifies an exact threshold for this rendering path, so
    # these are warning bands with margin, not asserted facts - if you hit this,
    # the fix that worked was lowering --bitrate, not shortening the script.
    if size_kb > 4000:
        print(f"[pack_standalone] WARNING: {size_kb:.0f} KB is in the range where the artifact "
              f"preview failed to load entirely in earlier testing. Re-run with a lower --bitrate "
              f"on build_karaoke.py before shipping this.")
    elif size_kb > 2500:
        print(f"[pack_standalone] NOTE: {size_kb:.0f} KB — untested territory between a size that "
              f"worked and one that didn't. Worth confirming it actually loads before sharing.")

if __name__ == "__main__":
    main()
