"""ocr.py — optional OCR for scanned PDFs via RapidOCR (pure Python, offline).
Importable even when rapidocr is missing; functions report availability.
"""

_ENGINE = None


def ocr_available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_image(path):
    """Run OCR on an image file. Returns recognized text or ''."""
    try:
        res, _ = _engine()(path)
    except Exception:
        return ""
    if not res:
        return ""
    return "\n".join(str(ln[1]) for ln in res if len(ln) > 1)


def ocr_pdf(pdf_path, max_pages=60):
    """Fallback for scanned PDFs: renders pages to temp PNGs and OCRs them.
    Only runs on pages that have no extractable text."""
    import tempfile
    import fitz
    from make_notes import _clean

    out_lines = []
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        if page.get_text().strip():
            continue
        pix = page.get_pixmap(dpi=200)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        pix.save(tmp_path)
        text = ocr_image(tmp_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        for line in text.splitlines():
            c = _clean(line)
            if c:
                out_lines.append(("p", c))
    doc.close()
    return out_lines