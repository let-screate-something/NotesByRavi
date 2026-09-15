#!/usr/bin/env python3
"""
make_notes.py — content pipeline: turn PDFs / TXT / MD into handwritten-style PDF.

Usage:
    python make_notes.py <file.pdf|file.txt|file.md> [--theme ocean] [--out DIR] [--title T]

Smart stuff:
  * PDF text is parsed with font-size & bold awareness -> real headings/keywords
  * Each section gets an automatic keyword list -> highlighted in the renderer
  * 'a -> b -> c' sequences become hand-drawn flow arrows
  * 'Term: description' lines become sticky-note callouts
"""

import argparse
import json
import os
import re
import sys

import fitz  # PyMuPDF

import renderer

BASE = os.path.dirname(os.path.abspath(__file__))
THEMES_FILE = os.path.join(BASE, "themes.json")

H1_RE = re.compile(r"^#\s+(.*)")
H2_RE = re.compile(r"^#{2,6}\s+(.*)")
BULLET_RE = re.compile(r"^\s*[-*•▪◦]\s+(.*)")
NUM_RE = re.compile(r"^\s*\d+[\.\)]\s+(.*)")
ARROW_RE = re.compile(r"\s*(?:->|\u2192)\s*")
KEY_RE = re.compile(r"^([A-Z][A-Za-z ,'&/-]{1,25}):\s*(.*)$")
SHAKE_RE = re.compile(r"[*_`~]", re.M)
DASH_RE = re.compile(r"\s*[•▪◦●○∙·|/]\s*")
BULLET_DASH_RE = re.compile(r"\s*([•▪◦●○∙·/|])\s*")
# contact/meta lines (emails, phones, 'LinkedIn • GitHub', locations, dates)
# are prose context, never bullets — and never keyword-highlighted.
META_RE = re.compile(r"(@|\+\d|www\.|http|linkedin|github|leetcode|portfolio"
                     r"|howrah|uttar pradesh|west bengal|india"
                     r"|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b"
                     r"|\b20\d\d\b)", re.I)

# Private-use icon glyphs (resume icon fonts) have no handwritten-font
# coverage -> strip them to avoid missing-glyph warnings.
PUA_RE = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")
# Hyphenated line-breaks in justified resumes ('customer-' + 'focused'):
# join 'word-' + 'continuation' directly (no space, drop the hyphen when the
# continuation is lowercase — else keep the real compound hyphen).
HYPHEN_JOIN_RE = re.compile(r"(\w)-\s+([A-Za-z])")

# ---------------------------------------------------------------- extraction

def _clean(s):
    # icon fonts + stray symbols with no handwritten-font coverage
    s = PUA_RE.sub("", s)  # icon fonts
    s = s.replace("▪", "").replace("◦", "").replace("•", " - ")
    s = s.replace("●", "-").replace("◆", "-").replace("■", "-")
    s = s.replace("⬢", "-").replace("⬣", "-")
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2192", "->")
    s = SHAKE_RE.sub("", s).strip()
    return re.sub(r"\s+", " ", s)

def _span_gap(prev, cur):
    """Width-aware gap between two spans; negative = overlap (kerning)."""
    try:
        gap = cur["bbox"][0] - prev["bbox"][2]
        size = max(prev.get("size", 10), cur.get("size", 10))
        return gap, (gap > -0.06 * size and gap > -0.8)
    except Exception:
        return 2.0, True


