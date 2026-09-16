"""tests_smoke.py — offline smoke tests for PDF Write Studio.

Run:  python tests_smoke.py
No browser / Streamlit server needed: exercises the editing engine, the
pagewrite overlay plumbing and the custom component files.
"""

import json
import os
import struct
import tempfile
import zlib

import fitz

import pdf_editor
from pdf_editor import PDFEditor

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL"), name, extra)


def make_sample_pdf(path, pages=3):
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((72, 100), f"Sample heading page {i + 1}",
                       fontsize=18, fontname="hebo")
        pg.insert_text((72, 140), "The quick brown fox jumps over the lazy dog.",
                       fontsize=11)
        pg.insert_text((72, 160), "Editable body text for find and replace.",
                       fontsize=11)
    doc.save(path)
    doc.close()


def make_transparent_ink(path):
    """A small transparent PNG with a black diagonal stroke."""
    W = H = 40
    rows = []
    for y in range(H):
        row = bytearray([0])  # filter type 0
        for x in range(W):
            on = abs(x - y) < 2
            row += bytes((0, 0, 0, 255 if on else 0))
        rows.append(bytes(row))
    raw = b"".join(rows)
    comp = zlib.compress(raw)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", comp) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def _data_url_of(path):
    import base64
    return ("data:image/png;base64," +
            base64.b64encode(open(path, "rb").read()).decode())


def main():
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "sample.pdf")
    make_sample_pdf(src)

    ed = PDFEditor(src)
    check("open: page_count", ed.page_count == 3)
    w, h = ed.page_size(1)
    check("page_size in points", abs(w - 595) < 1 and abs(h - 842) < 1,
          f"{w:.0f}x{h:.0f}")

    # --- whole-page ink overlay (the pagewrite path) ------------------------
    overlay = os.path.join(tmp, "ink.png")
    make_transparent_ink(overlay)
    ed.add_page_ink(1, overlay)
    check("add_page_ink recorded", ed.layer_count(1) == 1)

    # --- object tools -------------------------------------------------------
    ed.add_text(1, "handwritten!", 72, 200, size=14, font="hand")
    ed.add_sticky(1, "remember this", 380, 90, w=140, h=80)
    ed.add_shape(1, "rect", 72, 220, 120, 50, fill=True)
    ed.add_highlight(1, 72, 132, 200, 14)
    ed.add_whiteout(1, 72, 150, 180, 12)
    ed.replace_text(2, "fox", "cat", font="hand")
    ed.erase_text(2, "Editable body text")
    check("object layers", ed.layer_count(1) == 6 and ed.layer_count(2) == 2)

    # --- undo ---------------------------------------------------------------
    ok = ed.undo()  # pops erase_text
    check("undo pops layer", ok and ed.layer_count(2) == 1)

    # --- previews / composite ----------------------------------------------
    raw_png = ed.render_raw_preview(1, dpi=72)
    prev_png = ed.render_preview(1, dpi=72)
    check("raw preview is PNG", raw_png[:8] == b"\x89PNG\r\n\x1a\n")
    check("overlay preview is PNG", prev_png[:8] == b"\x89PNG\r\n\x1a\n")
    check("preview differs from raw", prev_png != raw_png)

    # ink pixels actually present on the composited page
    doc = ed._composited()
    pix = doc[0].get_pixmap(dpi=72)  # 595x842 px == point space
    # the 40px overlay's diagonal is stretched to the full-page diagonal
    samples = []
    for t in (0.25, 0.5, 0.75):
        cx, cy = int(t * 594), int(t * 841)
        for dx, dy in ((0, 0), (1, 1), (2, 2), (-1, -1), (3, 3)):
            samples.append(pix.pixel(min(594, cx + dx), min(841, cy + dy)))
    inkish = any(sum(p[:3]) < 3 * 200 for p in samples)
    check("ink visible on composited page", inkish, str(samples[:3]))
    doc.close()

    # --- page ops -----------------------------------------------------------
    ed.rotate_page(1, 90)
    ed.duplicate_page(3)        # LAST page -> exercises the move-to-end path
    check("duplicate last page", ed.page_count == 4)
    ed.insert_blank_page(3)
    ed.move_page(2, 1)
    check("page ops change count", ed.page_count == 5, str(ed.page_count))
    ed.delete_page(5)
    check("delete page", ed.page_count == 4)

    # --- save ---------------------------------------------------------------
    out = os.path.join(tmp, "edited.pdf")
    ed.save(out)
    check("save writes file",
          os.path.isfile(out) and os.path.getsize(out) > 1000)
    redoc = fitz.open(out)
    check("saved doc opens", redoc.page_count == 4)
    txt = redoc[0].get_text()  # orig page 2 was moved to the front
    check("replace landed", "cat" in txt and "fox" not in txt)
    redoc.close()
    ed.close()

    # --- pagewrite plumbing --------------------------------------------------
    import pagewrite
    check("component frontend exists", pagewrite.available())
    html = open(os.path.join(os.path.dirname(pagewrite.__file__),
                             "frontend", "index.html"),
                encoding="utf-8").read()
    check("frontend speaks protocol",
          "streamlit:componentReady" in html and
          "streamlit:setComponentValue" in html and
          "streamlit:render" in html)
    check("frontend has page selector", 'id="pgsel"' in html)
    check("ink payload uses action keys",
          'action: "ink"' in html and 'action: "nav"' in html)

    payload = json.dumps({
        "action": "ink", "png": _data_url_of(overlay),
        "page": 0, "pw": 595, "ph": 842, "sx": 2.0, "sy": 2.0,
        "strokes": 2, "seq": 7,
    })
    p, sx, sy = pagewrite.save_overlay(payload)
    check("save_overlay persists PNG",
          p is not None and os.path.isfile(p) and abs(sx - 2.0) < 1e-9)
    p2, _, _ = pagewrite.save_overlay(
        json.dumps({"action": "ink", "png": "data:text/html,x"}))
    check("save_overlay rejects junk", p2 is None)
    nav = pagewrite.parse(json.dumps({"action": "nav", "page": 2, "seq": 3}))
    check("parse nav payload",
          nav.get("action") == "nav" and nav.get("page") == 2)
    check("parse None", pagewrite.parse(None) == {})
    pagewrite.clear_overlays(keep=3)

    # --- library helpers ------------------------------------------------------
    found = pdf_editor.list_editable_pdfs(extra_dir=tmp)
    check("list_editable_pdfs finds sample",
          any(f.endswith("edited.pdf") for f in found), f"{len(found)} files")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

