"""pdf_editor.py - Section 3: Visual PDF Editor.

Opens any PDF (typically one of our generated note PDFs) and lets you edit it
with **true vector overlays** drawn natively by PyMuPDF - no rasterisation, so
text stays sharp at any zoom and the files stay small.

Supported edits
---------------
  text      insert handwritten text anywhere (uses the note fonts)
  replace   find text and swap it for new text (true redact + rewrite)
  erase     find text and remove it (true redaction)
  image     stamp an image (photo, diagram, screenshot) anywhere
  sticky    add a coloured sticky note with text
  shape     rectangle / oval / arrow / line
  draw      freehand stroke through a list of points
  whiteout  blank out an area
  pages     rotate / delete / move / duplicate / insert blank

Edits are kept as an overlay list, so preview and save are always consistent
and the source PDF on disk is never modified until you call ``save()``.
"""

import glob
import os

import fitz  # PyMuPDF

import renderer

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "output")
NOTES_DIR = os.path.join(BASE, "notes")

# friendly label -> renderer font key
FONT_CHOICES = {
    "hand (Patrick Hand)": "hand",
    "note (Kalam)": "note",
    "kalam bold (Kalam-Bold)": "handb",
    "caveat (Caveat)": "caveat",
    "caveat bold (Caveat-Bold)": "caveatb",
}

INK = (45, 50, 60)
STICKY_COLORS = {
    "yellow": (255, 246, 200),
    "pink": (255, 224, 232),
    "blue": (219, 238, 255),
    "green": (223, 246, 226),
}


def _rgb(c):
    """(r, g, b) 0-255 -> PyMuPDF float tuple."""
    return tuple(max(0.0, min(1.0, v / 255.0)) for v in c[:3])


def _font(name):
    """Return a fitz.Font for a renderer font key, with safe fallbacks."""
    path = renderer.FONT_FILES.get(name) or renderer.FONT_FILES.get("hand")
    try:
        return fitz.Font(fontfile=path)
    except Exception:
        try:
            return fitz.Font("helv")
        except Exception:
            return fitz.Font()


def _wrap(text, width, max_lines):
    """Tiny word-wrapper used for sticky notes."""
    out, line = [], ""
    for word in str(text).split():
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += " " + word
        else:
            out.append(line)
            line = word
        if len(out) >= max_lines:
            break
    if line and len(out) < max_lines:
        out.append(line)
    return out or [""]


def _arrow_head(page, p1, p2, color, bw):
    import math
    ang = math.atan2(p2.y - p1.y, p2.x - p1.x)
    ln = 7.0
    for off in (math.radians(155), math.radians(-155)):
        page.draw_line(p2, fitz.Point(p2.x + ln * math.cos(ang + off),
                                      p2.y + ln * math.sin(ang + off)),
                       color=color, width=bw)


class EditLayer:
    """A single overlay element on a page."""

    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.data = kwargs