def extract_from_pdf(path, use_ocr=False):
    """Return list of ('h', level, text) | ('p', text). Font size aware.
    Scanned pages (no text) are OCR'd when use_ocr=True and available."""
    doc = fitz.open(path)
    items = []
    scanned_pages = 0
    for page in doc:
        d = page.get_text("dict")
        sizes = []
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    if s["text"].strip():
                        sizes.append(s["size"])
        body_size = sorted(sizes)[len(sizes) // 2] if sizes else 11
        page_lines = []
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                spans = [s for s in l.get("spans", []) if s["text"]]  # keep spaces!
                if not spans or not "".join(s["text"] for s in spans).strip():
                    continue
                # Gap-aware join: PyMuPDF emits per-character spans in some PDFs,
                # including explicit ' ' spans. A space is added only when the
                # gap is a real word break; small/negative gaps are kerning
                # *inside* a word (e.g. Enterprise|Data with gap -3.02).
                parts, prev = [], None
                for s in spans:
                    t = s["text"]
                    if parts and prev is not None and t and not t[0].isspace():
                        tail = parts[-1][-1:] if parts[-1] else ""
                        if tail and not tail.isspace() \
                                and tail not in "-/|(" and t[0] not in ",.;:)%-/'\"":
                            gap, is_space = _span_gap(prev, s)
                            if is_space and gap > 0.6:
                                parts.append(" ")
                    parts.append(t)
                    prev = s
                txt = _clean("".join(parts))
                if not txt:
                    continue
                size = max(s["size"] for s in spans)
                bold = any(s["flags"] & 16 for s in spans)
                if len(txt) <= 3 and txt.isdigit():
                    continue  # page number
                if size >= body_size * 1.28 and len(txt) < 90:
                    page_lines.append(("h", 1 if size >= body_size * 1.5 else 2, txt))
                elif bold and len(txt) < 70 and not txt.endswith("."):
                    page_lines.append(("h", 2, txt))
                else:
                    page_lines.append(("p", txt))
        if not page_lines and use_ocr:
            scanned_pages += 1
            page_lines = _ocr_page(page)
        page_lines = _join_hyphen_lines(page_lines)
        items.extend(page_lines)
    doc.close()
    # repair hyphen-joins now all pieces of a visual paragraph merged
    fixed = []
    for it in items:
        if it[0] == "p":
            fixed.append(("p", _dehyphen(it[1])))
        else:
            fixed.append(it)
    return fixed


def _ocr_page(page):
    """OCR one scanned page; returns item stream."""
    import ocr as _ocr
    if not _ocr.ocr_available():
        return []
    import tempfile
    pix = page.get_pixmap(dpi=200)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    pix.save(tmp_path)
    text = _ocr.ocr_image(tmp_path)
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    return [("p", _clean(ln)) for ln in text.splitlines() if _clean(ln)]


def _join_hyphen_lines(page_lines):
    """Join 'word-' + 'continuation' split across visual lines of one page.

    'high-impact,' + 'customer-' + 'focused' -> 'high-impact, customerfocused'
    is still wrong alone; joining the pieces first gives 'customerfocused',
    which _dehyphen() then repairs using the lowercase-continuation rule.
    """
    out = []
    for kind, *rest in page_lines:
        txt = rest[-1] if rest else ""
        if out and out[-1][0] == kind == "p" and isinstance(txt, str):
            pk, *pr = out[-1]
            prev_txt = pr[-1] if pr else ""
            if isinstance(prev_txt, str) and prev_txt.endswith("-") \
                    and txt[:1].isalpha() and prev_txt[-2:-1] != " ":
                merged = prev_txt[:-1] + txt
                out[-1] = (pk, *pr[:-1], merged) if len(pr) > 1 else (pk, merged)
                continue
        out.append((kind, *rest))
    return out


def _dehyphen(text):
    """Repair 'customerfocused' style joins: word- + lowercase continuation."""
    def fix(m):
        head, tail = m.group(1), m.group(2)
        if len(head) >= 4 and tail[:1].islower():
            # known compounds keep their hyphen; line-break splits drop it
            if (head + tail).lower().startswith(
                    ("highimpact", "objectoriented", "endtoend",
                     "decisionmaking")):
                return head + "-" + tail
            return head + tail
        return m.group(0)
    return HYPHEN_JOIN_RE.sub(fix, text)
    doc.close()
    return items

def extract_text(path, use_ocr=False):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_from_pdf(path, use_ocr=use_ocr)
    raw = open(path, encoding="utf-8", errors="ignore").read()
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        m1, m2 = H1_RE.match(s), H2_RE.match(s)
        if m1:
            out.append(("h", 1, strip_md_inline(_clean(m1.group(1)))))
        elif m2:
            out.append(("h", 2, strip_md_inline(_clean(m2.group(1)))))
        else:
            s = strip_md_inline(_clean(s))
            if not s:
                continue
            if re.match(r"^([-*_])\1{2,}\s*$", s):  # --- / *** separators
                continue
            out.append(("p", s))
    return out

def strip_md_bullet(line):
    """Remove one markdown bullet/number prefix ('- ', '* ', '1. ') only.

    Indented (nested) bullets keep their marker — the renderer indents them.
    Signs glued to a following single token may also stay, but only when the
    sign is INSIDE the chemical token stream: '- e-' alone ('- e- carrier').
    A full '- word ...' bullet still strips normally.
    """
    if re.match(r"^[+-]\s+[A-Za-z][A-Za-z0-9()]*[+-](\s|$)", line):
        return line
    if re.match(r"^\s+[-*\u2022]", line):
        return line
    return re.sub(r"^(\s*(?:[-*\u2022]|\d+[.)])\s+)", "", line)


def strip_md_inline(text):
    """Remove inline markdown (**bold**, *ital*, `code`, [txt](url), #tags)."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)   # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)    # links keep text
    text = re.sub(r"`([^`]*)`", r"\1", text)                # code spans
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)          # bold
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)            # italic
    text = re.sub(r"_([^_\n]+)_", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)              # strikethrough
    return text.strip()

# ---------------------------------------------------------------- keywords

def _tokens(text):
    return [w.strip(".,;:!?()[]{}\"'") for w in text.split()]

def top_keywords(texts, n=6):
    freq = {}
    for t in texts:
        for w in _tokens(t.lower()):
            if len(w) > 3 and w not in STOPWORDS and w.isalpha():
                freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))[:n]
    return [w for w, _ in ranked]

def _classify(text):
    m = KEY_RE.match(text)
    if m and len(m.group(2)) > 8 and m.group(1).lower() in KEYS:
        return ("key", m.group(1), m.group(2))
    if ARROW_RE.search(text) and not text.startswith(("http", "www")):
        raw_parts = [p for p in ARROW_RE.split(text)]
        parts = []
        for p in raw_parts:
            # only trim TRUE edge dashes: a dash with a space on its outer
            # side was a bullet, 'e-' / 'O2-' / '-e' are chemistry — keep
            p = re.sub(r"^[-*\u2022]\s+(?=\S)", "", p)      # leading bullet
            p = re.sub(r"\s+$", "", p)
            p = re.sub(r"(?<=\s)-(?=\s*$)", "", p)          # trailing stray
            p = p.strip()
            if p.strip(" -*\u2022"):
                parts.append(p)
        if 2 <= len(parts) <= 8 and all(parts) and max(len(p) for p in parts) < 28:
            return ("arrow", parts)
    return None
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        m1, m2 = H1_RE.match(s), H2_RE.match(s)
        if m1:
            out.append(("h", 1, _clean(m1.group(1))))
        elif m2:
            out.append(("h", 2, _clean(m2.group(1))))
        else:
            out.append(("p", _clean(s)))
    return out

STOPWORDS = set("""a an and are as at be but by for from had has have he her his
i if in into is it its me my nor of on or our so that the their them they this
to was we were what when which who why will with you your not no than then
there these those about after before between during each few many more most
other some such only own same very just can could should would may might""".split())

KEYS = {"definition", "tip", "note", "example", "key", "remember", "important",
        "warning", "formula", "equation", "summary"}

# ---------------------------------------------------------------- blocks

def build_blocks(items):
    """items: list of ('h', level, text) | ('p', text) -> renderer blocks.
    Passthrough of ('key',..) / ('arrow',..) tuples also accepted."""
    title = None
    sections = []           # list of dicts: {head, copy[]}
    pending = []
    level = 1
    for idx, it in enumerate(items):
        if it[0] == "h":
            if title is None and it[1] == 1:
                title = it[2]
            else:
                pending.append({"head": it[2], "level": it[1], "copy": []})
                level = it[1]
        else:
            if not pending:
                pending.append({"head": None, "level": 0, "copy": []})
            text = it[1] if it[0] == "p" else it
            # resume-style leader lines ('EDUCATION -', 'SKILLS:') that sit
            # right before prose become real section heads instead of bullets
            if isinstance(text, str):
                # nested md bullets carry their marker into text ('- '); one
                # marker is re-added by the renderer dot, so strip it first.
                # Signs glued to tokens (H+, e-) are not bullets — kept by
                # strip_md_bullet itself, so no extra guard needed here.
                text = strip_md_bullet(text)
                nxt = items[idx + 1] if idx + 1 < len(items) else None
                nxt_is_para = nxt is not None and nxt[0] == "p"
                if nxt_is_para and len(text.split()) <= 6:
                    mh = re.match(r"^([A-Z][A-Za-z0-9 ,&'/-]{1,40}?)\s*[:-]\s*$", text)
                    if mh and len(nxt[1]) > 25:
                        pending.append({"head": mh.group(1).strip(), "level": 2, "copy": []})
                    else:
                        me = re.match(r"^([A-Z][A-Z0-9 ,&'/-]{3,40})$", text)
                        if me and len(nxt[1]) > 25:
                            pending.append({"head": text.strip().title(), "level": 2, "copy": []})
                        else:
                            pending[-1]["copy"].append(text)
                else:
                    pending[-1]["copy"].append(text)
            else:
                pending[-1]["copy"].append(text)
    if title is None and pending:
        title = pending[0]["head"] or "Notes"
        if pending and pending[0]["head"]:
            pending = pending[1:]
    blocks = []
    for sec in pending:
        head = sec["head"]
        hl = top_keywords([c for c in sec["copy"] if isinstance(c, str)])
        if head:
            blocks.append(("h2", head, hl))
        copied_hl = list(hl)
        for c in sec["copy"]:
            if isinstance(c, str):
                cls = _classify(c)
                if cls:
                    blocks.append(cls)
                else:
                    full = META_RE.match(c or "") is not None or len(c.split()) <= 2 and len(c) < 60
                    if full:
                        hl_use = top_keywords([c]) or copied_hl  # own terms, not section bleed
                        blocks.append(("para", c, hl_use))
                    elif len(c) < 160:
                        blocks.append(("bullet", c, 0, copied_hl))
                    else:
                        blocks.append(("para", c, copied_hl))
            elif isinstance(c, tuple):
                blocks.append(c + (copied_hl,))
            else:
                blocks.append(("bullet", str(c), 0, copied_hl))
        blocks.append(("divider",))
    return title or "My Notes", blocks

def merge_markdown(md_text):
    """AI output (markdown) -> same item stream extract_text would return."""
    out = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s:
            continue
        m1, m2 = H1_RE.match(s), H2_RE.match(s)
        mb, mn = BULLET_RE.match(s), NUM_RE.match(s)
        if m1:
            out.append(("h", 1, strip_md_inline(_clean(m1.group(1)))))
        elif m2:
            out.append(("h", 2, strip_md_inline(_clean(m2.group(1)))))
        elif mb:
            out.append(("p", strip_md_inline(_clean(mb.group(1)))))
        elif mn:
            out.append(("p", strip_md_inline(_clean(mn.group(1)))))
        else:
            s = strip_md_inline(_clean(s))
            if not s:
                continue
            # markdown horizontal rules (---, ***, ___) are separators
            if re.match(r"^([-*_])\1{2,}\s*$", s):
                continue
            out.append(("p", s))
    return out

# ---------------------------------------------------------------- generate

def generate_notes(input_path, theme_name="sunset", out_dir=None, title=None,
                   subtitle=None, cover=True, from_items=None, use_ocr=False):
    """Core pipeline: file -> pretty PDF (via renderer). Returns output path.
    from_items: optional pre-parsed item stream (used by the AI flow)."""
    items = from_items if from_items is not None else extract_text(input_path, use_ocr=use_ocr)
    doc_title, blocks = build_blocks(items)
    if title:
        doc_title = title
    if not blocks:
        raise ValueError("No content found in the input file.")
    out_dir = out_dir or os.path.join(BASE, "output")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(out_dir, f"{stem}_{theme_name}.pdf")
    if subtitle is None and isinstance(input_path, str) and os.path.isfile(input_path):
        subtitle = os.path.basename(input_path)
    renderer.build(theme_name, doc_title, blocks, out_path,
                   subtitle=subtitle, cover=cover)
    return out_path, doc_title

# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Generate handwritten-style notes")
    ap.add_argument("input", help="PDF, .txt or .md file")
    ap.add_argument("--theme", default="sunset")
    ap.add_argument("--out", default=os.path.join(BASE, "output"))
    ap.add_argument("--title", default=None)
    ap.add_argument("--no-cover", action="store_true")
    args = ap.parse_args()
    if not os.path.isfile(args.input):
        sys.exit(f"Input not found: {args.input}")
    out_path, _ = generate_notes(args.input, args.theme, args.out, args.title,
                                 cover=not args.no_cover)
    print(f"[OK] Notes written to: {out_path}")

if __name__ == "__main__":
    main()
