#!/usr/bin/env python3
"""
build_karaoke.py - Markdown chat response -> narrated MP3 + verbatim structural
timing manifest for a karaoke (sentence-underline, word-highlight) review player.

THREE LAYERS, DELIBERATELY SEPARATE:
  1. SOURCE  - the raw markdown exactly as written.
  2. DISPLAY - source with inline markdown markers stripped but structure and
               styling preserved (**bold** renders bold, not as asterisks).
               This is what you READ.
  3. SPOKEN  - display with acronym substitutions applied so espeak says it right
               ("MCP" -> "M C P"). This is what gets SYNTHESIZED and aligned.
  All three differ. An earlier version collapsed them, so a transcript of
  "The **MCP** server returns JSON" was rendered as "The M C P server returns
  jason" - unusable for reviewing what was actually written.

STRUCTURE IS PRESERVED. A real chat response is markdown: headings, bullets,
paragraphs, code fences. Normalizing all whitespace flattens it into one wall of
text, which defeats the point of a review lens. Blocks are parsed first, and
sentences are split within each block.

CODE FENCES ARE RENDERED BUT NOT NARRATED. Reading code aloud is useless, and
narration-audio's SKILL.md notes long code-heavy replies should be summarized
rather than read verbatim. Code blocks appear in the transcript, marked, with no
timings attached.

Alignment: sentences come from the source, so each sentence's clip offset is known
with zero ASR. Each display token's substitution expansion count is tracked, so
spoken-token timings map back onto verbatim tokens by construction. faster-whisper
runs ONLY on short isolated per-sentence clips - narration-audio documents that
full-file Whisper on synthetic TTS silently drops long spans.

Exit codes:  0 = pass,  2 = QC gate failed (do not ship).
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, tempfile, wave, difflib
import numpy as np

HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICES = {
    "en_US-hfc_female-medium": ("en/en_US/hfc_female/medium", "clear US female, default"),
    "en_US-lessac-high":       ("en/en_US/lessac/high",       "US female, higher fidelity"),
    "en_US-ryan-high":         ("en/en_US/ryan/high",         "US male, higher fidelity"),
}
DEFAULT_SUBS = {
    r"\bMCP\b": "M C P", r"\bAPI\b": "A P I", r"\bSQL\b": "sequel",
    r"\bJSON\b": "jason", r"\bYAML\b": "yammel", r"\bGraphQL\b": "Graph Q L",
    r"\bCLI\b": "command line interface", r"\bURL\b": "U R L",
    r"\bCSP\b": "C S P", r"\bHTML\b": "H T M L", r"\bTTS\b": "T T S",
    r"\bASR\b": "A S R", r"\bQC\b": "Q C", r"\bCI\b": "C I",
    r"read-me": "read me", r"\bREADME\b": "read me",
}
MIN_WORD_DUR = 0.08


def need(tool):
    if shutil.which(tool) is None:
        sys.exit(f"[karaoke] required tool not found on PATH: {tool}")

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)

def db_to_lin(db):
    return 10 ** (db / 20.0)

def ensure_voice(voice, voices_dir):
    if os.path.isfile(voice):
        return voice
    onnx = os.path.join(voices_dir, voice + ".onnx")
    if os.path.isfile(onnx):
        return onnx
    if voice not in VOICES:
        sys.exit(f"[karaoke] unknown voice '{voice}'. Known: {', '.join(VOICES)}")
    need("curl")
    os.makedirs(voices_dir, exist_ok=True)
    sub = VOICES[voice][0]
    print(f"[karaoke] downloading voice {voice} ...")
    for ext in (".onnx", ".onnx.json"):
        run(["curl", "-sL", "-o", onnx.replace(".onnx", ext), f"{HF}/{sub}/{voice}{ext}"])
    return onnx


# ---------- layer 1 -> 2 : markdown structure and inline cleanup ----------

def parse_blocks(text):
    """Split markdown into structural blocks, preserving layout.
    Returns [{"type", "level", "raw", "narrated"}]."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):                       # code fence
            fence, i = [line], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                fence.append(lines[i]); i += 1
            if i < len(lines):
                fence.append(lines[i]); i += 1
            body = "\n".join(fence[1:-1]) if len(fence) > 2 else ""
            blocks.append({"type": "code", "level": 0, "raw": body, "narrated": False})
            continue
        if not line.strip():
            i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)                 # heading
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)),
                           "raw": m.group(2).strip(), "narrated": True})
            i += 1; continue
        m = re.match(r"^\s*>\s?(.*)$", line)                     # blockquote
        if m:
            buf = [m.group(1).strip()]; i += 1
            while i < len(lines) and re.match(r"^\s*>", lines[i]):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]).strip()); i += 1
            # Each line is one step. Kept as discrete items rather than joined,
            # so the player can number them - and without appending invented
            # punctuation, which would break verbatim fidelity.
            blocks.append({"type": "quote", "level": 0, "items": buf,
                           "raw": "\n".join(buf).strip(), "narrated": True})
            continue
        m = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$", line)       # list item
        if m:
            buf = [m.group(1).strip()]; i += 1
            while i < len(lines) and lines[i].strip() and \
                  not re.match(r"^\s*(?:[-*+]|\d+\.)\s+", lines[i]) and \
                  not lines[i].strip().startswith(("#", "```")):
                buf.append(lines[i].strip()); i += 1
            blocks.append({"type": "bullet", "level": 0,
                           "raw": " ".join(buf), "narrated": True})
            continue
        buf = [line.strip()]; i += 1                             # paragraph
        while i < len(lines) and lines[i].strip() and \
              not re.match(r"^\s*(?:[-*+]|\d+\.)\s+", lines[i]) and \
              not lines[i].strip().startswith(("#", "```")):
            buf.append(lines[i].strip()); i += 1
        blocks.append({"type": "paragraph", "level": 0,
                       "raw": " ".join(buf), "narrated": True})
    return blocks


