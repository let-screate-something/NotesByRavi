"""whiteboard.py — pen/stylus digital-board section for the PDF editor.

Zero-dependency drawing surface: an HTML <canvas> (touch + stylus +
pressure ready) served through st.components.v1.html, with the drawing
exported as a PNG the user downloads (one tap) and stamps into the PDF.

Why not a canvas component package? streamlit-drawable-canvas 0.13 only
supports the old components API and crashes on modern Streamlit (>=1.49);
this approach works on every Streamlit version, local + Cloud.
"""

import base64
import os
import time

import streamlit as st
import streamlit.components.v1 as components

BASE = os.path.dirname(os.path.abspath(__file__))
BOARD_DIR = os.path.join(BASE, "output", "_uploads")


def _canvas_html(height=420):
    return (
        "<canvas id='wb' style='width:100%;height:" + str(height) + "px;"
        "touch-action:none;border:2px dashed #7FB3B5;border-radius:12px;"
        "background:#FFFFFF;cursor:crosshair;display:block'></canvas>"
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;"
        "align-items:center'>"
        "<button onclick=\"setTool('pen')\">Pen</button>"
        "<button onclick=\"setTool('marker')\">Marker</button>"
        "<button onclick=\"setTool('eraser')\">Eraser</button>"
        "<input type='color' id='wbc' value='#2D323C' title='colour'>"
        "<input type='range' id='wbs' min='1' max='24' value='3' title='size'>"
        "<button onclick='undo()'>Undo</button>"
        "<button onclick='clearAll()'>Clear</button>"
        "<button onclick='savePng()'>Download PNG</button>"
        "</div>"
        "<script>"
        "var cv=document.getElementById('wb'),ctx=cv.getContext('2d'),"
        "drawing=false,tool='pen',hist=[];"
        "function fit(){var r=cv.getBoundingClientRect();"
        "var t=document.createElement('canvas');"
        "t.width=cv.width;t.height=cv.height;"
        "t.getContext('2d').drawImage(cv,0,0);"
        "cv.width=r.width*2;cv.height=" + str(height) + "*2;"
        "ctx.lineCap='round';ctx.lineJoin='round';"
        "ctx.drawImage(t,0,0,cv.width,cv.height);}"
        "fit();window.addEventListener('resize',fit);"
        "function push(){hist.push(cv.toDataURL());"
        "if(hist.length>40)hist.shift();}"
        "push();"
        "function pos(e){var r=cv.getBoundingClientRect();"
        "if(e.touches&&e.touches[0])"
        "{return[(e.touches[0].clientX-r.left)*2,"
        "(e.touches[0].clientY-r.top)*2];}"
        "return[(e.clientX-r.left)*2,(e.clientY-r.top)*2];}"
        "function setTool(t){tool=t;}"
        "function undo(){if(hist.length>1){hist.pop();"
        "var i=new Image();i.onload=function(){"
        "ctx.clearRect(0,0,cv.width,cv.height);"
        "ctx.drawImage(i,0,0);};i.src=hist[hist.length-1];}}"
        "function clearAll(){push();"
        "ctx.clearRect(0,0,cv.width,cv.height);push();}"
        "cv.addEventListener('pointerdown',function(e){"
        "drawing=true;cv.setPointerCapture(e.pointerId);"
        "var p=pos(e);ctx.beginPath();ctx.moveTo(p[0],p[1]);"
        "e.preventDefault();});"
        "cv.addEventListener('pointermove',function(e){"
        "if(!drawing)return;"
        "var p=pos(e);"
        "var w=parseFloat(document.getElementById('wbs').value);"
        "if(e.pointerType==='pen'&&e.pressure&&e.pressure>0)"
        "{w=Math.max(1,w*e.pressure*1.6);}"
        "ctx.lineWidth=w*2;"
        "if(tool==='eraser'){ctx.globalCompositeOperation="
        "'destination-out';ctx.strokeStyle='rgba(0,0,0,1)';}"
        "else{ctx.globalCompositeOperation='source-over';"
        "ctx.strokeStyle=document.getElementById('wbc').value;"
        "if(tool==='marker')ctx.globalAlpha=0.45;"
        "else ctx.globalAlpha=1.0;}"
        "ctx.lineTo(p[0],p[1]);ctx.stroke();ctx.beginPath();"
        "ctx.moveTo(p[0],p[1]);e.preventDefault();});"
        "function stop(){if(drawing){drawing=false;"
        "ctx.globalAlpha=1.0;push();}}"
        "cv.addEventListener('pointerup',stop);"
        "cv.addEventListener('pointercancel',stop);"
        "cv.addEventListener('touchmove',function(e){e.preventDefault();},"
        "{passive:false});"
        "function savePng(){var a=document.createElement('a');"
        "a.download='board.png';a.href=cv.toDataURL('image/png');"
        "document.body.appendChild(a);a.click();a.remove();}"
        "</script>"
    )


def whiteboard_panel(height=420):
    """Render the board; returns saved PNG path or None.

    Flow: draw -> Download PNG -> re-upload below -> stamp into the PDF.
    The upload step is needed because browsers sandbox the component iframe
    (no direct Python bridge without an extra package).
    """
    components.html(_canvas_html(height), height=height + 70)
    up = st.file_uploader("Upload the downloaded board PNG to stamp it",
                          type=["png"], key="wb_up")
    if up is None:
        return st.session_state.get("wb_file")
    os.makedirs(BOARD_DIR, exist_ok=True)
    name = f"board_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(BOARD_DIR, name)
    raw = up.getvalue()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        st.error("That file is not a PNG — download the board first.")
        return st.session_state.get("wb_file")
    with open(path, "wb") as f:
        f.write(raw)
    st.session_state["wb_file"] = path
    st.success("Board captured — hit **Stamp board as full page**.")
    st.image(base64.b64encode(raw).decode(), width="stretch")
    return path
