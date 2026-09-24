# 🖋 PDF Write Studio

Open **any PDF** and write directly **on the page** — with a digital pen,
stylus, touchscreen, or mouse. Every edit is a true vector overlay drawn by
[PyMuPDF](https://pymupdf.readthedocs.io/), so text stays razor-sharp at any
zoom, files stay small, and your **source PDF is never modified** — Save
always writes a new file.

## ✨ What you can do

| Area | Features |
|---|---|
| **Write on the page** | Whole-page writeable canvas (the page *is* the canvas) — pen / marker / highlighter / eraser, pressure-sensitive strokes, per-canvas undo & clear, in-canvas page selector |
| **Place objects** | Handwritten text (5 bundled handwriting fonts, rotation), sticky notes, images, shapes (rect / circle / arrow / line), highlight areas, whiteout (with optional true redaction) |
| **Edit text** | Find & replace (true redact + rewrite in a handwriting font), erase text, page text viewer |
| **Page tools** | Rotate, duplicate, insert blank, move, delete, undo stack, clear a page's edits |
| **Output** | Save-as + one-click download; previews with all overlays applied |

## 🚀 Run it

```powershell
pip install -r requirements.txt
streamlit run app.py          # or double-click  Start PDF Write Studio.bat
```

Then open a PDF from the sidebar (upload, or pick one from `output/` /
`notes/`), draw on the page, press **✅ Apply to PDF** on the canvas, and
**💾 Save** when you're done.

## 🗂 Project layout

```
app.py                  Streamlit UI (the whole editor)
pdf_editor.py           Vector-overlay editing engine (PyMuPDF)
pagewrite/              Whole-page writeable canvas custom component
  +-- __init__.py       Python wrapper (declare_component protocol)
  +-- frontend/         Static JS/HTML (pen input, no build step)
assets/fonts/           Handwriting TTFs used by the text tools
notes/                  Drop PDFs here to make them openable in the app
output/                 Saved edited PDFs (+ working dirs, gitignored)
```

## 🔧 How the ink lands exactly where you drew it

1. The current page is rendered to a PNG and set as the canvas background —
   so what you see is exactly where you write.
2. Your strokes are kept in the browser (no Streamlit reruns while drawing).
3. On **Apply**, a transparent ink-only PNG is sent to Python and stamped
   onto the page at its full rect in PDF points — a 1:1 mapping, so strokes
   land precisely and stay crisp when the PDF is zoomed or printed.

