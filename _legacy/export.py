"""export.py — extra output formats: PNG pages, HTML gallery, DOCX, Anki, merge."""

import base64
import os

import fitz


def pdf_to_pngs(pdf_path, out_dir=None, dpi=110):
    out_dir = out_dir or (os.path.dirname(pdf_path) + "_pngs")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    paths = []
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc):
        p = os.path.join(out_dir, f"{stem}_p{i + 1}.png")
        page.get_pixmap(dpi=dpi).save(p)
        paths.append(p)
    doc.close()
    return paths


def to_html(pdf_path, out_dir=None):
    """Pages embedded into a single self-contained HTML file."""
    out_dir = out_dir or os.path.dirname(pdf_path)
    pngs = pdf_to_pngs(pdf_path, out_dir, dpi=90)
    imgs = []
    for p in pngs:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        imgs.append(f'<img style="max-width:760px" src="data:image/png;base64,{b64}">')
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    html_path = os.path.join(out_dir, f"{stem}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{stem}</title><style>body{{background:#f7f5f1;display:flex;"
                "flex-direction:column;align-items:center;margin:20px}}"
                "img{box-shadow:0 6px 18px rgba(0,0,0,.15);border-radius:10px;margin:14px}"
                "</style></head><body>" + "".join(imgs) + "</body></html>")
    return html_path, pngs


def anki_deck(cards, path):
    """cards: list of (front, back) -> Anki-importable UTF-16 TSV."""
    rows = []
    for front, back in cards:
        frow = str(front).replace("\t", " ").replace("\n", " ")
        brow = str(back).replace("\t", " ").replace("\n", " ")
        rows.append(f"{frow}\t{brow}")
    with open(path, "w", encoding="utf-16") as f:
        f.write("\n".join(rows) + "\n")
    return path


def to_docx(title, items, path):
    """items: make_notes item stream -> clean Word document."""
    from docx import Document
    doc = Document()
    doc.add_heading(title, level=0)
    for it in items:
        if it[0] == "h":
            doc.add_heading(it[2], level=2 if it[1] == 2 else 1)
        elif it[0] == "key":
            doc.add_paragraph(f"{it[1]}: {it[2]}", style="Quote")
        elif it[0] == "arrow":
            doc.add_paragraph(" -> ".join(it[1]))
        else:
            doc.add_paragraph(str(it[1]), style="List Bullet")
    doc.save(path)
    return path


def merge_pdfs(paths, out_path):
    out = fitz.open()
    for p in paths:
        src = fitz.open(p)
        out.insert_pdf(src)
        src.close()
    out.save(out_path)
    out.close()
    return out_path