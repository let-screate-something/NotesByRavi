"""research.py — Section 1: Research & Compile.

Gathers information from multiple sources and compiles into structured markdown.
Sources: topic description (AI-researched), PDF files, TXT/MD files, URLs.
"""

import json
import os
import re
import urllib.request

import fitz  # PyMuPDF

import ocr
from ai_notes import ai_ready, load_config, _chat, _truncate

BASE = os.path.dirname(os.path.abspath(__file__))


def extract_pdf_text(path, max_pages=200):
    """Extract text from a PDF file using PyMuPDF + optional OCR.

    Image-only pages are rendered to a temp PNG and OCR'd (Windows-safe).
    """
    import tempfile

    doc = fitz.open(path)
    chunks = []
    tmp_path = None
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        text = page.get_text().strip()
        if not text and ocr.ocr_available():
            try:
                pix = page.get_pixmap(dpi=150)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name
                pix.save(tmp_path)
                text = ocr.ocr_image(tmp_path).strip()
            except Exception:
                text = ""
            finally:
                if tmp_path:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    tmp_path = None
        if text:
            chunks.append(text)
    doc.close()
    return "\n\n".join(chunks)


def fetch_url_text(url):
    """Simple URL text fetcher (no API key needed)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NotesStudio"})
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="ignore")
        # crude HTML-to-text: strip tags, scripts, styles
        raw = html
        raw = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw[:8000]
    except Exception as e:
        return f"[Could not fetch URL: {url} — {e}]"


def research_to_markdown(topic, pdf_files=None, txt_files=None, urls=None,
                         style="study_guide", extra_instructions="", cfg=None):
    """Compile research from all sources into structured markdown.

    - If AI is available: sends combined content to AI → rich markdown.
    - If AI not available: still combines text into a basic markdown.
    """
    pdf_files = pdf_files or []
    txt_files = txt_files or []
    urls = urls or []

    sources = []

    if topic.strip():
        sources.append(f"=== TOPIC ===\n{topic.strip()}")

    for pf in pdf_files:
        name = os.path.basename(pf)
        try:
            text = extract_pdf_text(pf)
            sources.append(f"=== FROM PDF: {name} ===\n{text[:6000] if text else '[no text extracted]'}")
        except Exception as e:
            sources.append(f"=== FROM PDF: {name} ===\n[error reading: {e}]")

    for tf in txt_files:
        name = os.path.basename(tf)
        try:
            with open(tf, encoding="utf-8", errors="ignore") as f:
                text = f.read().strip()
            sources.append(f"=== FROM FILE: {name} ===\n{text[:6000]}")
        except Exception as e:
            sources.append(f"=== FROM FILE: {name} ===\n[error: {e}]")

    for u in urls:
        text = fetch_url_text(u)
        sources.append(f"=== FROM URL: {u} ===\n{text[:6000]}")

    combined = "\n\n".join(sources)

    cfg = cfg or load_config()
    style_prompt = {
        "study_guide": "Create clean study notes with headings, bullet points, definitions, tips, and examples.",
        "bullet_summary": "Create concise bullet-point notes with key facts highlighted.",
        "deep_dive": "Create detailed explanatory notes with thorough explanations and context.",
    }.get(style, style)

    has_sources = bool(pdf_files or txt_files or urls)

    if ai_ready(cfg):
        # AI available — synthesize into structured markdown
        if has_sources:
            grounding = ("Do not invent information — use only what is in the "
                         "sources below.\n\n")
        else:
            grounding = (f"Use your own knowledge about this topic: "
                         f"{topic.strip()}.\n\n")
        prompt = (
            f"{style_prompt}\n\n"
            f"Extra instruction: {extra_instructions}\n\n"
            f"Organize content clearly. Use:\n"
            f"- '# Title' for the main title\n"
            f"- '## Section' for major sections\n"
            f"- '- bullet point' for key facts\n"
            f"- '**bold**' for important terms\n"
            f"- '>' blockquote for tips and warnings\n"
            f"{grounding}=== COMBINED SOURCES ===\n{combined}"
        )
        md = _chat(cfg, [
            {"role": "system", "content": "You are a research assistant. Compile notes into clean markdown."},
            {"role": "user", "content": _truncate(prompt, limit=12000)},
        ], max_tokens=4000)
        # strip markdown fences if AI added them
        md = re.sub(r"```[a-z]*\n", "", md.strip())
        md = re.sub(r"\n```$", "", md)
        return md.strip()
    else:
        # No AI — basic assembly into markdown
        md = f"# Research Notes: {topic[:60]}\n\n"
        md += "## Sources\n\n"
        if topic.strip():
            md += f"- Topic: {topic.strip()}\n"
        for pf in pdf_files:
            md += f"- PDF: {os.path.basename(pf)}\n"
        for tf in txt_files:
            md += f"- File: {os.path.basename(tf)}\n"
        for u in urls:
            md += f"- URL: {u}\n"
        md += "\n## Gathered Content\n\n"
        md += combined
        return md


def save_markdown(md_text, filename, notes_dir=None):
    """Save markdown text to a .md file in the notes folder."""
    notes_dir = notes_dir or os.path.join(BASE, "notes")
    os.makedirs(notes_dir, exist_ok=True)
    path = os.path.join(notes_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md_text)
    return path
