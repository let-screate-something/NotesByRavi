"""Notes Studio — beautiful handwritten-style notes from PDFs, files or AI prompts.
Run:  streamlit run app.py
"""

import glob
import json
import os
import time

import fitz
import streamlit as st

import ai_notes
import export
from make_notes import build_blocks, extract_text, generate_notes
from renderer import list_themes, load_theme
from ocr import ocr_available

BASE = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(BASE, "notes")
OUT_DIR = os.path.join(BASE, "output")
THEMES_FILE = os.path.join(BASE, "themes.json")
HISTORY_FILE = os.path.join(OUT_DIR, "history.json")
os.makedirs(NOTES_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

PRESET_NAMES = {
    "Study guide": "study_guide",
    "Cheat sheet": "cheat_sheet",
    "Exam prep": "exam_prep",
    "Flashcards": "flashcards",
}
PRESET_HELP = {
    "Study guide": "Balanced notes with definitions & tips",
    "Cheat sheet": "Ultra-dense one-page cheat sheet",
    "Exam prep": "What to remember + common mistakes",
    "Flashcards": "Q&A cards (exportable to Anki)",
}

st.set_page_config(page_title="Notes Studio", page_icon="🎨", layout="wide")

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(160deg, #FDFCF8 0%, #EAF4F2 45%, #F6EFF8 100%);
        color: #2E3D48 !important;
    }
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp td, .stApp div {
        color: #2E3D48;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #35505E !important; }
    .stApp header { background: transparent; }
    .block-container {
        background: rgba(255, 255, 255, 0.72); border-radius: 18px;
        padding: 2rem 2.4rem 3rem 2.4rem; margin-top: 1rem;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #F6FAF8 0%, #EDF3F8 100%);
        border-right: 1px solid #E2E8EE;
    }
    section[data-testid="stSidebar"] * { color: #2E3D48; }
    .stApp textarea, .stApp input, div[data-baseweb="select"] > div,
    .stApp [data-testid="stFileUploaderDropzone"] {
        background-color: #FFFFFF !important; color: #2E3D48 !important; border-radius: 10px;
    }
    .stApp textarea::placeholder, .stApp input::placeholder { color: #7C8B96 !important; }
    div.stButton > button {
        border-radius: 12px !important; border: 1px solid #C9DDE2 !important; color: #2F4858 !important;
        background: linear-gradient(135deg, #D6ECE9, #E3EBFB) !important;
        font-weight: 600; padding: 0.45em 1.2em;
    }
    .stApp [data-baseweb="tab"] p { color: #5A6B78; }
    .stApp [aria-selected="true"] p { color: #2F4858 !important; font-weight: 700; }
    .stApp [data-testid="stAlertContainer"] * { color: #2E3D48 !important; }
    .stApp small, .stApp [data-testid="stCaptionContainer"] { color: #61707C !important; }
    .stApp img { border-radius: 10px; box-shadow: 0 2px 10px rgba(60,80,100,0.12); }
</style>
""", unsafe_allow_html=True)


def show_pdf(path, dpi=100):
    doc = fitz.open(path)
    n = doc.page_count
    if n == 1:
        st.image(doc[0].get_pixmap(dpi=dpi).tobytes("png"), width="stretch")
    else:
        pages = st.tabs([f"Page {i + 1}" for i in range(n)])
        for i, tab in enumerate(pages):
            with tab:
                st.image(doc[i].get_pixmap(dpi=dpi).tobytes("png"), width="stretch")
    doc.close()


def outputs_list():
    return sorted(glob.glob(os.path.join(OUT_DIR, "*.pdf")),
                  key=os.path.getmtime, reverse=True)


def log_history(record):
    hist = []
    if os.path.isfile(HISTORY_FILE):
        try:
            hist = json.load(open(HISTORY_FILE, encoding="utf-8"))
        except Exception:
            hist = []
    hist.insert(0, record)
    json.dump(hist[:200], open(HISTORY_FILE, "w", encoding="utf-8"), indent=1)


def render(items, theme, title=None, subtitle=None, cover=True):
    doc_title, blocks = build_blocks(items)
    if title:
        doc_title = title
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUT_DIR, f"note_{ts}_{theme}.pdf")
    load_theme(theme)  # early, clear failure
    import renderer as _r
    _r.build(theme, doc_title, blocks, out_path, subtitle=subtitle, cover=cover)
    return out_path, doc_title, len(blocks)
# ------------------------------------------------------------------ sidebar
st.sidebar.title("🎨 Notes Studio")
theme = st.sidebar.selectbox("Theme", list_themes(), index=0)
st.sidebar.caption("Pick the color mood for your notes.")

cfg = ai_notes.load_config()
with st.sidebar.expander("🤖 AI Settings", expanded=not ai_notes.ai_ready(cfg)):
    st.caption("OpenAI, Groq, OpenRouter…\nor free local Ollama:\nbase http://localhost:11434/v1")
    new_key = st.text_input("API key", value=cfg["api_key"], type="password")
    new_base = st.text_input("Base URL", value=cfg["base_url"])
    new_model = st.text_input("Model", value=cfg["model"])
    if st.button("💾 Save AI settings"):
        cfg.update(api_key=new_key.strip(), base_url=new_base.strip(), model=new_model.strip())
        ai_notes.save_config(cfg)
        st.success("Saved!")
    st.caption("✅ AI ready" if ai_notes.ai_ready(cfg) else "⚠️ AI not configured — "
               "File & Batch tabs work offline; Prompt falls back to simple layout.")

with st.sidebar.expander("🎨 Theme Studio", expanded=False):
    raw = json.load(open(THEMES_FILE, encoding="utf-8"))
    pick = st.selectbox("Edit theme", list(raw.keys()))
    cols = ["paper", "title_band", "title_text", "heading1", "body",
            "bullet", "highlight", "callout_bg", "accent"]
    changed = {}
    for k in cols:
        cur = raw[pick].get(k)
        if isinstance(cur, list) and len(cur) == 3:
            hexv = "#%02x%02x%02x" % tuple(cur)
        else:
            hexv = "#ffffff"
        val = st.color_picker(k, hexv)
        changed[k] = tuple(int(val.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    if st.button("Save this theme"):
        raw[pick].update(changed)
SAMPLE_PROMPTS = [
    "Explain photosynthesis with definitions and a memory tip",
    "Revision notes on the French Revolution: causes, events, dates",
    "Cheat sheet for Statistics: mean median mode, variance, distributions",
    "Notes on Java classes, inheritance and polymorphism with examples",
]

tab_ai, tab_file, tab_batch, tab_out = st.tabs(
    ["✨ From Prompt", "📄 From File", "📚 Batch Folder", "🗂 My Notes"])

with tab_ai:
    st.subheader("Describe the notes you want")
    preset_label = st.radio("Style", list(PRESET_NAMES), horizontal=True,
                            help=" | ".join(PRESET_HELP.values()))
    prompt = st.text_area(
        "Prompt", height=110, label_visibility="collapsed",
        placeholder="e.g. Make revision notes on the French Revolution: causes, "
                    "key events and important dates.")
    with st.popover("💡 Try a sample prompt"):
        for s in SAMPLE_PROMPTS:
            if st.button(s):
                prompt = s
    c1, c2 = st.columns([1, 3])
    if c2.button("✨ Generate Notes"):
        if not prompt.strip():
            st.warning("Type a prompt first!")
        else:
            try:
                if ai_notes.ai_ready(cfg):
                    with st.spinner("AI is writing your notes (multi-pass)..."):
                        doc = ai_notes.ai_generate_notes(prompt, PRESET_NAMES[preset_label], cfg)
                        items = ai_notes.doc_to_items(doc)
                else:
                    st.info("AI not configured — simple layout from your prompt. "
                            "Add AI settings in the sidebar.")
                    lines = [l.strip() for l in prompt.strip().splitlines() if l.strip()]
                    head = [("h", 1, lines[0][:70])]
                    rest = [("p", l) for l in lines[1:]] if len(lines) > 1 else []
                    items = head + rest
                out_path, doc_title, _ = render(items, theme, cover=True,
                                                subtitle=prompt.strip().splitlines()[0][:90])
                st.session_state["ai_out"] = out_path
                st.session_state["last_mode"] = "Prompt"
                log_history({"time": time.strftime("%Y-%m-%d %H:%M"), "source": "Prompt",
                             "title": doc_title, "theme": theme,
                             "pages": fitz.open(out_path).page_count})
            except Exception as e:
                st.error(f"Generation failed: {e}")
    if st.session_state.get("ai_out") and os.path.isfile(st.session_state["ai_out"]):
        st.success(f"Saved to {os.path.basename(st.session_state['ai_out'])}")
        show_pdf(st.session_state["ai_out"])
        json.dump(raw, open(THEMES_FILE, "w", encoding="utf-8"), indent=2)
        st.success(f"'{pick}' updated!")
with tab_file:
    st.subheader("Turn a file into pretty notes")
    up = st.file_uploader("Upload a PDF / TXT / MD", type=["pdf", "txt", "md"])
    existing = sorted(glob.glob(os.path.join(NOTES_DIR, "*")))
    existing = [f for f in existing if f.lower().endswith((".pdf", ".txt", ".md"))]
    picked = st.selectbox("…or pick one already in notes/",
                          ["—"] + [os.path.basename(f) for f in existing])
    c_ai, c_ocr = st.columns(2)
    use_ai = c_ai.checkbox("🤖 AI-condense content", value=False,
                           help="Requires AI settings.")
    use_ocr = c_ocr.checkbox("🧠 OCR scanned PDFs", value=False,
                             help="Reads image-only PDFs" +
                             ("" if ocr_available() else " (needs 'pip install rapidocr_onnxruntime')"))
    extra = st.text_input("Extra instruction for AI (optional)",
                          placeholder="e.g. focus on definitions and dates")
    preset_label2 = st.selectbox("AI style", list(PRESET_NAMES))
    if st.button("📄 Generate Notes from File"):
        src = None
        if up is not None:
            src = os.path.join(NOTES_DIR, up.name)
            open(src, "wb").write(up.getvalue())
        elif picked != "—":
            src = os.path.join(NOTES_DIR, picked)
        if src is None:
            st.warning("Upload a file or pick one from the list.")
        else:
            try:
                if use_ai:
                    if not ai_notes.ai_ready(cfg):
                        st.error("AI not configured — uncheck the box or add settings in the sidebar.")
                    else:
                        with st.spinner("AI is condensing your content..."):
                            items = extract_text(src, use_ocr=use_ocr)
                            raw = " ".join((t[2] if t[0] == "h" else t[1]) if len(t) > 1 else str(t)
                                           for t in items)
                            doc = ai_notes.ai_summarize_notes(raw, PRESET_NAMES[preset_label2], extra, cfg)
                            out_path, doc_title, _ = render(ai_notes.doc_to_items(doc), theme,
                                                            cover=True, subtitle=os.path.basename(src))
                            if doc.get("cards"):
                                export.anki_deck(doc["cards"], out_path[:-4] + "_flashcards.txt")
                            log_history({"time": time.strftime("%Y-%m-%d %H:%M"),
                                         "source": os.path.basename(src), "title": doc_title,
                                         "theme": theme, "pages": fitz.open(out_path).page_count,
                                         "flashcards": len(doc.get("cards", []))})
                            st.session_state["file_out"] = out_path
                else:
                    items = extract_text(src, use_ocr=use_ocr)
                    out_path, doc_title, _ = render(items, theme, cover=True,
                                                    subtitle=os.path.basename(src))
                    log_history({"time": time.strftime("%Y-%m-%d %H:%M"),
                                 "source": os.path.basename(src), "title": doc_title,
                                 "theme": theme, "pages": fitz.open(out_path).page_count})
                    st.session_state["file_out"] = out_path
            except Exception as e:
                if "No content found" in str(e):
                    st.error("This PDF has no readable text. Try checking the "
                             "OCR box (scanned pages), or use a text PDF / .txt.")
                else:
                    st.error(f"Could not generate notes: {e}")
    if st.session_state.get("file_out") and os.path.isfile(st.session_state["file_out"]):
        st.success(f"Saved to {os.path.basename(st.session_state['file_out'])}")
        show_pdf(st.session_state["file_out"])

with tab_batch:
    st.subheader("Convert a whole folder at once")
    folder = st.text_input("Folder path", value=NOTES_DIR)
    combine = st.checkbox("🔗 Combine all results into one master PDF", value=True)
    theme_b = st.selectbox("Theme for batch", list_themes(), index=0)
    ocr_b = st.checkbox("🧠 OCR scanned pages", value=False)
    if st.button("🚀 Run Batch"):
        files = sorted(glob.glob(os.path.join(folder, "*.pdf")) +
                       glob.glob(os.path.join(folder, "*.txt")) +
                       glob.glob(os.path.join(folder, "*.md")))
        if not files:
            st.warning("No PDF/TXT/MD files found in that folder.")
        else:
            done, skipped = [], []
            bar = st.progress(0.0)
            for i, f in enumerate(files):
                bar.progress((i + 1) / len(files))
                try:
                    out, t, _ = render(extract_text(f, use_ocr=ocr_b), theme_b,
                                       cover=True, subtitle=os.path.basename(f))
                    done.append(out)
                except Exception as e:
                    skipped.append((os.path.basename(f), str(e)[:80]))
            bar.empty()
            if combine and done:
                ts = time.strftime("%Y%m%d_%H%M%S")
                master = os.path.join(OUT_DIR, f"master_{ts}_{theme_b}.pdf")
                export.merge_pdfs(done, master)
                st.session_state["batch_out"] = master
            log_history({"time": time.strftime("%Y-%m-%d %H:%M"), "source": "Batch",
                         "title": f"{len(done)} files", "theme": theme_b,
                         "pages": len(done), "skipped": len(skipped)})
            st.success(f"Done: {len(done)} ok, {len(skipped)} skipped")
            for name, err in skipped[:8]:
                st.caption(f"⚠ {name}: {err}")
    if st.session_state.get("batch_out") and os.path.isfile(st.session_state["batch_out"]):
        st.success(f"Master PDF: {os.path.basename(st.session_state['batch_out'])}")
        show_pdf(st.session_state["batch_out"])

with tab_out:
    st.subheader("Your generated notes")
    hist = []
    if os.path.isfile(HISTORY_FILE):
        try:
            hist = json.load(open(HISTORY_FILE, encoding="utf-8"))
        except Exception:
            hist = []
    if hist:
        with st.expander("🕘 History", expanded=False):
            st.table([{k: str(v)[:22] for k, v in h.items()} for h in hist[:12]])
    files = outputs_list()
    if not files:
        st.info("Nothing here yet — generate your first notes!")
    else:
        sel = st.selectbox("Choose a PDF", [os.path.basename(f) for f in files])
        path = os.path.join(OUT_DIR, sel)
        b1, b2, b3 = st.columns([1, 1, 1])
        if b1.button("📂 Open"):
            os.startfile(path)
        if b2.button("🗑 Delete"):
            os.remove(path)
            st.rerun()
        with b3.popover("⬇ Export"):
            if st.button("HTML preview"):
                h, _ = export.to_html(path, OUT_DIR)
                st.success(os.path.basename(h))
            if st.button("PNG pages"):
                ps = export.pdf_to_pngs(path, OUT_DIR, dpi=110)
                st.success(f"{len(ps)} PNGs saved")
            if st.button("Word (.docx)"):
                items = extract_text(path)
                d = export.to_docx(sel[:-4], items, path[:-4] + ".docx")
                st.success(os.path.basename(d))
        st.caption(f"{sel} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))}")
        show_pdf(path)