def _strip_inline(t):
    """Remove inline markdown markers, leaving the words themselves untouched.

    Module-level rather than nested so other tools in this package compare text
    the SAME way rather than each carrying its own copy of these regexes - a
    hand-maintained copy is a third text that can drift from the ones it claims
    to represent. scripts/audit_published.py imports this.
    """
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = t.replace("**", "").replace("`", "")
    t = re.sub(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def clean_token(tok):
    """Strip inline markdown from one token. Returns (display_text, [styles]).
    Token count is preserved 1:1 so display and source stay aligned."""
    styles, t = set(), tok
    m = re.fullmatch(r"\[([^\]]+)\]\([^)]*\)([^\w\s]*)", t)      # [text](url)
    if m:
        t = m.group(1) + (m.group(2) or ""); styles.add("link")
    if "`" in t:
        styles.add("code"); t = t.replace("`", "")
    if "**" in t:
        styles.add("bold"); t = t.replace("**", "")
    if re.search(r"(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", t):
        styles.add("italic"); t = re.sub(r"\*", "", t)
    if re.fullmatch(r"_[^_]+_[^\w]*", t):
        styles.add("italic"); t = t.replace("_", "")
    return (t if t else tok), sorted(styles)


def split_sentences(text):
    text = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?]) ", text)
            if s.strip() and re.search(r"[A-Za-z0-9]", s)]


# ---------- layer 2 -> 3 : speech ----------

def expand_token(disp, enabled):
    if not enabled:
        return [disp]
    s = disp
    for pat, rep in DEFAULT_SUBS.items():
        s = re.sub(pat, rep, s)
    parts = s.split()
    return parts if parts else [disp]

def build_spoken(sentence, enabled):
    """(spoken_text, display_tokens, styles, expansion_counts, spoken_tokens) for
    one sentence.

    Punctuation-only tokens (a standalone em dash, a bare quote) are KEPT as
    display tokens with an expansion count of 0: shown, never spoken. Dropping
    them silently broke the core promise of this tool - a 344-word turn rendered
    with 8 em dashes missing, so the transcript was not actually verbatim while
    claiming to be. count==0 is handled in aggregate_to_display()."""
    disp_tokens, styles, counts, spoken = [], [], [], []
    for raw_tok in sentence.split():
        d, st = clean_token(raw_tok)
        if not re.search(r"[A-Za-z0-9]", d):
            # No speakable content, but it IS part of the written text.
            disp_tokens.append(d); styles.append(st); counts.append(0)
            continue
        exp = expand_token(d, enabled)
        disp_tokens.append(d); styles.append(st)
        counts.append(len(exp)); spoken.extend(exp)
    return " ".join(spoken), disp_tokens, styles, counts, spoken


# ---------- synthesis ----------

