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
import pdf_editor
import research
from make_notes import build_blocks, extract_text, generate_notes
from renderer import list_themes, load_theme
from ocr import ocr_available

BASE = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(BASE, "notes")
OUT_DIR = os.path.join(BASE, "output")
THEMES_FILE = os.path.join(BASE, "themes.json")
HISTORY_FILE = os.path.join(OUT_DIR, "history.json")
UPLOAD_DIR = os.path.join(OUT_DIR, "_uploads")
os.makedirs(NOTES_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

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


def _hex_rgb(hexv):
    """'#rrggbb' -> (r, g, b) ints."""
    hexv = (hexv or "#000000").lstrip("#")
    return tuple(int(hexv[i:i + 2], 16) for i in (0, 2, 4))


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
        json.dump(raw, open(THEMES_FILE, "w", encoding="utf-8"), indent=2)
        st.success(f"'{pick}' updated!")

SAMPLE_PROMPTS = [
    "Explain photosynthesis with definitions and a memory tip",
    "Revision notes on the French Revolution: causes, events, dates",
    "Cheat sheet for Statistics: mean median mode, variance, distributions",
    "Notes on Java classes, inheritance and polymorphism with examples",
]

tab_res, tab_file, tab_edit, tab_ai, tab_batch, tab_out = st.tabs([
    "🔎 1· Research → Markdown",
    "📄 2· Markdown/File → PDF",
    "✏️ 3· Edit PDF",
    "✨ From Prompt",
    "📚 Batch Folder",
    "🗂 My Notes"])

with tab_res:
    st.subheader("🔎 Research a topic or your PDFs → clean Markdown")
    st.caption("Combines a topic description, PDFs, text files and web pages "
               "into one structured .md file. That .md then feeds tab 2.")

    r_topic = st.text_area(
        "Topic / description", height=90, key="res_topic",
        placeholder="e.g. Descriptive statistics — central tendency, dispersion, "
                    "skewness. Focus on formulas and when to use each measure.")

    c_r1, c_r2 = st.columns(2)
    with c_r1:
        r_pdfs = st.file_uploader("Reference PDFs (optional)", type=["pdf"],
                                  accept_multiple_files=True, key="res_pdfs")
        r_docs = st.file_uploader("Reference TXT / MD (optional)",
                                  type=["txt", "md"], accept_multiple_files=True,
                                  key="res_txt")
    with c_r2:
        _np = sorted(glob.glob(os.path.join(NOTES_DIR, "*.pdf")))
        r_pick_pdf = st.multiselect("…or pick PDFs already in notes/",
                                    [os.path.basename(p) for p in _np],
                                    key="res_pick_pdf")
        r_urls = st.text_area("Web pages (one per line, optional)", height=68,
                              key="res_urls",
                              placeholder="https://en.wikipedia.org/wiki/Statistics")

    c_s1, c_s2 = st.columns([1, 2])
    r_style = c_s1.selectbox("Research style",
                             ["study_guide", "bullet_summary", "deep_dive"],
                             key="res_style")
    r_extra = c_s2.text_input("Extra instructions (optional)", key="res_extra",
                              placeholder="e.g. keep every formula, add exam tips")

    if st.button("🔎 Research & Build Markdown", type="primary"):
        pdf_paths, txt_paths = [], []
        for uf in (r_pdfs or []):
            dst = os.path.join(UPLOAD_DIR, uf.name)
            with open(dst, "wb") as f:
                f.write(uf.getvalue())
            pdf_paths.append(dst)
        for uf in (r_docs or []):
            dst = os.path.join(UPLOAD_DIR, uf.name)
            with open(dst, "wb") as f:
                f.write(uf.getvalue())
            txt_paths.append(dst)
        pdf_paths += [os.path.join(NOTES_DIR, n) for n in r_pick_pdf]
        url_list = [u.strip() for u in (r_urls or "").splitlines() if u.strip()]
        if not (r_topic.strip() or pdf_paths or txt_paths or url_list):
            st.warning("Give me something to research — a topic, a PDF, a file "
                       "or a URL.")
        else:
            try:
                with st.spinner("Gathering sources and compiling markdown…"):
                    md = research.research_to_markdown(
                        r_topic, pdf_files=pdf_paths, txt_files=txt_paths,
                        urls=url_list, style=r_style,
                        extra_instructions=r_extra, cfg=cfg)
                st.session_state["res_md"] = md
                st.session_state["res_name"] = (
                    (r_topic.strip()[:40] or "research")
                    .replace("/", "-").replace("\\", "-").strip() + ".md")
                log_history({"time": time.strftime("%Y-%m-%d %H:%M"),
                             "source": "Research",
                             "title": (r_topic.strip()[:40] or "notes"),
                             "theme": "-", "pages": 0})
            except Exception as e:
                st.error(f"Research failed: {e}")

    if st.session_state.get("res_md"):
        st.success("Markdown ready — edit it below, then save it into notes/.")
        edited_md = st.text_area("Markdown (editable)",
                                 value=st.session_state["res_md"], height=320)
        fname = st.text_input("File name",
                              value=st.session_state.get("res_name", "notes.md"))
        b1, b2 = st.columns(2)
        if b1.button("💾 Save to notes/"):
            name = fname if fname.lower().endswith(".md") else fname + ".md"
            p = research.save_markdown(edited_md, name, NOTES_DIR)
            st.success(f"Saved {os.path.basename(p)} — now open tab 2 and pick it.")
        b2.download_button(" Download .md", data=edited_md, file_name=fname,
                           mime="text/markdown")
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

with tab_edit:
    st.subheader("✏️ Edit a PDF")
    st.caption("True vector edits — inserted text stays sharp and searchable, "
               "and the original file is never modified until you save a copy.")

    _pdfs = pdf_editor.list_editable_pdfs()
    if not _pdfs:
        st.info("No PDFs yet — generate one in tab 2 (or drop a PDF into notes/).")
    else:
        _names = [os.path.basename(p) for p in _pdfs]
        e_sel = st.selectbox("PDF to edit", _names, key="ed_sel")
        e_src = _pdfs[_names.index(e_sel)]

        # (re)open the editor whenever the chosen file changes
        if st.session_state.get("ed_src") != e_src:
            _old = st.session_state.get("ed_obj")
            if _old is not None:
                try:
                    _old.close()
                except Exception:
                    pass
            st.session_state["ed_obj"] = pdf_editor.PDFEditor(e_src)
            st.session_state["ed_src"] = e_src
            st.session_state.pop("ed_saved", None)
        ed = st.session_state["ed_obj"]

        c_pg, c_dpi, c_undo = st.columns([1, 1, 1])
        e_page = c_pg.number_input("Page", min_value=1, max_value=ed.page_count,
                                   value=1, step=1, key="ed_page")
        e_dpi = c_dpi.slider("Preview quality", 60, 170, 100, 10, key="ed_dpi")
        if c_undo.button("↶ Undo last edit", key="ed_undo"):
            if ed.undo():
                st.rerun()
            else:
                st.toast("Nothing to undo")
        _pw, _ph = ed.page_size(e_page)
        st.caption(f"{ed.page_count} page(s) · {_pw:.0f}×{_ph:.0f} pt · "
                   f"{ed.layer_count(e_page)} edit(s) on this page")

        st.image(ed.render_preview(e_page, dpi=e_dpi), width="stretch")

        with st.expander("✍️ Insert text", expanded=False):
            t_txt = st.text_area("Text to add", key="ed_t_text", height=70,
                                 placeholder="Type the text you want on the page")
            c1, c2, c3 = st.columns(3)
            t_x = c1.number_input("X (pt)", 0.0, 2000.0, 60.0, 5.0, key="ed_t_x")
            t_y = c2.number_input("Y (pt)", 0.0, 2000.0, 120.0, 5.0, key="ed_t_y")
            t_size = c3.number_input("Font size", 6.0, 48.0, 15.0, 1.0,
                                     key="ed_t_size")
            c4, c5, c6 = st.columns(3)
            t_font = c4.selectbox("Handwriting font",
                                  list(pdf_editor.FONT_CHOICES), key="ed_t_font")
            t_col = c5.color_picker("Colour", "#2D323C", key="ed_t_col")
            t_rot = c6.slider("Tilt (°)", -15.0, 15.0, 0.0, 0.5, key="ed_t_rot")
            if st.button("➕ Add text", key="ed_t_go") and t_txt.strip():
                ed.add_text(e_page, t_txt, t_x, t_y, t_size, _hex_rgb(t_col),
                            pdf_editor.FONT_CHOICES[t_font], t_rot)
                st.rerun()

        with st.expander("🔁 Replace or erase existing text", expanded=False):
            st.caption("Searches this page for the exact text and redacts it.")
            r_find = st.text_input("Find text", key="ed_r_find",
                                   placeholder="text you want to change")
            r_new = st.text_input("Replace with (leave empty to just erase)",
                                  key="ed_r_new")
            c7, c8 = st.columns(2)
            r_font = c7.selectbox("Font for replacement",
                                  list(pdf_editor.FONT_CHOICES), key="ed_r_font")
            r_col = c8.color_picker("Colour", "#2D323C", key="ed_r_col")
            if st.button("🔁 Apply", key="ed_r_go") and r_find.strip():
                hits = ed.find_text(e_page, r_find)
                if not hits:
                    st.warning("That text was not found on this page.")
                else:
                    if r_new.strip():
                        ed.replace_text(e_page, r_find, r_new, None,
                                        _hex_rgb(r_col),
                                        pdf_editor.FONT_CHOICES[r_font])
                    else:
                        ed.erase_text(e_page, r_find)
                    st.success(f"{len(hits)} occurrence(s) updated.")
                    st.rerun()
        with st.expander("🖼 Insert an image", expanded=False):
            i_up = st.file_uploader("Image (PNG / JPG)", type=["png", "jpg", "jpeg"],
                                    key="ed_i_up")
            c9, c10, c11 = st.columns(3)
            i_x = c9.number_input("X (pt)", 0.0, 2000.0, 380.0, 5.0, key="ed_i_x")
            i_y = c10.number_input("Y (pt)", 0.0, 2000.0, 120.0, 5.0, key="ed_i_y")
            i_w = c11.number_input("Width (pt)", 20.0, 900.0, 150.0, 10.0,
                                   key="ed_i_w")
            i_keep = st.checkbox("Keep aspect ratio", value=True, key="ed_i_keep")
            if st.button("➕ Stamp image", key="ed_i_go"):
                if i_up is None:
                    st.warning("Choose an image file first.")
                else:
                    dst = os.path.join(UPLOAD_DIR, i_up.name)
                    with open(dst, "wb") as f:
                        f.write(i_up.getvalue())
                    ed.add_image(e_page, dst, i_x, i_y, i_w,
                                 None if i_keep else i_w * 0.75)
                    st.rerun()

        with st.expander("🗒 Sticky note", expanded=False):
            s_txt = st.text_area("Note text", key="ed_s_txt", height=70)
            c12, c13, c14, c15 = st.columns(4)
            s_x = c12.number_input("X (pt)", 0.0, 2000.0, 380.0, 5.0, key="ed_s_x")
            s_y = c13.number_input("Y (pt)", 0.0, 2000.0, 240.0, 5.0, key="ed_s_y")
            s_w = c14.number_input("Width", 25.0, 400.0, 90.0, 5.0, key="ed_s_w")
            s_h = c15.number_input("Height", 20.0, 400.0, 55.0, 5.0, key="ed_s_h")
            s_col = st.select_slider("Sticky colour",
                                     list(pdf_editor.STICKY_COLORS),
                                     value="yellow", key="ed_s_col")
            if st.button("➕ Add sticky", key="ed_s_go") and s_txt.strip():
                ed.add_sticky(e_page, s_txt, s_x, s_y, s_w, s_h,
                              pdf_editor.STICKY_COLORS[s_col])
                st.rerun()

        with st.expander("🖍 Highlight · shapes · whiteout · draw",
                         expanded=False):
            c16, c17, c18, c19 = st.columns(4)
            h_x = c16.number_input("X (pt)", 0.0, 2000.0, 60.0, 5.0, key="ed_h_x")
            h_y = c17.number_input("Y (pt)", 0.0, 2000.0, 200.0, 5.0, key="ed_h_y")
            h_w = c18.number_input("W (pt)", 5.0, 1200.0, 140.0, 5.0, key="ed_h_w")
            h_h = c19.number_input("H (pt)", 5.0, 1200.0, 40.0, 5.0, key="ed_h_h")
            c20, c21, c22 = st.columns(3)
            h_col = c20.color_picker("Colour", "#FFE082", key="ed_h_col")
            a_shape = c21.selectbox("Shape", ["rect", "circle", "arrow", "line"],
                                    key="ed_h_shape")
            a_fill = c22.checkbox("Fill shape", value=False, key="ed_h_fill")
            b17, b18, b19, b20 = st.columns(4)
            if b17.button("🖍 Highlight", key="ed_h_hl"):
                ed.add_highlight(e_page, h_x, h_y, h_w, h_h, _hex_rgb(h_col))
                st.rerun()
            if b18.button("➕ Shape", key="ed_h_sh"):
                ed.add_shape(e_page, a_shape, h_x, h_y, h_w, h_h,
                             _hex_rgb(h_col), a_fill)
                st.rerun()
            if b19.button("⬜ Whiteout", key="ed_h_wo"):
                ed.add_whiteout(e_page, h_x, h_y, h_w, h_h)
                st.rerun()
            if b20.button(" Erase area", key="ed_h_er"):
                ed.add_whiteout(e_page, h_x, h_y, h_w, h_h, erase=True)
                st.rerun()

        from whiteboard import whiteboard_panel

        with st.expander("🖊 Digital board — draw & stamp", expanded=True):
            st.caption("Write with your **pen / stylus / mouse / touch** on the "
                       "canvas, then stamp the sheet into the PDF. "
                       "Pressure-sensitive pens work like a normal canvas.")
            wb_file = whiteboard_panel()
            wb1, wb2 = st.columns([1, 1])
            if wb1.button("📌 Stamp board as full page",
                          key="ed_wb_stamp", disabled=not wb_file):
                if wb_file:
                    dst = os.path.join(UPLOAD_DIR, os.path.basename(wb_file))
                    if dst != wb_file:
                        open(dst, "wb").write(open(wb_file, "rb").read())
                    ed.add_board(e_page, dst)
                    st.rerun()
            if wb2.button("🧽 Discard board", key="ed_wb_clear",
                          disabled=not wb_file):
                try:
                    os.remove(wb_file)
                except OSError:
                    pass
                st.session_state.pop("wb_file", None)
                st.rerun()
            st.caption("Freehand — type the points in order as 'x,y' pairs.")
            pts_raw = st.text_input("Points, e.g. 60,300 80,310 100,295",
                                    key="ed_d_pts")
            if st.button("✏️ Draw stroke", key="ed_d_go") and pts_raw.strip():
                pts = []
                for chunk in pts_raw.replace(";", " ").split():
                    if "," in chunk:
                        try:
                            px, py = chunk.split(",")[:2]
                            pts.append((float(px), float(py)))
                        except ValueError:
                            continue
                if len(pts) >= 2:
                    ed.add_drawing(e_page, pts, _hex_rgb(h_col))
                    st.rerun()
                else:
                    st.warning("Give at least two 'x,y' pairs.")
        with st.expander(" Page tools", expanded=False):
            p1, p2, p3, p4 = st.columns(4)
            if p1.button(" Rotate 90°", key="ed_p_rot"):
                ed.rotate_page(e_page, 90)
                st.rerun()
            if p2.button(" Duplicate", key="ed_p_dup"):
                ed.duplicate_page(e_page)
                st.rerun()
            if p3.button("➕ Blank page", key="ed_p_blank"):
                ed.insert_blank_page(e_page)
                st.rerun()
            if p4.button(" Delete page", key="ed_p_del"):
                try:
                    ed.delete_page(e_page)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            c23, c24 = st.columns(2)
            m_to = c23.number_input("Move this page to position",
                                    min_value=1, max_value=ed.page_count,
                                    value=1, step=1, key="ed_p_to")
            if c24.button("➡ Move", key="ed_p_move"):
                ed.move_page(e_page, m_to)
                st.rerun()
            if st.button("🧹 Clear edits on this page", key="ed_p_clear"):
                ed.clear_page(e_page)
                st.rerun()

        st.divider()
        c25, c26 = st.columns([2, 1])
        _default_name = os.path.splitext(e_sel)[0] + "_edited.pdf"
        save_name = c25.text_input("Save as (inside output/)",
                                   value=_default_name, key="ed_save_name")
        if c26.button("💾 Save edited PDF", type="primary", key="ed_save_go"):
            if not save_name.lower().endswith(".pdf"):
                save_name += ".pdf"
            try:
                out_p = ed.save(os.path.join(OUT_DIR, save_name))
                st.session_state["ed_saved"] = out_p
                log_history({"time": time.strftime("%Y-%m-%d %H:%M"),
                             "source": "Editor", "title": save_name,
                             "theme": "-", "pages": ed.page_count})
            except Exception as e:
                st.error(f"Save failed: {e}")
        _sp = st.session_state.get("ed_saved")
        if _sp and os.path.isfile(_sp):
            st.success(f"Saved {os.path.basename(_sp)}")
            if st.button("📂 Open saved PDF", key="ed_open"):
                if os.name == "nt":
                    os.startfile(_sp)  # local Windows only
                else:
                    st.info("On Streamlit Cloud use the Download button below.")
            with open(_sp, "rb") as f:
                st.download_button(" Download edited PDF", data=f.read(),
                                   file_name=os.path.basename(_sp),
                                   mime="application/pdf")
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
            if os.name == "nt":
                os.startfile(path)  # local Windows only
            else:
                st.info("On Streamlit Cloud use ⬇ Export → download instead.")
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

