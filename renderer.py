"""renderer.py — the 'ink & pen' handwriting engine (fpdf2).

Turns structured content blocks into beautiful handwritten-style pages:
per-word rotation & baseline bounce, ink-shade variation, translucent
highlighter swipes, tilted sticky cards, washi tape, doodles, arrows,
a decorated cover page and running headers with doodled page numbers.
"""

import hashlib
import json
import os
import random
import re
from datetime import date

from fpdf import FPDF

BASE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE, "assets", "fonts")
THEMES_FILE = os.path.join(BASE, "themes.json")

def _font(name):
    return os.path.join(FONT_DIR, name)

FONT_FILES = {
    "caveat": _font("Caveat-Regular-static.ttf"),
    "caveatb": _font("Caveat-Bold-static.ttf"),
    "hand": _font("PatrickHand-Regular.ttf"),
    "handb": _font("Kalam-Bold.ttf"),
    "note": _font("Kalam-Regular.ttf"),
}

def _c(v):
    v = v.strip().lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))

def _mix(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))

def load_theme(name):
    with open(THEMES_FILE, encoding="utf-8") as f:
        themes = json.load(f)
    if name not in themes:
        raise ValueError(f"Theme '{name}' not found. Available: {', '.join(themes)}")
    raw = themes[name]
    t = {}
    for k, v in raw.items():
        if isinstance(v, list):
            t[k] = tuple(v)
        elif isinstance(v, str) and v.startswith("#"):
            t[k] = _c(v)
        else:
            t[k] = v
    # sensible defaults for new pen keys
    t.setdefault("ink", (45, 50, 60))
    t.setdefault("ink_var", 0.12)          # ink shade variation 0..0.3
    t.setdefault("wobble", 0.9)            # word rotation jitter degrees
    t.setdefault("bounce", 0.5)            # baseline bounce mm
    t.setdefault("highlight_opacity", 0.75)
    t.setdefault("arrow_color", t.get("bullet", (0, 0, 0)))
    return t

class Pen:
    """Draws words one by one with handwriting imperfections."""

    def __init__(self, pdf, rng, theme):
        self.pdf = pdf
        self.rng = rng
        self.theme = theme

    def _ink(self, base):
        var = self.theme.get("ink_var", 0.12)
        t = self.rng.uniform(0, var)
        return _mix(base, (20, 25, 30), t)

    def word(self, w, x, y, family, size, color, bold=False, rot=None):
        """Draw a single word starting at (x, y) top-left of its line box."""
        style = "B" if bold else ""
        self.pdf.set_font(family, style, size)
        ang = rot if rot is not None else self.rng.uniform(
            -self.theme.get("wobble", 0.9), self.theme.get("wobble", 0.9))
        with self.pdf.rotation(ang, x, y):
            self.pdf.set_text_color(*self._ink(color))
            self.pdf.text(x, y + size * 0.35, w)
        return self.pdf.get_string_width(w)

    def rich_line(self, tokens, x, y, size, base_color, kw_color, hl_terms,
                  family="hand", bold_family="handb", line_h=None, max_w=None):
        pdf = self.pdf
        if line_h is None:
            line_h = size * 0.52
        space_w = self._measure(" ", family, False, size)
        max_w = max_w if max_w is not None else pdf.w - pdf.r_margin - x
        # greedy wrap (over-wide single tokens are char-split first)
        lines, cur, cur_w = [], [], 0.0
        for w in tokens:
            ww = self._measure(w, family, False, size)
            if ww > max_w:
                if cur:
                    lines.append(cur)
                    cur, cur_w = [], 0.0
                for piece in self._split_long(w, max_w, family, False, size):
                    lines.append([(piece, self._measure(piece, family, False, size))])
                continue
            ww = ww * (1.03 if w.lower().strip(".,;:!?") in hl_terms else 1)
            if cur and cur_w + ww + space_w > max_w:
                lines.append(cur)
                cur, cur_w = [], 0.0
            cur.append((w, ww))
            cur_w += ww + space_w
        if cur:
            lines.append(cur)
        yy = y
        for line in lines:
            # baseline bounce per line
            bounce = self.rng.uniform(-self.theme.get("bounce", 0.5),
                                      self.theme.get("bounce", 0.5))
            xx = x
            for w, ww in line:
                key = w.lower().strip(".,;:!?()[]{}\"'“”‘’")
                is_kw = key in hl_terms and len(key) > 2
                fam = bold_family if is_kw else family
                col = kw_color if is_kw else base_color
                if is_kw:
                    self._highlight(xx, yy + bounce, ww, line_h)
                self.word(w, xx, yy + bounce, fam, size, col)
                xx += ww + space_w
            yy += line_h
        return yy - y, len(lines)

    def _split_long(self, w, max_w, family, bold, size):
        """Char-split an over-wide token; returns list of fitted pieces."""
        pieces, cur = [], ""
        for ch in w:
            t = cur + ch
            if self._measure(t, family, bold, size) <= max_w or not cur:
                cur = t
            else:
                pieces.append(cur)
                cur = ch
        if cur:
            pieces.append(cur)
        return pieces

    def _measure(self, w, family, bold, size):
        self.pdf.set_font(family, "B" if bold else "", size)
        return self.pdf.get_string_width(w)

    def para(self, text, x, y, size, color, hl_terms, max_w=None, line_h=None,
             kw_color=None):
        tokens = text.split()
        used_h, nlines = self.rich_line(tokens, x, y, size, color,
                                        kw_color or color, hl_terms,
                                        line_h=line_h, max_w=max_w)
        return used_h, nlines

    def _highlight(self, x, y, w, h):
        pad_x, pad_y = 0.7, h * 0.12
        col = self.theme.get("highlight", (255, 235, 150))
        with self.pdf.local_context(fill_opacity=self.theme.get("highlight_opacity", 0.45)):
            self.pdf.set_fill_color(*col)

