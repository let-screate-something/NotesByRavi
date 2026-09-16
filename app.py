"""PDF Write Studio — open any PDF and write directly ON the page.

Every edit is a true vector overlay drawn natively by PyMuPDF (no
rasterising of the original content), so text stays sharp at any zoom and
the source PDF on disk is never touched until you press Save.

The centrepiece is a whole-page writeable canvas (the `pagewrite` custom
component): the real page is the canvas background, so a digital pen /
stylus / touch / mouse writes straight onto the document, pressure-aware.
Run:  streamlit run app.py
"""

import os
import time

import streamlit as st

import pagewrite
from pdf_editor import FONT_CHOICES, INK, STICKY_COLORS, PDFEditor, \
    list_editable_pdfs

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "output")
UPLOAD_DIR = os.path.join(BASE, "output", "_uploads")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

st.set_page_config(page_title="PDF Write Studio", page_icon="🖋", layout="wide")

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(160deg, #FDFCF8 0%, #EAF2F4 45%, #F5EFF8 100%);
        color: #2E3D48 !important;
    }
    .stApp, .stApp p, .stApp span, .stApp label, .stApp li, .stApp div {
        color: #2E3D48;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #33525E !important; }
    .stApp header { background: transparent; }
    .block-container {
        background: rgba(255, 255, 255, 0.74); border-radius: 18px;
        padding: 1.6rem 2.2rem 3rem 2.2rem; margin-top: .8rem;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #F7FAF9 0%, #EDF2F8 100%);
        border-right: 1px solid #E2E8EE;
    }
    section[data-testid="stSidebar"] * { color: #2E3D48; }
    .stApp textarea, .stApp input, div[data-baseweb="select"] > div,
    .stApp [data-testid="stFileUploaderDropzone"] {
        background-color: #FFFFFF !important; color: #2E3D48 !important;
        border-radius: 10px;
    }
    .stApp textarea::placeholder, .stApp input::placeholder { color: #7C8B96 !important; }
    div.stButton > button {
        border-radius: 12px !important; border: 1px solid #C9DDE2 !important;
        color: #2F4858 !important;
        background: linear-gradient(135deg, #D9EDE9, #E3EBFB) !important;
        font-weight: 600; padding: 0.4em 1.1em;
    }
    .stApp [data-baseweb="tab"] p { color: #5A6B78; }
    .stApp [aria-selected="true"] p { color: #2F4858 !important; font-weight: 700; }
    .stApp [data-testid="stAlertContainer"] * { color: #2E3D48 !important; }
    .stApp small, .stApp [data-testid="stCaptionContainer"] { color: #61707C !important; }
    .stApp img { border-radius: 10px; box-shadow: 0 2px 10px rgba(60,80,100,0.12); }
</style>
""", unsafe_allow_html=True)


# ---- small helpers ---------------------------------------------------------

def hex_rgb(h):
    """'#rrggbb' -> (r, g, b) tuple, falling back to the default ink."""
    h = (h or "#20242e").lstrip("#")
    if len(h) != 6:
        return INK
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return INK


def bump():
    """New canvas token -> client clears its strokes (fresh surface)."""
    st.session_state.token = os.urandom(4).hex()


def open_pdf(path, name):
    """(Re)create the editor session for a chosen PDF."""
    st.session_state.ed = PDFEditor(path)
    st.session_state.src_name = name
    st.session_state.page = 1
    st.session_state.pw_seq = -1
    st.session_state.last_saved = None
    bump()


def get_ed():
    return st.session_state.get("ed")


# ---- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.title("🖋 PDF Write Studio")

    st.subheader("1 · Open a PDF")
    up = st.file_uploader("Upload a PDF", type=["pdf"])
    if up is not None and up.name != st.session_state.get("up_name"):
        dest = os.path.join(UPLOAD_DIR, up.name)
        with open(dest, "wb") as f:
            f.write(up.getvalue())
        st.session_state.up_name = up.name
        open_pdf(dest, up.name)

    files = list_editable_pdfs()
    names = [os.path.basename(p) for p in files]
    sel = st.selectbox("…or open a local one", ["—"] + names, index=0)
    if sel != "—" and sel != st.session_state.get("src_name"):
        open_pdf(files[names.index(sel)], sel)

    ed = get_ed()
    if ed is None:
        st.info("Open a PDF to start writing on it.")
        st.stop()

    st.caption(f"📄 {st.session_state.src_name} — {ed.page_count} page(s)")

    st.subheader("2 · Page")
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    if nav1.button("◀") and st.session_state.page > 1:
        st.session_state.page -= 1
        bump()
    page_pick = nav2.number_input("Go to page", min_value=1,
                                  max_value=max(1, ed.page_count),
                                  value=st.session_state.page, key="pg_pick")
    if page_pick != st.session_state.page:
        st.session_state.page = int(page_pick)
        bump()
    if nav3.button("▶") and st.session_state.page < ed.page_count:
        st.session_state.page += 1
        bump()

    total_layers = sum(len(l) for l in ed.layers)
    st.caption(f"✍️ {len(ed.layers[st.session_state.page - 1])} ink/object(s) "
               f"on this page · {total_layers} total")

    if st.button("↶ Undo last edit"):
        if ed.undo():
            bump()
            st.rerun()
        else:
            st.info("Nothing left to undo (page deletes/duplicates can't be "
                    "reversed).")

    with st.expander("🧰 Page operations"):
        c1, c2 = st.columns(2)
        if c1.button("↻ Rot +90°"):
            ed.rotate_page(st.session_state.page, 90)
            bump()
        if c2.button("↺ Rot −90°"):
            ed.rotate_page(st.session_state.page, -90)
            bump()
        c3, c4 = st.columns(2)
        if c3.button("⧉ Duplicate"):
            ed.duplicate_page(st.session_state.page)
            bump()
            st.rerun()
        if c4.button("＋ Blank after"):
            ed.insert_blank_page(st.session_state.page)
            bump()
            st.rerun()
        c5, c6 = st.columns(2)
        to_p = c5.number_input("Move to #", min_value=1,
                               max_value=ed.page_count,
                               value=st.session_state.page, key="mv_pick")
        if c6.button("⇄ Move") and to_p != st.session_state.page:
            ed.move_page(st.session_state.page, int(to_p))
            st.session_state.page = int(to_p)
            bump()
            st.rerun()
        if st.button("🗑 Delete this page", type="primary"):
            try:
                ed.delete_page(st.session_state.page)
                st.session_state.page = min(st.session_state.page,
                                            ed.page_count)
                bump()
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.subheader("3 · Save")
    default_name = (os.path.splitext(st.session_state.src_name)[0]
                    + "_edited.pdf")
    out_name = st.text_input("File name", value=default_name)
    if st.button("💾 Save edited PDF"):
        out_path = os.path.join(OUT_DIR, out_name)
        try:
            ed.save(out_path)
            st.session_state.last_saved = out_path
            st.success(f"Saved: {out_name}")
            pagewrite.clear_overlays(keep=12)
        except Exception as e:
            st.error(f"Save failed: {e}")
    if st.session_state.get("last_saved") and os.path.isfile(
            st.session_state.last_saved):
        with open(st.session_state.last_saved, "rb") as f:
            st.download_button("⬇ Download edited PDF", f.read(),
                               file_name=os.path.basename(
                                   st.session_state.last_saved),
                               mime="application/pdf")



# ---- main: the writeable page ----------------------------------------------

st.subheader(f"✍️ Writing on page {st.session_state.page} of {ed.page_count}")
st.caption("Draw straight on the page with your pen / stylus / touch / mouse. "
           "Press **✅ Apply to PDF** and the ink lands exactly where you "
           "drew it — at print resolution, as a real overlay you can undo "
           "or save.")

page = st.session_state.page
pw_pt, ph_pt = ed.page_size(page)
bg_png = ed.render_raw_preview(page, dpi=110)

canvas_val = pagewrite.page_canvas(
    bg_png, pw_pt, ph_pt, page - 1, st.session_state.token,
    pages=ed.page_count, key="pwcanvas",
)

# component payloads: react to each (action, seq) exactly once
data = pagewrite.parse(canvas_val)
seq = data.get("seq")
if seq is not None and seq != st.session_state.pw_seq:
    st.session_state.pw_seq = seq
    action = data.get("action")
    if action == "nav":
        try:
            new_page = int(data.get("page", page - 1)) + 1
        except (TypeError, ValueError):
            new_page = page
        if 1 <= new_page <= ed.page_count:
            st.session_state.page = new_page
        bump()
        st.rerun()
    elif action == "ink":
        ink_path, _sx, _sy = pagewrite.save_overlay(data)
        if ink_path:
            ed.add_page_ink(page, ink_path)
            st.toast(f"Stamped {data.get('strokes', '?')} stroke(s) onto "
                     f"page {page}")
            bump()
            st.rerun()
        else:
            st.warning("The canvas sent an empty overlay — draw something "
                       "first.")

with st.expander("👁 Preview with all edits applied (this page)"):
    st.image(ed.render_preview(page, dpi=110), width="stretch")

prev1, prev2 = st.columns([3, 2])
with prev1:
    with st.expander("📜 Page text (useful for find & replace)"):
        st.text(ed.page_text(page, max_chars=2500) or "(no text on this page)")
with prev2:
    with st.expander("⚠️ Clear all edits on this page"):
        if st.button("Clear this page's edits"):
            ed.clear_page(page)
            bump()
            st.rerun()



# ---- object tools -----------------------------------------------------------

st.subheader("🧷 Place objects on this page")
st.caption("Coordinates are PDF points (1 pt = 1/72 inch). The page is "
           f"{pw_pt:.0f} × {ph_pt:.0f} pt.")

FONT_KEYS = list(FONT_CHOICES.values())
FONT_LABELS = list(FONT_CHOICES.keys())
STICKY_KEYS = list(STICKY_COLORS.keys())

tools = st.columns(3)

with tools[0]:
    with st.expander("🔤 Handwritten text"):
        t_txt = st.text_area("Text", "your note here", key="t_txt")
        t_x = st.number_input("X", 0.0, pw_pt, 60.0, key="t_x")
        t_y = st.number_input("Y", 0.0, ph_pt, 80.0, key="t_y")
        t_size = st.slider("Size", 6.0, 36.0, 13.0, key="t_size")
        t_font = st.selectbox("Font", FONT_LABELS, key="t_font")
        t_col = st.color_picker("Colour", "#20242e", key="t_col")
        t_rot = st.slider("Rotation °", -90.0, 90.0, 0.0, key="t_rot")
        if st.button("Add text", key="t_add"):
            if t_txt.strip():
                ed.add_text(page, t_txt, float(t_x), float(t_y),
                            size=float(t_size), color=hex_rgb(t_col),
                            font=FONT_KEYS[FONT_LABELS.index(t_font)],
                            rotation=float(t_rot))
                bump()
                st.rerun()
            else:
                st.warning("Type some text first.")

    with st.expander("🗂 Sticky note"):
        s_txt = st.text_area("Note text", "", key="s_txt")
        s_col = st.selectbox("Colour", STICKY_KEYS, key="s_col")
        s_x = st.number_input("X", 0.0, pw_pt, 380.0, key="s_x")
        s_y = st.number_input("Y", 0.0, ph_pt, 80.0, key="s_y")
        s_w = st.slider("Width", 40.0, 400.0, 140.0, key="s_w")
        s_h = st.slider("Height", 30.0, 300.0, 80.0, key="s_h")
        if st.button("Add sticky", key="s_add") and s_txt.strip():
            ed.add_sticky(page, s_txt, float(s_x), float(s_y),
                          w=float(s_w), h=float(s_h),
                          color=STICKY_COLORS[s_col])
            bump()
            st.rerun()

with tools[1]:
    with st.expander("🖼 Image"):
        i_up = st.file_uploader("Image (png/jpg)",
                                type=["png", "jpg", "jpeg"], key="i_up")
        i_x = st.number_input("X", 0.0, pw_pt, 60.0, key="i_x")
        i_y = st.number_input("Y", 0.0, ph_pt, 200.0, key="i_y")
        i_w = st.number_input("Width pt (0 = auto)", 0.0, 2000.0, 200.0,
                              key="i_w")
        i_h = st.number_input("Height pt (0 = auto)", 0.0, 2000.0, 0.0,
                              key="i_h")
        if st.button("Add image", key="i_add") and i_up is not None:
            ext = os.path.splitext(i_up.name)[1].lower() or ".png"
            dest = os.path.join(UPLOAD_DIR, f"img_{int(time.time())}{ext}")
            with open(dest, "wb") as f:
                f.write(i_up.getvalue())
            ed.add_image(page, dest, float(i_x), float(i_y),
                         w=float(i_w) or None, h=float(i_h) or None)
            bump()
            st.rerun()

    with st.expander("⬜ Shape"):
        sh_shape = st.selectbox("Shape", ["rect", "circle", "arrow", "line"],
                                key="sh_shape")
        sh_x = st.number_input("X", 0.0, pw_pt, 100.0, key="sh_x")
        sh_y = st.number_input("Y", 0.0, ph_pt, 100.0, key="sh_y")
        sh_w = st.number_input("W", 1.0, pw_pt, 150.0, key="sh_w")
        sh_h = st.number_input("H", 1.0, ph_pt, 60.0, key="sh_h")
        sh_col = st.color_picker("Colour", "#d04a4a", key="sh_col")
        sh_fill = st.checkbox("Filled", key="sh_fill")
        sh_bw = st.slider("Line width", 0.4, 4.0, 1.0, key="sh_bw")
        if st.button("Add shape", key="sh_add"):
            ed.add_shape(page, sh_shape, float(sh_x), float(sh_y),
                         float(sh_w), float(sh_h), color=hex_rgb(sh_col),
                         fill=sh_fill, bw=float(sh_bw))
            bump()
            st.rerun()


with tools[2]:
    with st.expander("🖍 Highlight area"):
        hl_x = st.number_input("X", 0.0, pw_pt, 60.0, key="hl_x")
        hl_y = st.number_input("Y", 0.0, ph_pt, 100.0, key="hl_y")
        hl_w = st.number_input("W", 1.0, pw_pt, 200.0, key="hl_w")
        hl_h = st.number_input("H", 1.0, ph_pt, 16.0, key="hl_h")
        hl_col = st.color_picker("Colour", "#ffeb82", key="hl_col")
        if st.button("Add highlight", key="hl_add"):
            ed.add_highlight(page, float(hl_x), float(hl_y),
                             float(hl_w), float(hl_h), color=hex_rgb(hl_col))
            bump()
            st.rerun()

    with st.expander("🧽 Whiteout area"):
        wo_erase = st.checkbox("Erase underlying text too (redaction)",
                               key="wo_erase")
        wo_x = st.number_input("X", 0.0, pw_pt, 60.0, key="wo_x")
        wo_y = st.number_input("Y", 0.0, ph_pt, 100.0, key="wo_y")
        wo_w = st.number_input("W", 1.0, pw_pt, 200.0, key="wo_w")
        wo_h = st.number_input("H", 1.0, ph_pt, 20.0, key="wo_h")
        if st.button("Add whiteout", key="wo_add"):
            ed.add_whiteout(page, float(wo_x), float(wo_y),
                            float(wo_w), float(wo_h), erase=wo_erase)
            bump()
            st.rerun()

    with st.expander("🔁 Find & replace / erase text"):
        fr_find = st.text_input("Find text", "", key="fr_find")
        fr_repl = st.text_input("Replace with (empty = erase)", "",
                                key="fr_repl")
        fr_font = st.selectbox("Font", FONT_LABELS, key="fr_font")
        fr_col = st.color_picker("Colour", "#1f5fa8", key="fr_col")
        if st.button("Apply to all matches", key="fr_add") and fr_find.strip():
            hits = ed.find_text(page, fr_find)
            if not hits:
                st.warning("No matches on this page.")
            elif fr_repl.strip():
                ed.replace_text(page, fr_find, fr_repl,
                                color=hex_rgb(fr_col),
                                font=FONT_KEYS[FONT_LABELS.index(fr_font)])
                st.success(f"{len(hits)} match(es) replaced.")
                bump()
            else:
                ed.erase_text(page, fr_find)
                st.success(f"{len(hits)} match(es) erased.")
                bump()

st.caption("PDF Write Studio · vector overlays via PyMuPDF · your source "
           "file is never modified — Save writes a new PDF.")

