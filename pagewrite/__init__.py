"""pagewrite — whole-page writeable canvas (true Streamlit custom component).

The real PDF page is rendered as the canvas background, so you write directly
ON the page with a digital pen / stylus / touch / mouse (pressure aware).

This uses ``components.declare_component(path=...)`` with a hand-written
static frontend (no npm build, no CDN): the browser-side code speaks the
Streamlit component protocol itself, so only the **Apply** button posts a
value back to Python. Drawing therefore never triggers a Streamlit rerun.

Protocol used (all postMessage payloads carry ``isStreamlitMessage: true``):
    streamlit:componentReady     {apiVersion: 1}
    streamlit:render             <- in   {args, disabled, theme}
    streamlit:setFrameHeight     {height}
    streamlit:setComponentValue  {value, dataType}
"""

import base64
import json
import os
import time

import streamlit.components.v1 as components

_BASE = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_DIR = os.path.join(_BASE, "frontend")
_OVERLAY_DIR = os.path.abspath(os.path.join(_BASE, os.pardir, "output", "_uploads"))

_component = components.declare_component("pagewrite", path=_FRONTEND_DIR)


def available():
    """True when the static frontend actually exists on disk."""
    return os.path.isfile(os.path.join(_FRONTEND_DIR, "index.html"))


def _data_url(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def page_canvas(bg_png_bytes, page_w_pt, page_h_pt, page, token, pages=None, key=None):
    """Show the writeable page.

    Parameters
    ----------
    bg_png_bytes : bytes
        PNG of the page (usually ``PDFEditor.render_raw_preview``).
    page_w_pt, page_h_pt : float
        Page size in PDF points — used for the canvas aspect ratio.
    page : int
        Zero-based page index (informational + used for the ink payload).
    token : str
        Any value that changes when the canvas must be cleared (page change,
        after an Apply, after a reload).
    pages : int | list | None
        Number of pages (or list of indices) to expose in the in-canvas page
        selector. A single page hides the selector.
    key : str
        Streamlit widget key.

    Returns
    -------
    str | None
        ``None`` until the user interacts; then a JSON string, either
        ``{"action": "ink", ...}`` (Apply pressed) or
        ``{"action": "nav", "page": n}`` (page selector used).
    """
    if not available():
        raise RuntimeError("pagewrite frontend missing: " + _FRONTEND_DIR)
    if pages is None:
        plist = [int(page)]
    elif isinstance(pages, int):
        plist = list(range(pages))
    else:
        plist = [int(p) for p in pages]
    return _component(
        bg=_data_url(bg_png_bytes),
        pw=float(page_w_pt),
        ph=float(page_h_pt),
        page=int(page),
        pages=plist,
        token=str(token),
        key=key,
        default=None,
    )


def parse(payload):
    """Best-effort decode of a component payload -> dict."""
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_overlay(payload):
    """Persist an Apply payload as a transparent PNG.

    Returns ``(path, sx, sy)`` or ``(None, None, None)`` when the payload is
    empty / not a usable PNG.
    """
    data = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict) or data.get("empty"):
        return None, None, None
    url = data.get("png", "")
    if not isinstance(url, str) or not url.startswith("data:image/png;base64,"):
        return None, None, None
    try:
        raw = base64.b64decode(url.split(",", 1)[1])
    except Exception:
        return None, None, None
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None, None
    os.makedirs(_OVERLAY_DIR, exist_ok=True)
    path = os.path.join(
        _OVERLAY_DIR, "pageink_%s_%d.png" % (time.strftime("%Y%m%d_%H%M%S"), len(raw))
    )
    with open(path, "wb") as f:
        f.write(raw)
    def _num(name, fallback):
        try:
            return float(data.get(name, fallback))
        except (TypeError, ValueError):
            return fallback

    return path, _num("sx", 1.0), _num("sy", 1.0)


def clear_overlays(keep=12):
    """Housekeeping: delete old overlay PNGs, keeping the newest ``keep``."""
    try:
        files = sorted(
            (os.path.join(_OVERLAY_DIR, f) for f in os.listdir(_OVERLAY_DIR)
             if f.startswith("pageink_") and f.endswith(".png")),
            key=os.path.getmtime,
        )
    except OSError:
        return
    for f in files[:-keep] if keep else files:
        try:
            os.remove(f)
        except OSError:
            pass