def _sparkle(pdf, x, y, col, s=1.6):
    pdf.set_draw_color(*col)
    pdf.set_line_width(0.45)
    pdf.line(x - s, y, x + s, y)
    pdf.line(x, y - s, x, y + s)
    pdf.line(x - s * 0.6, y - s * 0.6, x + s * 0.6, y + s * 0.6)
    pdf.line(x - s * 0.6, y + s * 0.6, x + s * 0.6, y - s * 0.6)

def _squiggle(pdf, x, y, w, col, amp=1.1, step=4.0, width=0.55):
    pdf.set_draw_color(*col)
    pdf.set_line_width(width)
    pts, up, xx = [], True, x
    while xx < x + w:
        pts.append((xx, y + (amp if up else -amp)))
        xx += step
        up = not up
    pts.append((x + w, y))
    for i in range(len(pts) - 1):
        pdf.line(*pts[i], *pts[i + 1])

def _curl_divider(pdf, x, y, w, col):
    pdf.set_draw_color(*col)
    pdf.set_line_width(0.5)
    n = max(3, int(w / 7))
    seg = w / n
    for i in range(n):
        x0 = x + i * seg
        up = -1.4 if i % 2 == 0 else 1.4
        pdf.bezier([(x0, y), (x0 + seg * 0.3, y + up), (x0 + seg * 0.7, y + up), (x0 + seg, y)])

def _hand_arrow(pdf, x, y, w, col, label=None, note_fam="note"):
    """A hand-drawn horizontal arrow, optionally with a label above."""
    pdf.set_draw_color(*col)
    pdf.set_line_width(0.6)
    mid = y + 1.2
    pdf.bezier([(x, y), (x + w * 0.3, y - 1.5), (x + w * 0.6, y + 2.5), (x + w, mid)])
    # arrowhead
    pdf.line(x + w, mid, x + w - 3.2, mid - 1.8)
    pdf.line(x + w, mid, x + w - 3.0, mid + 2.0)
    if label:
        pdf.set_font(note_fam, "", 9)
        pdf.set_text_color(*col)
        pdf.text(x + w / 2 - pdf.get_string_width(label) / 2, y - 2.2, label)

def _washi_tape(pdf, rng, x, y, w, h, base_col, rot=0):
    col = _mix(base_col, (255, 255, 255), rng.uniform(0.25, 0.45))
    with pdf.rotation(rot, x + w / 2, y + h / 2):
        with pdf.local_context(fill_opacity=0.65):
            pdf.set_fill_color(*col)
            pdf.rect(x, y, w, h, "F", round_corners=True, corner_radius=0.8)
        pdf.set_draw_color(*_mix(col, (255, 255, 255), 0.35))
        pdf.set_line_width(0.25)
        pdf.rect(x, y, w, h, "D", round_corners=True, corner_radius=0.8)

