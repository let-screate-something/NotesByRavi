"""ai_notes.py — multi-pass AI notes writing via any OpenAI-compatible API.
Works with OpenAI, Groq, OpenRouter, Together, or a free local Ollama.
Pipeline: outline -> per-section draft (structured JSON) -> polished notes.
No third-party packages (stdlib urllib only)."""

import json
import os
import re
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
}

PRESETS = {
    "study_guide": "A clean study guide: one fact per bullet, definitions and tips.",
    "cheat_sheet": "An ultra-dense exam cheat-sheet: short bullets, formulas, key facts only.",
    "exam_prep": "Exam revision notes: what to remember, common mistakes, memory hooks.",
    "flashcards": "Question-answer flashcards (QUESTION and ANSWER labels).",
}

# valid item kinds understood by the renderer
KINDS = {"bullet", "para", "definition", "tip", "note", "example", "arrow"}

SYSTEM = (
    "You are a master study-notes writer. Use the user's request to create notes.\n"
    "Respond ONLY with valid JSON, no markdown fences, matching exactly:\n"
    "{\n"
    '  "title": "Short Title",\n'
    '  "sections": [\n'
    "    {\n"
    '      "heading": "Section heading",\n'
    '      "items": [\n'
    '        {"kind": "bullet", "text": "..."},\n'
    '        {"kind": "para", "text": "..."},\n'
    '        {"kind": "definition", "text": "term - explanation"},\n'
    '        {"kind": "tip", "text": "..."},\n'
    '        {"kind": "note", "text": "..."},\n'
    '        {"kind": "example", "text": "..."},\n'
    '        {"kind": "arrow", "text": "A -> B -> C"}\n'
    "      ]\n"
    "    }\n"
    "  ]\n"
    "}\n"
    "Rules: bullets under 22 words; use arrow kind for step sequences; "
    "2-5 sections; spell out important terms."
)


def load_config():
    if not os.path.isfile(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def ai_ready(cfg):
    base = cfg.get("base_url", "").lower()
    return bool(cfg.get("api_key")) or ("localhost" in base or "127.0.0.1" in base)


def _chat(cfg, messages, max_tokens=2400):
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg.get("model") or "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _outline(cfg, user_prompt):
    msg = ("Before writing anything, reply with a numbered outline of "
           "2-5 section headings only, no extra text.\n\n" + user_prompt)
    return _chat(cfg, [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": msg}], max_tokens=400)


def _draft_section(cfg, user_prompt, preset, i, n, section_hint):
    msg = (f"Write section {i} of {n} now: '{section_hint}'\n"
           f"Style: {PRESETS.get(preset, PRESETS['study_guide'])}\n\nTopic/request:\n{user_prompt}")
    return _extract_json(_chat(cfg, [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": msg}]))


def _truncate(text, limit=14000):
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]..."


def ai_generate_notes(user_prompt, preset="study_guide", cfg=None):
    """Multi-pass: outline, then draft each section, merge into one doc."""
    cfg = cfg or load_config()
    outline = _outline(cfg, user_prompt)
    sections = [ln.strip().lstrip("0123456789.)- ") for ln in outline.splitlines()
                if ln.strip() and any(c.isalnum() for c in ln)]
    if not sections:
        sections = ["Key Concepts", "Details", "Summary"]
    result = {"title": "", "sections": []}
    n = len(sections)
    for i, sec in enumerate(sections, 1):
        data = _draft_section(cfg, user_prompt, preset, i, n, sec)
        if not isinstance(data, dict) or "items" not in data:
            data = {"heading": sec, "items": []}
        result["sections"].append(data)
        if not result["title"] and data.get("heading"):
            result["title"] = data["heading"]
    return _normalize(result, preset)


def ai_summarize_notes(raw_text, preset="study_guide", extra="", cfg=None):
    """Condense long PDF/text into structured notes (single JSON doc)."""
    cfg = cfg or load_config()
    user_msg = ("Condense the following content into notes.\n"
                + (f"Extra instruction: {extra}\n" if extra else "")
                + f"Style: {PRESETS[preset]}\n\nCONTENT:\n"
                + _truncate(raw_text))
    data = _extract_json(_chat(cfg, [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": user_msg}]))
    return _normalize(data, preset)


def _normalize(data, preset):
    """Coerce AI JSON into a clean structure for the renderer + flashcard export."""
    if not isinstance(data, dict):
        data = {"title": "", "sections": []}
    title = str(data.get("title") or "My Notes").strip() or "My Notes"
    cards = []
    sections = []
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "").strip()
        items = []
        for it in sec.get("items") or []:
            if not isinstance(it, dict):
                continue
            kind = str(it.get("kind") or "bullet").lower()
            text = str(it.get("text") or "").strip()
            if not text:
                continue
            if kind in ("definition", "tip", "note", "example"):
                items.append({"kind": "key", "text": text})
                if kind == "definition" and " - " in text:
                    q, a = text.split(" - ", 1)
                    cards.append((f"Define: {q.strip()}", a.strip()))
            elif kind == "arrow" or "->" in text or "→" in text:
                items.append({"kind": "arrow", "text": text})
            elif kind == "para":
                items.append({"kind": "para", "text": text})
            else:
                items.append({"kind": "bullet", "text": text})
            if kind == "tip":
                cards.append(("Tip: what & why", text))
        if heading or items:
            sections.append({"heading": heading, "items": items})
    if preset == "flashcards":
        for sec in sections:
            for it in sec["items"]:
                if it["kind"] == "key" and " - " in it["text"]:
                    q, a = it["text"].split(" - ", 1)
                    cards.append((q.strip(), a.strip()))
    return {"title": title, "sections": sections, "cards": cards}


def doc_to_items(doc):
    """AI doc -> make_notes item stream for rendering."""
    items = []
    items.append(("h", 1, doc["title"]))
    for sec in doc["sections"]:
        h = sec.get("heading")
        if h:
            items.append(("h", 2, h))
        for it in sec["items"]:
            if it["kind"] == "para":
                items.append(("p", it["text"]))
            elif it["kind"] == "arrow":
                part = " -> ".join(p.strip() for p in it["text"].split("->") if p.strip())
                items.append(("p", part))
            elif it["kind"] == "key":
                label, _, body = it["text"].partition(" - ")
                if label and body:
                    items.append(("key", label.strip().capitalize(), body.strip()))
                else:
                    items.append(("p", it["text"]))
            else:
                items.append(("p", it["text"]))
    return items