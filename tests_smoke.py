import os
import fitz
import make_notes, renderer

def check(name, fn):
    try:
        msg = fn()
        print(f"[PASS] {name}: {msg}")
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")

# 1. markdown input with bold/italic, numbered, definition, tip
def t_md():
    md = ("# Test Markdown\n## Section One\n- bullet one\n- bullet two\n"
          "**bold text** and *italic* here.\n## Section Two\n1. numbered feels\n"
          "2. also numbered\nDefinition: Sample - a short definition here for testing.\n"
          "Tip: Remember to test.")
    open("notes/_test.md", "w", encoding="utf-8").write(md)
    out, t = make_notes.generate_notes("notes/_test.md", theme_name="meadow")
    return f"title={t!r} pages={fitz.open(out).page_count}"
check("markdown path", t_md)

# 2. arrow chain long
def t_arrows():
    items = [("h", 2, "Steps"), ("p", "Collect -> Preprocess -> Explore -> Model -> "
                              "Evaluate -> Deploy -> Monitor -> Retrain")] * 30  # lots
    out, t = make_notes.generate_notes("fake", from_items=items,
                                       theme_name="berry", title="Arrows")
    return f"pages={fitz.open(out).page_count}"
check("long arrow chains x30", t_arrows)

# 3. many sections -> must not crash
def t_many():
    items = []
    for i in range(12):
        items.append(("h", 2, f"Section {i}"))
        items.append(("p", f"This is paragraph number {i} discussing important "
                           f"concepts that students must remember well."))
    out, t = make_notes.generate_notes("fake", from_items=items, theme_name="sunset")
    return f"pages={fitz.open(out).page_count}"
check("12 sections", t_many)

# 4. resume PDF (real user file)
def t_resume():
    if not os.path.isfile("notes/Ravineesh_Singh_Resume.pdf"):
        return "no file"
    out, t = make_notes.generate_notes("notes/Ravineesh_Singh_Resume.pdf", theme_name="ocean")
    return f"title={t!r} pages={fitz.open(out).page_count}"
check("resume pdf", t_resume)

# 5. empty / blank-ish file -> friendly error
def t_empty():
    open("notes/_blank.txt", "w", encoding="utf-8").write("   \n\n  \n")
    try:
        make_notes.generate_notes("notes/_blank.txt", theme_name="ocean")
        return "unexpectedly OK"
    except ValueError as e:
        return f"ValueError as expected ({str(e)[:30]})"
check("blank file", t_empty)

# 6. all themes loop
def t_themes():
    from renderer import list_themes
    n = 0
    for th in list_themes():
        out, _ = make_notes.generate_notes("notes/_test.md", theme_name=th)
        n += fitz.open(out).page_count
        os.remove(out)
    return f"{len(list_themes())} themes rendered, {n} pages total"
check("theme loop", t_themes)

# 7. docx + anki + html exports on a generated pdf
def t_exports():
    import export
    out, _ = make_notes.generate_notes("notes/_test.md", theme_name="ocean")
    h, pngs = export.to_html(out, "output")
    d = export.to_docx("Test", make_notes.extract_text("notes/_test.md"), "output/_t.docx")
    a = export.anki_deck([("Q1", "A1")], "output/_t.txt")
    n = len(pngs)
    for f in [out, h] + pngs + [d, a]:
        os.remove(f) if os.path.isfile(f) else None
    return f"html pngs={n}, docx & anki written"
check("exports", t_exports)

# 8. rich_line with word wider than column (no crash)
def t_longword():
    import renderer as r
    pdf = r.NoteDoc(r.load_theme("ocean"), "Wide")
    pdf.add_page()
    pen = pdf.pen
    pdf.set_font("hand", "", 10.5)
    used, lines = pen.para("supercalifragilisticexpialidocious" * 3, 30, 40, 10.5,
                           (60, 60, 60), set(), max_w=80)
    return f"long word: {lines} lines"
check("long word wrap", t_longword)