class PDFEditor:
    """Load a PDF, record overlay edits per page, write a new PDF."""

    def __init__(self, src_path):
        if not os.path.isfile(src_path):
            raise FileNotFoundError(src_path)
        self.src_path = src_path
        self.doc = fitz.open(src_path)
        self.page_count = self.doc.page_count
        self.layers = [[] for _ in range(self.page_count)]
        self.undo_stack = []

    # ---- text -------------------------------------------------------------
    def add_text(self, page, text, x, y, size=12.0, color=None,
                 font="hand", rotation=0.0):
        self._add(page, EditLayer("text", text=text, x=x, y=y, size=size,
                                  color=color or INK, font=font,
                                  rotation=rotation))

    def replace_text(self, page, find, replacement, size=None,
                     color=None, font="hand"):
        """Find every occurrence of `find` and swap it for `replacement`."""
        self._add(page, EditLayer("replace", find=find, text=replacement,
                                  size=size, color=color or INK, font=font))

    def erase_text(self, page, find):
        """Remove every occurrence of `find` (true redaction)."""
        self._add(page, EditLayer("erase", find=find))

    # ---- media ------------------------------------------------------------
    def add_image(self, page, img_path, x, y, w=None, h=None):
        self._add(page, EditLayer("image", path=img_path, x=x, y=y, w=w, h=h))

    def add_sticky(self, page, text, x, y, w=60, h=34, color=None,
                   font="note", size=8.5):
        self._add(page, EditLayer("sticky", text=text, x=x, y=y, w=w, h=h,
                                  color=color or STICKY_COLORS["yellow"],
                                  font=font, size=size))

    def add_shape(self, page, shape, x, y, w, h, color=None, fill=False,
                  bw=0.8):
        self._add(page, EditLayer("shape", shape=shape, x=x, y=y, w=w, h=h,
                                  color=color or (90, 90, 90), fill=fill,
                                  bw=bw))

    def add_highlight(self, page, x, y, w, h, color=None):
        self._add(page, EditLayer("highlight", x=x, y=y, w=w, h=h,
                                  color=color or (255, 235, 130)))

    def add_board(self, page, img_path, x=None, y=None, w=None, h=None,
                  full_page=True, margin=30.0):
        """Stamp a whiteboard PNG onto the page.

        full_page=True (default): centre it as a ruled board sheet inset by
        *margin* points. Otherwise place at (x, y) with width w / height h.
        """
        if full_page:
            r = self.doc[self._check(page)].rect
            self._add(page, EditLayer("board", img=img_path, x=r.x0 + margin,
                                      y=r.y0 + margin,
                                      w=r.width - 2 * margin,
                                      h=r.height - 2 * margin))
        else:
            self._add(page, EditLayer("board", img=img_path, x=x, y=y,
                                      w=w, h=h))

    def add_whiteout(self, page, x, y, w, h, erase=False):
        self._add(page, EditLayer("whiteout", x=x, y=y, w=w, h=h, erase=erase))

    def add_drawing(self, page, points, color=None, bw=0.9):
        self._add(page, EditLayer("draw", points=list(points),
                                  color=color or INK, bw=bw))

    # ---- page operations --------------------------------------------------
    def rotate_page(self, page, degrees=90):
        idx = self._check(page)
        cur = self.doc[idx].rotation
        self.undo_stack.append(("rotate", idx, cur))
        self.doc[idx].set_rotation((cur + degrees) % 360)

    def delete_page(self, page):
        if self.page_count <= 1:
            raise ValueError("Cannot delete the only page.")
        idx = self._check(page)
        self.undo_stack.append(("delete", idx, self.layers[idx]))
        self.doc.delete_page(idx)
        self.layers.pop(idx)
        self.page_count = self.doc.page_count

    def move_page(self, page, to_page):
        idx, to = self._check(page) - 1, self._check(to_page) - 1
        if idx == to:
            return
        self.undo_stack.append(("move", idx, to))
        self.doc.move_page(idx, to)
        layer = self.layers.pop(idx)
        self.layers.insert(to, layer)

    def duplicate_page(self, page):
        idx = self._check(page)
        self.doc.fullcopy_page(idx, idx + 1)
        self.layers.insert(idx + 1, [])
        self.page_count = self.doc.page_count
        self.undo_stack.append(("duplicate", idx))

    def insert_blank_page(self, page):
        idx = self._check(page)
        r = self.doc[0].rect
        self.doc.new_page(pno=idx, width=r.width, height=r.height)
        self.layers.insert(idx, [])
        self.page_count = self.doc.page_count
        self.undo_stack.append(("blank", idx))

    # ---- internals --------------------------------------------------------
    def _check(self, page):
        if page < 1 or page > self.page_count:
            raise ValueError(f"page {page} out of range (1..{self.page_count})")
        return page - 1

    def _add(self, page, layer):
        idx = self._check(page)
        self.undo_stack.append(("add", idx, len(self.layers[idx])))
        self.layers[idx].append(layer)

    def undo(self):
        """Undo the last overlay/page edit. True if something was undone."""
        if not self.undo_stack:
            return False
        op = self.undo_stack.pop()
        if op[0] == "add":
            idx, pos = op[1], op[2]
            if pos < len(self.layers[idx]):
                self.layers[idx].pop(pos)
        elif op[0] == "rotate":
            idx, prev = op[1], op[2]
            if idx < self.doc.page_count:
                self.doc[idx].set_rotation(prev)
        elif op[0] == "move":
            idx, to = op[1], op[2]
            self.doc.move_page(to, idx)
            layer = self.layers.pop(to)
            self.layers.insert(idx, layer)
        else:
            return False  # delete / duplicate / blank are not reversible
        return True

    def page_size(self, page):
        """(width, height) of a page in PDF points."""
        rect = self.doc[self._check(page)].rect
        return rect.width, rect.height

    def page_text(self, page, max_chars=4000):
        return self.doc[self._check(page)].get_text()[:max_chars]

    def find_text(self, page, needle):
        """Bounding boxes (x0, y0, x1, y1) where `needle` appears on `page`."""
        if not needle:
            return []
        return [tuple(r) for r in
                self.doc[self._check(page)].search_for(needle)]

    def layer_count(self, page):
        return len(self.layers[self._check(page)])

    def clear_page(self, page):
        self.layers[self._check(page)] = []

    # ---- drawing engine ---------------------------------------------------
    def _write_text(self, page, text, x, y, size, color, font, rotation=0.0):
        fnt = _font(font)
        tw = fitz.TextWriter(page.rect)
        tw.append(fitz.Point(x, y), text, font=fnt, fontsize=size)
        if abs(rotation) > 0.01:
            tw.write_text(page, color=_rgb(color),
                          morph=(fitz.Point(x, y),
                                 fitz.Matrix(1, 1).prerotate(rotation)))
        else:
            tw.write_text(page, color=_rgb(color))

    def _draw_layer(self, page, layer):
        d, k = layer.data, layer.kind

        if k == "text":
            size = d["size"]
            for i, line in enumerate(str(d["text"]).split("\n")):
                self._write_text(page, line, d["x"],
                                 d["y"] + i * size * 1.32, size, d["color"],
                                 d.get("font", "hand"), d.get("rotation", 0.0))

        elif k in ("replace", "erase"):
            rects = page.search_for(d["find"]) if d.get("find") else []
            if not rects:
                return
            for r in rects:
                page.add_redact_annot(r, fill=(1, 1, 1))
            _apply_redactions(page)
            if k == "replace" and str(d.get("text", "")).strip():
                r0 = fitz.Rect(rects[0])
                size = d.get("size") or max(6.0, min(12.0, r0.height * 0.78))
                self._write_text(page, str(d["text"]), r0.x0,
                                 r0.y1 - r0.height * 0.16, size,
                                 d.get("color", INK), d.get("font", "hand"))

        elif k == "image":
            path = d.get("path")
            if not path or not os.path.isfile(path):
                return
            w, h = d.get("w"), d.get("h")
            if not (w and h):
                try:
                    pm = fitz.Pixmap(path)
                    ratio = pm.height / float(pm.width or 1)
                    w = w or 160.0
                    h = h or w * ratio
                except Exception:
                    w, h = 160.0, 120.0
            rect = fitz.Rect(d["x"], d["y"], d["x"] + w, d["y"] + h)
            try:
                page.insert_image(rect, filename=path, keep_proportion=True)
            except Exception:
                pass

        elif k == "sticky":
            _draw_sticky(page, d, self._write_text)

        elif k == "shape":
            _draw_shape(page, d)

        elif k == "highlight":
            page.draw_rect(fitz.Rect(d["x"], d["y"], d["x"] + d["w"],
                                     d["y"] + d["h"]),
                           color=None, fill=_rgb(d["color"]),
                           fill_opacity=0.42)

        elif k == "whiteout":
            rect = fitz.Rect(d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"])
            if d.get("erase"):
                page.add_redact_annot(rect, fill=(1, 1, 1))
                _apply_redactions(page)
            else:
                page.draw_rect(rect, color=None, fill=(1, 1, 1))

        elif k == "draw":
            pts = [fitz.Point(p[0], p[1]) for p in d["points"]]
            if len(pts) >= 2:
                page.draw_polyline(pts, color=_rgb(d["color"]),
                                   width=d.get("bw", 0.9))
            elif len(pts) == 1:
                r = d.get("bw", 0.9) / 2.0
                page.draw_circle(pts[0], r, color=_rgb(d["color"]),
                                 fill=_rgb(d["color"]))

        elif k == "board":
            path = d.get("img")
            if not path or not os.path.isfile(path):
                return
            rect = fitz.Rect(d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"])
            self._draw_board_sheet(page, rect)
            try:
                inset = fitz.Rect(rect.x0 + 4, rect.y0 + 4,
                                  rect.x1 - 4, rect.y1 - 4)
                page.insert_image(inset, filename=path, keep_proportion=True)
            except Exception:
                pass

    def _draw_board_sheet(self, page, rect):
        """Ruled whiteboard sheet: white fill, teal border, faint rules."""
        page.draw_rect(rect, color=(0.18, 0.36, 0.38), fill=(1, 1, 1),
                       width=1.1)
        y = rect.y0 + 14
        while y < rect.y1 - 6:
            page.draw_line(fitz.Point(rect.x0 + 6, y),
                           fitz.Point(rect.x1 - 6, y),
                           color=(0.75, 0.82, 0.82), width=0.35)
            y += 13

    def _composited(self):
        """A throwaway in-memory copy of the doc with all overlays applied."""
        tmp = fitz.open("pdf", self.doc.tobytes())
        for idx, layers in enumerate(self.layers):
            if idx >= tmp.page_count:
                continue
            pg = tmp[idx]
            for layer in layers:
                try:
                    self._draw_layer(pg, layer)
                except Exception:
                    continue
        return tmp

    # ---- preview / save ---------------------------------------------------
    def render_raw_preview(self, page, dpi=90):
        """PNG bytes of the page with no overlays."""
        return self.doc[self._check(page)].get_pixmap(dpi=dpi).tobytes("png")

    def render_preview(self, page, dpi=90):
        """PNG bytes of the page with every overlay applied."""
        idx = self._check(page)
        if not self.layers[idx]:
            return self.render_raw_preview(page, dpi)
        tmp = self._composited()
        try:
            return tmp[idx].get_pixmap(dpi=dpi).tobytes("png")
        finally:
            tmp.close()

    def save(self, out_path):
        """Write the edited PDF. The source file is never touched."""
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = self._composited()
        try:
            tmp.save(out_path, garbage=3, deflate=True)
        finally:
            tmp.close()
        return out_path

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---- overlay drawing helpers ---------------------------------------------

def _apply_redactions(page):
    """apply_redactions() changed signature across PyMuPDF versions."""
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    except TypeError:
        page.apply_redactions()


def _draw_sticky(page, d, write_text):
    x, y, w, h = d["x"], d["y"], d["w"], d["h"]
    # soft drop shadow
    page.draw_rect(fitz.Rect(x + 1.5, y + 1.5, x + w + 1.5, y + h + 1.5),
                   color=None, fill=(0.72, 0.72, 0.72), fill_opacity=0.30)
    # card
    page.draw_rect(fitz.Rect(x, y, x + w, y + h),
                   color=_rgb((196, 180, 110)), fill=_rgb(d["color"]),
                   width=0.6)
    # folded bottom-right corner
    fold = min(9.0, w / 4.0, h / 3.0)
    page.draw_polyline([fitz.Point(x + w - fold, y + h),
                        fitz.Point(x + w, y + h - fold),
                        fitz.Point(x + w - fold, y + h - fold),
                        fitz.Point(x + w - fold, y + h)],
                       color=_rgb((196, 180, 110)), fill=(1, 1, 1), width=0.4)
    size = d.get("size") or 8.5
    cols = max(8, int((w - 8) / (size * 0.46)))
    ty = y + size + 2.0
    for line in _wrap(str(d["text"]), cols, 6):
        write_text(page, line, x + 4.0, ty, size, INK, d.get("font", "note"))
        ty += size * 1.3


def _draw_shape(page, d):
    x, y, w, h = d["x"], d["y"], d["w"], d["h"]
    rect = fitz.Rect(x, y, x + w, y + h)
    col = _rgb(d["color"])
    fill_col = col if d.get("fill") else None
    bw = d.get("bw", 0.8)
    shape = d["shape"]
    if shape == "rect":
        page.draw_rect(rect, color=col, fill=fill_col, width=bw)
    elif shape == "circle":
        page.draw_oval(rect, color=col, fill=fill_col, width=bw)
    elif shape == "arrow":
        p1, p2 = fitz.Point(x, y), fitz.Point(x + w, y + h)
        page.draw_line(p1, p2, color=col, width=bw)
        _arrow_head(page, p1, p2, col, bw)
    else:  # line
        page.draw_line(fitz.Point(x, y), fitz.Point(x + w, y + h),
                       color=col, width=bw)


# ---- library helpers ------------------------------------------------------

def list_output_pdfs(out_dir=None):
    """PDFs inside the output directory, newest first."""
    out_dir = out_dir or OUT_DIR
    if not os.path.isdir(out_dir):
        return []
    return sorted(glob.glob(os.path.join(out_dir, "*.pdf")),
                  key=os.path.getmtime, reverse=True)


def list_editable_pdfs(extra_dir=None):
    """Output PDFs plus any PDF the user dropped into notes/."""
    found = list(list_output_pdfs())
    for d in (NOTES_DIR, extra_dir):
        if d and os.path.isdir(d):
            for p in glob.glob(os.path.join(d, "*.pdf")):
                if p not in found:
                    found.append(p)
    return found