def _sticky_card(pdf, rng, x, y, w, h, theme, title, body, pen, size_body=9.5):
    tilt = rng.uniform(-1.6, 1.6)
    bg = theme.get("callout_bg", (250, 240, 215))
    edge = theme.get("callout_border", (210, 170, 90))
    with pdf.rotation(tilt, x + w / 2, y + h / 2):
        # shadow
        pdf.set_fill_color(*_mix(bg, (60, 70, 80), 0.18))
        pdf.rect(x + 1.2, y + 1.2, w, h, "F", round_corners=True, corner_radius=2.0)
        pdf.set_fill_color(*bg)
        pdf.set_draw_color(*edge)
        pdf.set_line_width(0.4)
        pdf.rect(x, y, w, h, "FD", round_corners=True, corner_radius=2.0)
        # folded corner
        pdf.set_fill_color(*_mix(bg, (255, 255, 255), 0.55))
        pdf.polygon([(x + w - 7, y + h), (x + w, y + h - 7), (x + w - 7, y + h - 7)], "F")
        pdf.set_draw_color(*edge)
        pdf.line(x + w - 7, y + h, x + w, y + h - 7)
        # pin dot
        pdf.set_fill_color(*theme.get("accent", (200, 60, 60)))
        pdf.ellipse(x + w / 2 - 1.1, y - 1.1, 2.2, 2.2, "F")
    # text drawn OUTSIDE the rotated context (nested rotation eats text)
    ty = y + 5.5
    if title:
        pdf.set_font("note", "B", 10.5)
        pdf.set_text_color(*theme.get("heading1", (180, 60, 60)))
        pdf.text(x + 6, ty, title)
        ty += 6
    if body:
        pen.para(body, x + 6, ty, size_body, theme.get("body", (60, 60, 60)),
                 set(), max_w=w - 12, kw_color=theme.get("heading1", (60, 60, 60)))

