"""One-tap whiteboard component (draw -> Stamp directly into the PDF).

Pure-static custom component: no Node/npm build needed. The canvas
returns a PNG data-URL to Python only when the user hits Stamp, so
drawing never reruns the app — one tap, no download/upload step.
"""

import base64
import os
import time

import streamlit as st
import streamlit.components.v1 as components

_BASE = os.path.dirname(os.path.abspath(__file__))
_FRONTEND = os.path.join(_BASE, "frontend", "index.html")
_BOARD_DIR = os.path.join(_BASE, "..", "output", "_uploads")


def board_component(height=420, key="wb_tap"):
    """The drawing canvas. Returns the PNG data-URL on Stamp, else None."""
    if not os.path.isfile(_FRONTEND):
        return None
    with open(_FRONTEND, encoding="utf-8") as f:
        html = f.read()
    return components.html(html, height=height + 110)


def save_board_png(data_url):
    """Persist a data-URL PNG to uploads. Returns path or None."""
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
    except Exception:
        return None
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 500:
        return None  # corrupt or blank
    os.makedirs(_BOARD_DIR, exist_ok=True)
    path = os.path.join(_BOARD_DIR,
                        f"board_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as f:
        f.write(raw)
    return path


def one_tap_board_panel(height=420):
    """Render board + auto-stamp button state. Returns saved PNG path/None."""
    val = board_component(height)
    if not val:
        return st.session_state.get("wb_tap_file")
    path = save_board_png(val)
    if path:
        st.session_state["wb_tap_file"] = path
        st.success("Board captured — hit **Stamp board into PDF** below.")
        st.image(val, width="stretch")
        return path
    return st.session_state.get("wb_tap_file")
