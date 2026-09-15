# 🎨 Notes Studio — Beautiful Handwritten-Style Notes

Turn **reference PDFs, topic notes, or a plain prompt** into colourful
handwritten-style study notes — then edit them right in the app.

## ✨ The 3 sections

| Tab | What it does |
|---|---|
| **1️⃣ Research** | Paste a topic + optional PDFs / TXT / MD / URLs → AI compiles everything into one clean **Markdown file** (saved in `notes/`) |
| **2️⃣ Notes** | Turn any MD / TXT / PDF (or a prompt) into a **pretty handwritten-style PDF** in `output/` — themes, AI condense, batch mode, PNG/HTML/DOCX/Anki exports |
| **3️⃣ Editor** | Edit any generated PDF — **insert text, replace/erase text, insert images, sticky notes, highlights, shapes, whiteout, freehand draw**, plus page tools (undo, rotate, reorder, duplicate, delete, insert blank) |

## 🚀 Run it

```powershell
# easiest — double-click:
Start Notes Studio.bat

# or manually:
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

## 🤖 AI setup (sidebar → AI Settings)

- **Fast & free:** paste a [Groq](https://console.groq.com/keys) key (model `openai/gpt-oss-120b`, base URL `https://api.groq.com/openai/v1`)
- **Fully offline:** run [Ollama](https://ollama.com), base URL `http://localhost:11434/v1`, model e.g. `qwen3:8b`
- **Keys stay local:** settings live in `config.json`, master keys in `api_keys.md` — both are git-ignored, never committed

No AI? Tabs 1–2 still work in basic offline mode.

## 📁 Project layout

```
AINotes/
├── app.py                 # the Streamlit UI (all 3 sections + batch + history)
├── research.py            # section 1: research & compile → markdown
├── make_notes.py          # markdown/PDF → structured item stream
├── renderer.py            # handwritten-style PDF engine (fpdf2)
├── ai_notes.py            # multi-pass AI writer (OpenAI-compatible APIs)
├── pdf_editor.py          # section 3: vector PDF editor (PyMuPDF)
├── export.py / ocr.py     # PNG, HTML, DOCX, Anki, merge / scanned-PDF OCR
├── themes.json            # sunset · ocean · meadow · berry palettes
├── notes/                 # input files + saved research markdown
└── output/                # generated PDFs live here
```

## 🧪 Verify everything works

```powershell
python tests_smoke.py     # markdown, arrows, sections, resume, themes, exports
```

## 🔑 Rotate a leaked key

Revoke it at https://console.groq.com/keys, paste the new one into
`api_keys.md` (or Sidebar → AI Settings), and you're done.