def piper_synth(text, path, model, ls):
    base = ["piper", "-m", model, "--length_scale", str(ls), "-f", path]
    try:
        run(base + ["--", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(path) and os.path.getsize(path) > 44:
            return
    except subprocess.CalledProcessError:
        pass
    run(base, input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def load_i16(path):
    w = wave.open(path, "rb")
    return w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

def distortion_pct(a):
    x = a.astype(np.float32) / 32768.0
    return float((np.abs(np.diff(x)) > 0.5).mean() * 100.0) if len(x) > 1 else 0.0

def synth_qc(text, model, ls, sr, tmp, tag, thresh=2.0, depth=0):
    """Synthesize; recursively re-split on distortion. Ported from narrate.py -
    detecting distortion without repairing it was a regression."""
    if not re.search(r"[A-Za-z0-9]", text):
        return np.zeros(int(0.05 * sr), dtype=np.int16), False
    p = os.path.join(tmp, f"seg_{tag}.wav")
    try:
        piper_synth(text, p, model, ls)
    except subprocess.CalledProcessError:
        try:
            piper_synth(text, p, model, ls)
        except subprocess.CalledProcessError:
            return np.zeros(int(0.05 * sr), dtype=np.int16), False
    _, a = load_i16(p)
    if distortion_pct(a) <= thresh or depth >= 2:
        return a, False
    parts = ([x.strip() for x in re.split(r",\s*", text) if x.strip()] if depth == 0
             else text.split())
    if len(parts) < 2:
        return a, False
    gap = np.zeros(int(0.06 * sr), dtype=np.int16)
    out = []
    for k, pp in enumerate(parts):
        suffix = "," if (depth == 0 and k < len(parts) - 1) else ""
        seg, _ = synth_qc(pp + suffix, model, ls, sr, tmp, f"{tag}_{k}", thresh, depth + 1)
        out += [seg, gap]
    return np.concatenate(out), True


# ---------- alignment ----------

def asr_spans(wmodel, wav_path, spoken_text, debug=False, debug_ctx=""):
    """Word-level ASR on one isolated sentence clip.

    beam_size=5, NO initial_prompt. Investigated after the fallback rate hit
    10/13 sentences on a real response (see references/whisper-tts-reliability.md
    for the full comparison). Root cause was NOT sentence complexity as first
    guessed - it was greedy decoding (beam_size=1) combined with passing the
    known text as initial_prompt, which on Piper's flat, breath-less prosody
    regularly made Whisper return zero segments, truncate after 3-4 words, or
    loop-repeat a phrase. Empirically, across four real failing sentences,
    beam_size=5 with NO prompt recovered usable output in every case;
    beam_size=5 WITH a prompt did not, and in one case still returned nothing.

    This is a substantial improvement, not a fix: a long, acronym-dense
    sentence (~38 tokens) still degraded even at beam_size=10. The proportional
    fallback in map_to_display() is load-bearing, not a stopgap - keep it. The
    spoken_text parameter is threaded through unused now (kept for the debug
    label and call-site symmetry); rendering it as initial_prompt is exactly
    what made this worse. """
    segments, info = wmodel.transcribe(
        wav_path, word_timestamps=True, language="en",
        vad_filter=False, beam_size=5, temperature=0.0)
    seg_list = list(segments)   # faster-whisper's segments generator is lazy; materialize once
    words = [(float(w.start), float(w.end), w.word.strip())
             for seg in seg_list for w in (seg.words or []) if w.word.strip()]
    if debug:
        clip_dur = None
        try:
            sr_dbg, a_dbg = load_i16(wav_path)
            clip_dur = len(a_dbg) / sr_dbg
        except Exception:
            pass
        print(f"\n[debug] {debug_ctx}")
        print(f"[debug]   clip duration        : {clip_dur}")
        print(f"[debug]   whisper language/prob : {getattr(info, 'language', '?')} "
              f"{getattr(info, 'language_probability', '?')}")
        print(f"[debug]   segments returned     : {len(seg_list)}")
        print(f"[debug]   words returned        : {len(words)}  {[w[2] for w in words]}")
    return words   # (start, end, text) - text is needed for fuzzy alignment now

def normalize_for_match(tok):
    """Strip leading/trailing punctuation and case for matching purposes only -
    timing doesn't care whether Whisper wrote 'cause,' or 'cause', or normalized
    a semicolon to a period."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", tok.lower())

def align_spoken_tokens(expected_spoken, asr_words, clip_dur):
    """Map ASR timings onto the EXPECTED spoken-token sequence via fuzzy sequence
    alignment, rather than requiring an exact token-count match.

    Why: the original design discarded ALL of a sentence's ASR timing the moment
    the returned count didn't exactly equal the expected count - so a single
    misrecognized word ("highlighted" heard as "translated") threw away 22 good
    timings along with the 1 bad one. Whisper on Piper's flat TTS prosody rarely
    returns an exact match (see references/whisper-tts-reliability.md), so that
    made whole-sentence proportional fallback the common case, not the exception.

    difflib finds the actual matching runs between what was expected and what
    Whisper heard; only the genuinely unmatched stretches get interpolated
    between their nearest real neighbors (or extrapolated at a sentence's very
    edges), so one bad word costs one word, not the whole sentence.

    Returns (spoken_spans, match_fraction) where spoken_spans has exactly
    len(expected_spoken) entries and match_fraction is real diagnostic
    information, not a boolean - report it, don't collapse it.
    """
    n = len(expected_spoken)
    if n == 0:
        return [], 1.0
    exp_norm = [normalize_for_match(t) for t in expected_spoken]
    asr_norm = [normalize_for_match(w[2]) for w in asr_words]

    spans = [None] * n
    if asr_norm:
        sm = difflib.SequenceMatcher(None, exp_norm, asr_norm, autojunk=False)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                spans[blk.a + k] = (asr_words[blk.b + k][0], asr_words[blk.b + k][1])

    matched = sum(1 for x in spans if x is not None)
    match_fraction = matched / n

    i = 0
    while i < n:
        if spans[i] is not None:
            i += 1; continue
        j = i
        while j < n and spans[j] is None:
            j += 1
        left = spans[i - 1][1] if i > 0 else 0.0
        right = spans[j][0] if j < n else clip_dur
        step = (right - left) / (j - i) if j > i else 0.0
        for k in range(i, j):
            spans[k] = (left + step * (k - i), left + step * (k - i + 1))
        i = j
    return spans, match_fraction

def aggregate_to_display(spoken_spans, counts):
    """Fold spoken-subtoken spans back onto display/source tokens via each
    token's expansion count (e.g. 'MCP' -> 3 spoken subtokens -> 1 display span
    covering all three).

    count == 0 means a punctuation-only display token that is shown but never
    spoken. It gets the instant between its neighbours - which is semantically
    right, since an em dash IS the pause. The global monotonic sweep afterwards
    widens it to the minimum tappable duration."""
    out, cur = [], 0
    for c in counts:
        if c == 0:
            if cur > 0 and cur - 1 < len(spoken_spans):
                t = spoken_spans[cur - 1][1]
            elif spoken_spans:
                t = spoken_spans[0][0]
            else:
                t = 0.0
            out.append((t, t))
            continue
        chunk = spoken_spans[cur:cur + c]
        if not chunk:                     # defensive: ran out of spans
            t = out[-1][1] if out else 0.0
            out.append((t, t)); continue
        out.append((chunk[0][0], chunk[-1][1]))
        cur += c
    return out

def enforce_monotonic_min_duration(flat_words, min_dur):
    """Single forward sweep guaranteeing monotonicity, no overlap, AND a minimum
    duration together, in one pass - not each as an independent per-word check.

    A per-word floor applied in isolation (raise this word's end if it's too
    short) can't see whether that pushes past the NEXT word's un-floored start.
    That's exactly what broke here: two real ASR anchors close in time with
    several unmatched tokens interpolated between them produces a local step
    under min_dur; flooring each independently created real overlaps that the
    QC gate correctly caught. Mutates in place - flat_words and each sentence's
    words list share the same dict objects, so this also fixes the copies
    embedded in manifest['sentences'] without a second pass."""
    prev_end = 0.0
    for wd in flat_words:
        start = max(wd["start"], prev_end)
        end = max(wd["end"], start + min_dur)
        wd["start"], wd["end"] = round(start, 3), round(end, 3)
        prev_end = wd["end"]


def measure(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "ebur128=peak=true", "-f", "null", "-"],
                       stderr=subprocess.PIPE, text=True)
    I = re.findall(r"I:\s+(-?\d+\.?\d*)", r.stderr)
    TP = re.findall(r"Peak:\s+(-?\d+\.?\d*)", r.stderr)
    return (float(I[-1]) if I else None, float(TP[-1]) if TP else None)

def normalize(raw_wav, out_mp3, target, peak_db, bitrate):
    """Loudness-match, then guarantee true peak.

    Two separate problems. (1) LAME drops ~0.5-0.7 LU vs the source WAV, so the
    encoder sits inside the loudness measurement loop. (2) `alimiter` caps SAMPLE
    peak, but MP3 encoding reintroduces INTER-SAMPLE peaks, so a file limited to
    -2 dBFS can still measure above 0 dBTP once encoded - which is real clipping.
    The QC gate caught exactly this on a 98-second file that a 9-second test never
    exposed. So after loudness converges, the ceiling is walked down until the
    measured true peak of the actual MP3 is under target."""
    # Sample rate follows the bitrate, because it constrains it. MPEG-1 Layer III
    # at 44100 Hz cannot encode below 32 kbps, so LAME silently clamps: asking for
    # --bitrate 16k produced a byte-for-byte 32k file, and a 3-minute turn stayed
    # at ~1 MB when the whole point of lowering it was to fit a mobile reader.
    # Sub-32k needs MPEG-2 rates, which require <= 24000 Hz. Speech has nothing
    # above ~8 kHz that matters, so 22050 costs nothing audible here.
    try:
        kbps = int(str(bitrate).lower().rstrip("k") or 32)
    except ValueError:
        kbps = 32
    ar = "22050" if kbps < 32 else "44100"

    def encode(gain_db, ceiling_db):
        af = (f"volume={gain_db:.2f}dB,"
              f"alimiter=level=false:limit={db_to_lin(ceiling_db):.4f}")
        run(["ffmpeg", "-y", "-hide_banner", "-i", raw_wav, "-af", af,
             "-c:a", "libmp3lame", "-b:a", bitrate, "-ar", ar, out_mp3],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return measure(out_mp3)

    I_raw, _ = measure(raw_wav)
    gain = target - (I_raw if I_raw is not None else target)
    ceiling = peak_db
    I_out, TP_out = encode(gain, ceiling)
    for _ in range(3):                                   # loudness convergence
        if I_out is None or abs(I_out - target) <= 0.3:
            break
        gain += (target - I_out)
        I_out, TP_out = encode(gain, ceiling)
    for _ in range(4):                                   # true-peak safety
        if TP_out is None or TP_out <= peak_db + 0.5:
            break
        ceiling -= max(TP_out - peak_db, 0.5) + 0.3
        I_out, TP_out = encode(gain, ceiling)
    return I_out, TP_out


def main():
    ap = argparse.ArgumentParser(description="Markdown response -> narrated MP3 + timing manifest")
    ap.add_argument("input", nargs="+",
                    help="one or more .md/.txt files, or '-' for stdin. EACH FILE IS ONE TURN, "
                         "rendered as its own labeled, separately-navigable section. Pass turns in "
                         "order. Turn label comes from the filename stem unless --labels is given.")
    ap.add_argument("--labels", nargs="*", default=None,
                    help="explicit display label per input file, in the same order")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--voice", default="en_US-hfc_female-medium")
    # Absolute, cwd-independent. The old relative default ("voices") cached the
    # ~63MB model into whatever directory you happened to run from, which put
    # three copies on disk and once got one packaged into a release zip,
    # inflating it 35x. Shares the state dir the Stop hook already uses.
    ap.add_argument("--voices-dir", default=str(
        pathlib.Path(os.environ.get("KARAOKE_STATE_DIR",
                                    pathlib.Path.home() / ".karaoke-narration")) / "voices"))
    ap.add_argument("--rate", type=float, default=1.06)
    ap.add_argument("--gap", type=float, default=0.35)
    ap.add_argument("--block-gap", type=float, default=0.55,
                    help="extra pause between structural blocks")
    ap.add_argument("--lufs", type=float, default=-16.0)
    ap.add_argument("--peak", type=float, default=-2.0)
    ap.add_argument("--bitrate", default="32k",
                    help="mp3 bitrate. Default is low (32k mono) because output is spoken word, "
                         "not music, AND because the standalone player embeds this file as base64 - "
                         "a ~2MB HTML artifact loaded in the claude.ai mobile app; a ~5.7MB one did "
                         "not (empirically observed, not a documented platform limit - see "
                         "references/artifact-size-constraints.md). 32k mono holds -1 to -2 LUFS off "
                         "target on re-encode, well within normal variance, at roughly 1/4 the file "
                         "size of 128k. Values BELOW 32k switch LAME to MPEG-2 LSF at 22050 Hz "
                         "(MPEG-1 Layer III cannot go under 32k at 44.1 kHz) - a less-exercised "
                         "WebKit decode path than the default. It decoded on the test iPhone, but "
                         "prefer shorter turns over sub-32k bitrates when size matters.")
    ap.add_argument("--whisper-model", default="base")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--model", default=None,
                    help="display name of the model that produced the response, e.g. 'Claude Opus 5'")
    ap.add_argument("--model-id", default=None,
                    help="API model string, e.g. 'claude-opus-5'")
    ap.add_argument("--mode", default=None,
                    help="effort/reasoning mode, e.g. 'Max', 'High'")
    ap.add_argument("--tokens-in", type=int, default=None,
                    help="EXACT input/prompt token count from the API response. There is no local "
                         "fallback for this: the serialized prompt (system prompt, tool schemas, "
                         "full history, images) is not visible to the model, so it cannot be "
                         "estimated - it is shown as unavailable unless supplied.")
    ap.add_argument("--tokens-out", type=int, default=None,
                    help="EXACT output token count from the API response. Overrides the local "
                         "estimate and is labelled exact rather than approximate.")
    ap.add_argument("--no-token-estimate", action="store_true",
                    help="skip the local output token estimate entirely")
    ap.add_argument("--attribution-file", default=None,
                    help="JSON file holding {model, model_id, mode}. Set once, read every build - "
                         "retyping these per build is how they drift out of date.")
    ap.add_argument("--verify-against", default=None,
                    help="Path to a ground-truth transcript of what was ACTUALLY said (e.g. the "
                         "user's paste-back). The build FAILS if the turn source diverges from it. "
                         "This is the only ground truth available on claude.ai: the container "
                         "cannot reach an authenticated session, so nothing else can confirm the "
                         "source matches reality. In Claude Code the Stop hook's "
                         "last_assistant_message makes this unnecessary.")
    ap.add_argument("--steps-file", default=None,
                    help="newline-delimited tool-call descriptions, appended as calls are made. "
                         "Injected as a step block so step text is never re-transcribed from memory.")
    ap.add_argument("--debug", action="store_true",
                    help="print per-sentence ASR diagnostics (spoken text, expected vs returned token count, raw ASR words) for every sentence that falls back to proportional timing")
    args = ap.parse_args()

    for t in ("piper", "ffmpeg", "ffprobe"):
        need(t)
    from faster_whisper import WhisperModel
    # float32, not int8. Isolated by direct comparison (see
    # references/whisper-tts-reliability.md): the SAME clip through the SAME
    # loaded int8 model produced a different result on 3 of 3 consecutive calls -
    # including a straight repetition-loop hallucination on one of them, and a
    # well-documented Whisper hallucination artifact ("thank you for watching my
    # video") on a fresh reload. Neither temperature=0.0 nor cpu_threads=1 fixed
    # it - those control decoding policy and thread scheduling, not the
    # underlying int8 GEMM kernel, which was the actual source. float32 on the
    # identical clip returned the SAME 24-word result bit-for-bit on all 3 calls,
    # with materially better content. Slower per clip; worth it for the QC gate
    # in this tool to mean the same thing on every run of the same input.
    wmodel = WhisperModel(args.whisper_model, device="cpu", compute_type="float32", cpu_threads=1)

    # Each input file is one turn. Blocks carry their turn index so the player can
    # render and navigate turns as distinct units rather than one undifferentiated
    # transcript - which is what made "is this the current turn?" ambiguous before.
    turns_meta, blocks = [], []
    for ti, path in enumerate(args.input):
        raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        if args.labels and ti < len(args.labels):
            label = args.labels[ti]
        elif path == "-":
            label = f"turn {ti + 1}"
        else:
            label = os.path.splitext(os.path.basename(path))[0]
        tb = parse_blocks(raw)
        for b in tb:
            b["turn"] = ti
        blocks.extend(tb)
        turns_meta.append({"i": ti, "label": label, "source_text": raw})
    # Attribution from file first, explicit flags override. Reading it from disk
    # is the point: hand-typing the model into each build is exactly what let a
    # stale value ride along for five consecutive releases.
    if args.attribution_file and os.path.exists(args.attribution_file):
        try:
            _a = json.load(open(args.attribution_file))
            args.model = args.model or _a.get("model")
            args.model_id = args.model_id or _a.get("model_id")
            args.mode = args.mode or _a.get("mode")
        except Exception as e:
            print(f"[karaoke] could not read attribution file: {e}")

    src = "\n\n".join(t["source_text"] for t in turns_meta)
    # Steps come from the running log, not from markdown the author retypes.
    #
    # POSITION MATTERS AS MUCH AS TEXT. A turn interleaves several step groups
    # between paragraphs; appending them all as one block at the end gets the
    # text right and the shape wrong. The log is split into groups on a line of
    # "---", and each group fills the next "> @steps" placeholder in the source,
    # in order - so the rendered document keeps the actual call flow.
    if args.steps_file and os.path.exists(args.steps_file):
        raw_log = open(args.steps_file, encoding="utf-8").read()
        def _split_type(line):
            """Lines may be 'type|text' where type is tool/edit/file. Bare lines
            default to tool, so older logs keep working unchanged."""
            if "|" in line:
                t, _, rest = line.partition("|")
                t = t.strip().lower()
                if t in ("tool", "edit", "file"):
                    return t, rest.strip()
            return "tool", line.strip()

        raw_groups = [[l.strip() for l in g.splitlines() if l.strip()]
                      for g in raw_log.split("---")]
        raw_groups = [g for g in raw_groups if g]
        groups, group_types = [], []
        for g in raw_groups:
            pairs = [_split_type(l) for l in g]
            group_types.append([t for t, _ in pairs])
            groups.append([txt for _, txt in pairs])
        placeholders = [b for b in blocks
                        if b["type"] == "quote" and b.get("items") == ["@steps"]]
        if placeholders and groups:
            for ph, grp, gtypes in zip(placeholders, groups, group_types):
                ph["items"] = grp
                ph["types"] = gtypes
                ph["raw"] = "\n".join(grp)
            # A placeholder with no group left is an authoring error: more
            # "> @steps" markers were written than the log has groups. Marking it
            # non-narrated is not enough - the literal token stays in source_text
            # while vanishing from the render, so display_text_is_verbatim fails
            # with a confusing off-by-one. Strip it from BOTH, and say so loudly,
            # because a silently dropped placeholder means a step group the
            # author expected to appear simply is not there.
            # A placeholder with no group is an authoring error: more "> @steps"
            # markers than the log has groups. Handled after substitution below,
            # where the remaining markers can be identified unambiguously.
            orphans = placeholders[len(groups):]
            for ph in orphans:
                ph["narrated"] = False
                ph["items"] = []
                ph["raw"] = ""
            for t in turns_meta:
                for ph, grp in zip(placeholders, groups):
                    t["source_text"] = t["source_text"].replace(
                        "> @steps", "\n".join("> " + l for l in grp), 1)
            # Any "> @steps" still standing had no group to consume it. Remove it
            # from source_text so source and render agree; marking the block
            # non-narrated alone leaves the literal token in the source and
            # produces a confusing off-by-one in display_text_is_verbatim.
            if orphans:
                print(f"[karaoke] WARNING: {len(orphans)} '> @steps' placeholder(s) had no "
                      f"matching group in the step log ({len(groups)} available). Removed. "
                      f"If steps were expected there, the log is missing a '---' separator.")
                for t in turns_meta:
                    t["source_text"] = re.sub(r"\n?> @steps\n?", "\n", t["source_text"])
        elif groups:
            # No placeholders: fall back to one appended block, and say so, since
            # silently losing position is exactly the bug this replaced.
            print("[karaoke] no '> @steps' placeholders found; appending steps at end")
            flat = [l for g in groups for l in g]
            last_turn = turns_meta[-1]["i"] if turns_meta else 0
            blocks.append({"type": "quote", "level": 0, "items": flat,
                           "raw": "\n".join(flat), "narrated": True, "turn": last_turn})
            if turns_meta:
                quoted = "\n".join("> " + l for l in flat)
                turns_meta[-1]["source_text"] = (
                    turns_meta[-1]["source_text"].rstrip() + "\n\n" + quoted + "\n")

    if not any(b["narrated"] for b in blocks):
        sys.exit("[karaoke] nothing narratable in input")
    subs_on = not args.no_subs

    model = ensure_voice(args.voice, args.voices_dir)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="karaoke_")
    try:
        first = next(b for b in blocks if b["narrated"])
        probe_sp, _, _, _, _ = build_spoken(split_sentences(first["raw"])[0], subs_on)
        piper_synth(probe_sp, os.path.join(tmp, "probe.wav"), model, args.rate)
        sr, _ = load_i16(os.path.join(tmp, "probe.wav"))
        gap = np.zeros(int(args.gap * sr), dtype=np.int16)
        bgap = np.zeros(int(args.block_gap * sr), dtype=np.int16)
        tgap = np.zeros(int(max(args.block_gap * 2.2, 1.1) * sr), dtype=np.int16)

        out_blocks, flat_sents, flat_words, pieces = [], [], [], []
        cursor = si = resplits = 0
        match_rates = []

        for bi, blk in enumerate(blocks):
            if not blk["narrated"]:
                out_blocks.append({"type": blk["type"], "level": blk["level"],
                                   "turn": blk.get("turn", 0),
                                   "narrated": False, "text": blk["raw"], "sentences": []})
                continue
            bsents = []
            # Quote blocks carry explicit per-line items; everything else splits
            # into sentences normally.
            for s in (blk.get("items") or split_sentences(blk["raw"])):
                spoken, disp, styles, counts, expected_spoken = build_spoken(s, subs_on)
                if not disp:
                    continue
                audio, did = synth_qc(spoken, model, args.rate, sr, tmp, f"{bi}_{si}")
                if did:
                    resplits += 1
                cp = os.path.join(tmp, f"al_{bi}_{si}.wav")
                w = wave.open(cp, "wb"); w.setnchannels(1); w.setsampwidth(2)
                w.setframerate(sr); w.writeframes(audio.tobytes()); w.close()

                clip_dur = len(audio) / sr
                asr_words = asr_spans(wmodel, cp, spoken, debug=args.debug,
                                       debug_ctx=f"sentence {si}: {s[:60]!r}  "
                                                 f"(expected {len(expected_spoken)} spoken tokens)")
                spoken_spans, match_rate = align_spoken_tokens(expected_spoken, asr_words, clip_dur)
                mapped = aggregate_to_display(spoken_spans, counts)
                match_rates.append(match_rate)

                off = cursor / sr
                words = []
                for tok, st, (a, b) in zip(disp, styles, mapped):
                    a, b = a + off, b + off
                    wd = {"w": tok, "start": round(a, 3), "end": round(b, 3)}
                    if st:
                        wd["s"] = st
                    words.append(wd)
                sent = {"i": si, "text": " ".join(disp), "start": round(off, 3),
                        "end": round(off + clip_dur, 3), "words": words,
                        "match_rate": round(match_rate, 3)}
                bsents.append(sent); flat_sents.append(sent); flat_words.extend(words)
                pieces += [audio, gap]
                cursor += len(audio) + len(gap)
                si += 1
                print(f"\r[karaoke] {si} sentences synthesized", end="", flush=True)
            _ob = {"type": blk["type"], "level": blk["level"],
                   "turn": blk.get("turn", 0),
                   "narrated": True, "text": blk["raw"], "sentences": bsents}
            if blk.get("types"):
                _ob["types"] = blk["types"]
            out_blocks.append(_ob)
            # Longer pause at a turn boundary than between blocks, so turns are
            # audibly separated and not just visually.
            is_last_of_turn = (bi + 1 >= len(blocks)) or blocks[bi + 1].get("turn", 0) != blk.get("turn", 0)
            pieces.append(tgap if is_last_of_turn else bgap)
            cursor += len(tgap) if is_last_of_turn else len(bgap)
        print()

        enforce_monotonic_min_duration(flat_words, MIN_WORD_DUR)

        combined = np.concatenate(pieces)
        raw = os.path.join(tmp, "raw.wav")
        w = wave.open(raw, "wb"); w.setnchannels(1); w.setsampwidth(2)
        w.setframerate(sr); w.writeframes(combined.tobytes()); w.close()
        I_out, TP_out = normalize(raw, args.out, args.lufs, args.peak, args.bitrate)
        dur = len(combined) / sr

        chk = os.path.join(tmp, "final.wav")
        run(["ffmpeg", "-v", "error", "-y", "-i", args.out, "-ac", "1", "-c:a", "pcm_s16le", chk])
        _, fa = load_i16(chk)
        final_dist = distortion_pct(fa)

        # VERBATIM FIDELITY CHECK. Reconstruct exactly what the player will render
        # and compare it, token for token, against the source with only inline
        # markdown markers removed. This exists because em dashes were being
        # silently dropped from the display layer - 8 of them in a single 344-word
        # turn - while the tool claimed to be showing verbatim text. Trusting that
        # promise instead of testing it is what let it ship.
        # _strip_inline now lives at module level (see its docstring) so
        # audit_published.py compares text identically instead of duplicating
        # these regexes. Behaviour here is unchanged.

        # Ground-truth check. display_text_is_verbatim proves render == source;
        # this proves source == what was actually said. They are different claims,
        # and only the second one catches a source that was incomplete before the
        # build ever ran.
        # TRI-STATE, deliberately. None means "not checked", distinct from True
        # ("checked, matched"). Initialising this to True made an unsupplied
        # ground truth report as PASS, which reads as "the source matched
        # reality" but means "nothing was compared". That vacuous PASS was
        # reported as meaningful on three consecutive turns before anyone
        # noticed. A guard that is not wired to fire by default will not fire.
        ground_ok, ground_detail = None, ""
        if args.verify_against and os.path.exists(args.verify_against):
            ground_ok = True
            gt_raw = open(args.verify_against, encoding="utf-8").read()
            # Strip fenced code from the truth side the same way `mine` is
            # already built only from narrated blocks (parse_blocks excludes
            # code). Without this, ANY ground-truth file containing a code
            # fence false-fails, since the fence's words appear in truth but
            # never in mine by design - reproduced by comparing this file
            # against itself with a code-fenced, deliberately-unnarrated
            # build-report coda: FAIL at a file compared against itself.
            gt_blocks = parse_blocks(gt_raw)
            gt_narrated_only = "\n".join(b["raw"] for b in gt_blocks
                                        if b.get("narrated") and b.get("type") != "quote")
            truth = _strip_inline(gt_narrated_only).split()
            mine = _strip_inline("\n".join(
                b["raw"] for b in blocks if b.get("narrated") and b.get("type") != "quote"
            )).split()
            sm_g = difflib.SequenceMatcher(None, truth, mine, autojunk=False)
            ratio = sm_g.ratio()
            if ratio < 0.995:
                ground_ok = False
                for tag, i1, i2, j1, j2 in sm_g.get_opcodes():
                    if tag == "equal":
                        continue
                    ground_detail += (f"\n      {tag}: truth={truth[i1:i2][:8]} "
                                      f"built={mine[j1:j2][:8]}")
                ground_detail = f"\n      similarity {ratio:.4f}" + ground_detail

        verbatim_ok, verbatim_detail = True, ""
        for t in turns_meta:
            want = _strip_inline("\n".join(
                b["raw"] for b in parse_blocks(t["source_text"]) if b["narrated"]
            )).split()
            got = [w["w"] for b in out_blocks if b.get("turn") == t["i"]
                   for s in b["sentences"] for w in s["words"]]
            if want != got:
                verbatim_ok = False
                sm = difflib.SequenceMatcher(None, want, got, autojunk=False)
                diffs = [f"{tag}: want={want[i1:i2][:6]} got={got[j1:j2][:6]}"
                         for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]
                verbatim_detail += f"\n      turn {t['i']+1}: {len(want)} src vs {len(got)} shown; " \
                                   + "; ".join(diffs[:3])

        checks = {
            "display_text_is_verbatim": verbatim_ok,
            "source_matches_ground_truth": ground_ok,
            "timings_monotonic": all(flat_words[k]["start"] <= flat_words[k+1]["start"]
                                     for k in range(len(flat_words)-1)),
            "no_overlapping_words": all(flat_words[k]["end"] <= flat_words[k+1]["start"] + 1e-6
                                        for k in range(len(flat_words)-1)),
            "no_zero_width_words": all(x["end"] > x["start"] for x in flat_words),
            "words_within_duration": (not flat_words) or flat_words[-1]["end"] <= dur + 0.5,
            "every_sentence_has_words": all(len(s["words"]) > 0 for s in flat_sents),
            "distortion_under_1pct": final_dist < 1.0,
            "true_peak_not_clipping": (TP_out is None or TP_out <= 0.0),
        }
        # None ("not checked") is excluded rather than treated as failure: on
        # claude.ai the only ground truth is a user paste-back, which cannot
        # exist until after the turn ends, so hard-failing every such build
        # would make the gate useless. It must neither pass nor block - it must
        # be visibly absent.
        ok = all(v for v in checks.values() if v is not None)

        # Real per-sentence ASR confidence, not a boolean. Reported rather than
        # gated: there's no calibration data yet establishing what match_rate
        # threshold actually correlates with a bad user-facing result, and a
        # made-up threshold would be false precision. Low-confidence sentences
        # still get usable timing via local interpolation - see align_spoken_tokens.
        avg_match = sum(match_rates) / len(match_rates) if match_rates else 1.0
        low_conf = [i for i, r in enumerate(match_rates) if r < 0.5]

        # Per-turn time spans, derived from the sentences actually belonging to each
        # turn - so the player can jump to a turn and show which one is playing.
        for t in turns_meta:
            t_sents = [s for b in out_blocks if b.get("turn") == t["i"] for s in b["sentences"]]
            t["start"] = round(min((s["start"] for s in t_sents), default=0.0), 3)
            t["end"] = round(max((s["end"] for s in t_sents), default=0.0), 3)
            t["words"] = sum(len(s["words"]) for s in t_sents)
            t["sentences"] = len(t_sents)

        # Token feedback, split into input and output because they are NOT
        # symmetrically knowable:
        #   OUTPUT can be estimated locally - the response text is right here. The
        #     estimate uses tiktoken's o200k_base, which is OpenAI's tokenizer, not
        #     Anthropic's (Anthropic's is not distributed for local use). Right
        #     neighbourhood, not right.
        #   INPUT cannot be estimated at all. The serialized prompt - system prompt,
        #     tool schemas, full conversation history, images - is never visible to
        #     the model producing the response. A guess would not be slightly off,
        #     it would be arbitrary, since images and tool definitions dominate the
        #     count and are entirely opaque from here. So it is reported as
        #     unavailable rather than fabricated.
        # Either can be supplied exactly from an API response via --tokens-in /
        # --tokens-out, which flips the label from estimate to exact.
        tok_in = tok_out = None
        if args.tokens_in is not None:
            tok_in = {"count": args.tokens_in, "exact": True, "tokenizer": "api-reported"}
        if args.tokens_out is not None:
            tok_out = {"count": args.tokens_out, "exact": True, "tokenizer": "api-reported"}
        elif not args.no_token_estimate:
            try:
                import tiktoken
                n = len(tiktoken.get_encoding("o200k_base").encode(src))
                tok_out = {"count": n, "exact": False, "tokenizer": "o200k_base (approx.)"}
            except Exception as e:
                print(f"[karaoke] output token estimate unavailable: {e}")
        tokens = {"input": tok_in, "output": tok_out} if (tok_in or tok_out) else None

        # If output is only an estimate, hand over the means to get the exact
        # figure instead of leaving the person stuck with a guess. count_tokens
        # is free, official, and needs nothing but the literal text - which is
        # right here. Written to disk next to the manifest, not just printed,
        # so it survives past the terminal scrollback.
        count_snippet_path = None
        if tok_out is not None and not tok_out.get("exact"):
            model_for_count = args.model_id or "claude-sonnet-5"
            snippet = f'''# Exact output token count via Anthropic's official count_tokens endpoint.
# Free, no generation triggered. Needs ANTHROPIC_API_KEY set and the anthropic
# package installed (pip install anthropic). This counts the response TEXT
# only - it cannot recover input tokens, which require the original request's
# system prompt, tools and history, none of which are available here.
import anthropic
client = anthropic.Anthropic()
with open({str(os.path.splitext(args.out)[0] + ".source.txt")!r}, encoding="utf-8") as f:
    text = f.read()
result = client.messages.count_tokens(
    model={model_for_count!r},
    messages=[{{"role": "user", "content": text}}],
)
print(result.input_tokens, "tokens (exact, via count_tokens)")
# Feed the real number back in:
#   python3 build_karaoke.py ... --tokens-out <that number>
'''
            count_snippet_path = os.path.splitext(args.out)[0] + ".count_tokens.py"
            with open(count_snippet_path, "w") as f:
                f.write(snippet)
            with open(os.path.splitext(args.out)[0] + ".source.txt", "w") as f:
                f.write(src)

        manifest = {
            "schema_version": "1.0",
            "source_text": src,
            "duration": round(dur, 3),
            # Attribution is recorded only when explicitly supplied. No default is
            # guessed: a wrong model or mode stamped on a response is worse than
            # none at all.
            "attribution": {k: v for k, v in
                            (("model", args.model), ("model_id", args.model_id),
                             ("mode", args.mode), ("tokens", tokens)) if v},
            "turns": [{k: v for k, v in t.items() if k != "source_text"} for t in turns_meta],
            "blocks": out_blocks,
            "sentences": flat_sents,
            "words": flat_words,
            "qc": {"passed": ok, "checks": checks,
                   "blocks": len(out_blocks),
                   "code_blocks_not_narrated": sum(1 for b in out_blocks if not b["narrated"]),
                   "sentences": len(flat_sents), "words": len(flat_words),
                   "distortion_pct_mp3": round(final_dist, 3),
                   "loudness_lufs": I_out, "true_peak_dbtp": TP_out,
                   "resplit_sentences": resplits,
                   "avg_word_match_rate": round(avg_match, 3),
                   "low_confidence_sentences": low_conf},
        }
        tp = os.path.splitext(args.out)[0] + ".timing.json"
        json.dump(manifest, open(tp, "w"), indent=2)

        print("\n=== KARAOKE QC REPORT ===")
        for t in turns_meta:
            print(f"  turn {t['i']+1}: {t['label']!r}  "
                  f"{t['sentences']} sentences / {t['words']} words  "
                  f"[{int(t['start']//60)}:{int(t['start']%60):02d} - {int(t['end']//60)}:{int(t['end']%60):02d}]")
        print(f"  blocks           : {len(out_blocks)} "
              f"({manifest['qc']['code_blocks_not_narrated']} code, not narrated)")
        print(f"  sentences/words  : {len(flat_sents)} / {len(flat_words)}")
        print(f"  re-split         : {resplits}")
        print(f"  avg word match   : {avg_match*100:.0f}%  "
              f"(per-sentence rates: {[round(r,2) for r in match_rates]})")
        if low_conf:
            print(f"  LOW CONFIDENCE   : sentence(s) {low_conf} - worth a manual listen")
        print(f"  distortion (mp3) : {final_dist:.2f}%")
        print(f"  loudness         : {I_out:.1f} LUFS   true peak {TP_out:.1f} dBTP")
        print(f"  duration         : {int(dur//60)}:{int(dur%60):02d}")
        for k, v in checks.items():
            label = "NOT CHECKED" if v is None else ("PASS" if v else "FAIL")
            print(f"    {label}  {k}")
            if k == "source_matches_ground_truth" and v is None:
                print("      no --verify-against supplied, so nothing was compared.")
                print("      This is NOT a pass. On claude.ai the only ground truth is a")
                print("      paste-back of what was actually said, which cannot exist until")
                print("      the turn has ended - see references/token-accuracy.md.")
            if k == "display_text_is_verbatim" and v is False:
                print(verbatim_detail)
            if k == "source_matches_ground_truth" and v is False:
                print(ground_detail)
        print(f"  RESULT           : {'PASS' if ok else 'FAIL - do not ship'}")
        print(f"  audio  : {args.out}")
        print(f"  timing : {tp}")
        if count_snippet_path:
            print(f"  exact token count : run {count_snippet_path} with an API key for the real figure")
        sys.exit(0 if ok else 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