class NoteDoc(FPDF):
    def __init__(self, theme, title, seed=None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.theme = theme
        self.doc_title = title
        seed_txt = f"{title}|{seed or ''}"
        self.rng = random.Random(int(hashlib.md5(seed_txt.encode()).hexdigest(), 16))
        self.pen = Pen(self, self.rng, theme)
        self.hl_terms = set()
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(False)
        for fam, path in FONT_FILES.items():
            if os.path.isfile(path):
                self.add_font(fam, "", path)
        # family style aliases
        self.add_font("caveat", "B", FONT_FILES["caveatb"])
        self.add_font("hand", "B", FONT_FILES["handb"])
        self.add_font("note", "B", FONT_FILES["handb"])

    # ---- furniture ---------------------------------------------------------
    def _paper(self):
        t = self.theme
        self.set_fill_color(*t["paper"])
        self.rect(0, 0, self.w, self.h, "F")
        # ruled lines, slightly wavy via dash pattern
        self.set_draw_color(*t["rule_line"])
        self.set_line_width(0.18)
        self.set_dash_pattern(dash=1.4, gap=2.2)
        y = 26
        while y < self.h - 18:
            self.line(12, y, self.w - 11, y)
            y += 7.8
        self.set_dash_pattern()
        # left margin line
        self.set_draw_color(*_mix(t["rule_line"], t.get("accent", (200, 80, 80)), 0.4))
        self.set_line_width(0.35)
        self.line(22, 14, 22, self.h - 16)

    def header(self):
        if self.page_no() == 1:
            return
        self._paper()
        self.set_font("hand", "", 9)
        self.set_text_color(*_mix(self.theme["ink"], self.theme["paper"], 0.35))
        self.set_xy(30, 8)
        self.cell(0, 6, self.doc_title[:56], align="R")

    def footer(self):
        x = self.w / 2 - 4.5
        y = self.h - 12
        with self.rotation(self.rng.uniform(-4, 4), x + 4.5, y + 3):
            self.set_draw_color(*self.theme.get("divider", (150, 150, 150)))
            self.set_line_width(0.4)
            self.ellipse(x, y, 9.5, 7, "D")
            self.set_font("caveat", "", 11)
            self.set_text_color(*self.theme.get("heading2", (90, 90, 90)))
            self.text(x + 3.4, y + 5.2, str(self.page_no()))

    # ---- helpers -----------------------------------------------------------
    def ensure(self, h):
        if self.get_y() + h > self.h - 20:
            self.add_page()
            self.set_y(28)

    def _kw_prefix(self, hl):
        self.hl_terms = {w.lower() for w in (hl or [])}

    def _highlight(self, x, y, w, h, opacity=None):
        col = self.theme.get("highlight", (255, 235, 150))
        op = opacity if opacity is not None else self.theme.get("highlight_opacity", 0.45)
        with self.local_context(fill_opacity=op):
            self.set_fill_color(*col)
            self.rect(x, y, w, h, "F", round_corners=True, corner_radius=1.2)

    # ---- cover -------------------------------------------------------------
    def cover(self, subtitle=None):
        t, rng = self.theme, self.rng
        self.add_page()
        self._paper()
        self.set_y(30)
        # washi tape top corners
        _washi_tape(self, rng, 12, 8, 34, 10, t.get("bullet", (90, 140, 200)), rot=-6)
        _washi_tape(self, rng, self.w - 48, 10, 34, 10, t.get("accent", (200, 90, 90)), rot=5)
        # crossed-out decorative word then real label
        self.set_font("caveat", "", 15)
        self.set_text_color(*_mix(t["ink"], t["paper"], 0.45))
        self.set_xy(24, 26)
        self.cell(0, 8, "typed boring notes")
        wtxt = "typed boring notes"
        self.set_draw_color(*t.get("accent", (200, 60, 60)))
        self.set_line_width(0.7)
        self.line(24.5, 30.5, 24.5 + self.get_string_width(wtxt) + 1, 29.2)
        self.set_font("caveat", "B", 13)
        self.set_text_color(*t.get("heading1", (180, 60, 60)))
        self.text(24.5 + self.get_string_width(wtxt) + 4, 28.5, "-> my notes!")
        # big title with highlighter swipe
        title = self.doc_title
        size = 34 if self.get_string_width(title) < 90 else 27
        self.set_font("caveat", "B", size)
        tw = self.get_string_width(title)
        x0 = 24
        y0 = 52
        self._highlight(x0 - 2, y0 - 2, min(tw + 6, self.w - x0 - 20), size * 0.5)
        self.pen.word(title, x0, y0, "caveatb", size, t["title_text"], rot=rng.uniform(-0.8, 0.4))
        _squiggle(self, x0 + 2, y0 + size * 0.62, min(tw - 4, self.w - x0 - 26), t["heading1"], amp=1.6)
        # sparkles (kept clear of the title, top-right zone)
        for _ in range(3):
            _sparkle(self, rng.uniform(self.w - 70, self.w - 22), rng.uniform(34, 47),
                     t.get("accent", (200, 90, 90)), rng.uniform(1.2, 2.2))
        # subtitle / source + date
        if subtitle:
            self.pen.para(subtitle[:120], x0 + 2, y0 + 27, 11, _mix(t["ink"], t["paper"], 0.2), set(), max_w=self.w - 70)
        self.set_font("hand", "", 10)
        self.set_text_color(*_mix(t["ink"], t["paper"], 0.3))
        self.set_xy(-60, self.h - 34)
        self.cell(0, 6, f"~ {date.today().strftime('%d %b %Y')} ~", align="R")
        # start content on fresh page
        self.add_page()
        self.set_y(28)

    # ---- content blocks ----------------------------------------------------
    def section(self, heading, hl_terms=None):
        t = self.theme
        self._kw_prefix(hl_terms)
        self.ensure(18)
        y = self.get_y() + 2
        size = 19 if len(heading) < 46 else 16
        self.set_font("caveat", "B", size)
        tw = min(self.get_string_width(heading), self.w - 70)
        # soft marker band behind the heading
        self._highlight(26, y - 1, tw + 8, size * 0.5)
        self.set_text_color(*t["title_text"])
        self.pen.word(heading, 28, y, "caveatb", size, t["title_text"],
                      rot=self.rng.uniform(-0.6, 0.6))
        _squiggle(self, 28, y + size * 0.62, tw, t["heading1"], amp=1.4, step=2.6)
        _sparkle(self, 28 + tw + 6, y + size * 0.3, t.get("accent", (200, 90, 90)), 1.8)
        self.set_y(y + size * 0.62 + 3)

    def bullet(self, text, level=0, hl_terms=None):
        t = self.theme
        self._kw_prefix(hl_terms)
        size = 10.5 if level == 0 else 9.5
        line_h = size * 0.52
        x_text = 34 + level * 6
        self.ensure(line_h * 2 + 2)
        y = self.get_y()
        # hand-drawn bullet dot
        col = t["bullet"] if level == 0 else t.get("accent", t["bullet"])
        self.set_fill_color(*col)
        self.ellipse(25 + level * 6, y + 1.0, 2.6, 2.4, "F")
        used_h, _ = self.pen.para(text, x_text, y, size, t["body"], self.hl_terms,
                                  max_w=self.w - x_text - 16,
                                  kw_color=t.get("accent", t["body"]))
        self.set_y(y + max(used_h, line_h) + 1.6)

    def para(self, text, hl_terms=None):
        t = self.theme
        self._kw_prefix(hl_terms)
        size = 10.5
        line_h = size * 0.52
        self.ensure(line_h * 2 + 2)
        y = self.get_y()
        used_h, _ = self.pen.para(text, 30, y, size, t["body"], self.hl_terms,
                                  max_w=self.w - 46,
                                  kw_color=t.get("accent", t["body"]))
        self.set_y(y + used_h + 2.4)

    def key(self, term, desc, hl_terms=None):
        t = self.theme
        self._kw_prefix(hl_terms or [term])
        self.set_font("hand", "", 10)
        body_wrapped = self._wrap_count(desc, 10, self.w - 76)
        h = 10 + body_wrapped * (9.5 * 0.52)
        self.ensure(h + 6)
        y = self.get_y() + 1.5
        _sticky_card(self, self.rng, 28, y, self.w - 66, h, t, term + ":", desc,
                     self.pen, size_body=9.5)
        self.set_y(y + h + 5)

    def arrow_flow(self, parts, hl_terms=None):
        t = self.theme
        self._kw_prefix(hl_terms or set())
        self.ensure(16)
        y = self.get_y() + 2
        x = 28
        max_label_w = 26
        col = t.get("arrow_color", t["bullet"])
        self.set_font("note", "", 9)
        for i, part in enumerate(parts):
            w = min(self.get_string_width(part) + 4, max_label_w + 14)
            # rounded box
            self.set_fill_color(*_mix(t["callout_bg"], t["paper"], 0.35))
            self.set_draw_color(*col)
            self.set_line_width(0.45)
            self.rect(x, y - 1, w, 10, "FD", round_corners=True, corner_radius=3)
            self.set_text_color(*t["body"])
            self.text(x + 2, y + 6, part[:30])
            x += w
            if i < len(parts) - 1:
                _hand_arrow(self, x + 1, y + 3.5, 9, col)
                x += 11
            if x > self.w - 40 and i < len(parts) - 1:
                x = 40
                y += 14
                self.ensure(16)
        self.set_y(y + 14)

    def divider(self):
        if self.get_y() > self.h - 34:
            return
        self.ln(2)
        _curl_divider(self, 40, self.get_y() + 1.5, self.w - 84,
                      self.theme.get("divider", (150, 150, 150)))
        self.set_y(self.get_y() + 6)

    def _wrap_count(self, text, size, max_w):
        self.set_font("hand", "", size)
        words = text.split()
        lines, cur = 1, 0.0
        space = self.get_string_width(" ") or 1.2
        for w in words:
            ww = self.get_string_width(w)
            if cur + ww > max_w:
                lines += 1
                cur = ww
            else:
                cur += ww + space
        return lines

    # ---- main entry --------------------------------------------------------
    def render(self, blocks):
        """blocks: list of tuples (kind, *payload) produced by make_notes."""
        for b in blocks:
            kind = b[0]
            if kind == "h2":
                self.section(b[1], b[2] if len(b) > 2 else None)
            elif kind == "bullet":
                self.bullet(b[1], level=b[2] if len(b) > 2 else 0,
                            hl_terms=b[3] if len(b) > 3 else None)
            elif kind == "para":
                self.para(b[1], b[2] if len(b) > 2 else None)
            elif kind == "key":
                self.key(b[1], b[2], b[3] if len(b) > 3 else None)
            elif kind == "arrow":
                self.arrow_flow(b[1], b[2] if len(b) > 2 else None)
            elif kind == "divider":
                self.divider()
        self.divider()

def build(theme_name, title, blocks, out_path, subtitle=None, cover=True, seed=None):
    """Full pipeline: theme + title + blocks -> PDF at out_path."""
    theme = load_theme(theme_name)
    doc = NoteDoc(theme, title, seed=seed)
    doc.hl_all = None
    if cover:
        doc.cover(subtitle=subtitle)
    else:
        doc.add_page()
        doc.set_y(28)
    doc.render(blocks)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    doc.output(out_path)
    return out_path

def list_themes():
    with open(THEMES_FILE, encoding="utf-8") as f:
        return list(json.load(f).keys())
