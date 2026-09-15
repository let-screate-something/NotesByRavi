"""ai_notes.py — multi-pass AI notes writing via any OpenAI-compatible API.
Works with OpenAI, Groq, OpenRouter, Together, or a free local Ollama.
Pipeline: outline -> per-section draft (structured JSON) -> polished notes.
No third-party packages (stdlib urllib only)."""

import json
import os
import re
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")
KEYS_FILE = os.path.join(BASE, "api_keys.md")

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.groq.com/openai/v1",
    "model": "openai/gpt-oss-120b",
}

KEY_RE = re.compile(r"gsk_[A-Za-z0-9]{10,}")

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


def _key_from_env():
    for name in ("GROQ_API_KEY", "OPENAI_API_KEY", "AI_API_KEY"):
        val = (os.environ.get(name) or "").strip().strip("'\"")
        if val:
            return val
    return ""


def _key_from_file():
    try:
        text = open(KEYS_FILE, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "revoked" in line.lower():
            continue
        m = KEY_RE.search(line)
        if m:
            return m.group(0)
    return ""


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if isinstance(saved.get(k), str) and saved[k].strip():
                    cfg[k] = saved[k].strip()
        except (OSError, ValueError):
            pass
    # env var wins over stored config; api_keys.md is a fallback only
    env_key = _key_from_env()
    if env_key:
        cfg["api_key"] = env_key
    elif not cfg.get("api_key"):
        cfg["api_key"] = _key_from_file()
    return cfg


def save_config(cfg):
    # config.json holds non-secret settings only; the key itself lives in
    # api_keys.md (or an env var) so it is never committed to git.
    safe = {
        "api_key": "",
        "base_url": (cfg.get("base_url") or "").strip() or DEFAULT_CONFIG["base_url"],
        "model": (cfg.get("model") or "").strip() or DEFAULT_CONFIG["model"],
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(safe, f, indent=2)


def ai_ready(cfg):
    base = cfg.get("base_url", "").lower()
    return bool(cfg.get("api_key")) or ("localhost" in base or "127.0.0.1" in base)


def _parse_wait(body, headers=None, default=6.0):
    """How long to wait after a 429/5xx. Groq says 'try again in 4.53s'."""
    m = re.search(r"try again in ([0-9.]+)\s*s", body or "", re.I)
    if m:
        try:
            return min(float(m.group(1)) + 0.8, 30.0)
        except ValueError:
            pass
    if headers is not None:
        ra = headers.get("Retry-After")
        if ra:
            try:
                return min(float(ra) + 0.8, 30.0)
            except ValueError:
                pass
    return default


def _chat(cfg, messages, max_tokens=2400, retries=6, on_wait=None):
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg.get("model") or "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    # NOTE: urllib's default User-Agent ("Python-urllib/3.x") is blocked by
    # Cloudflare, which fronts Groq/OpenRouter — without this header the API
    # returns HTTP 403 even with a perfectly valid key.
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "NotesStudio/1.0 (+https://github.com/let-screate-something)",
    }
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    # Free tiers (esp. Groq: 8000 tokens/minute) throttle hard, so retry with
    # the server's own "try again in Xs" hint instead of failing the whole job.
    last_err = None
    data = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            last_err = RuntimeError(
                f"API error {e.code} from {url}: {body or e.reason}")
            if e.code in (429, 408, 500, 502, 503, 504) and attempt < retries:
                wait = _parse_wait(body, getattr(e, "headers", None))
                if on_wait:
                    on_wait(attempt + 1, wait, e.code)
                time.sleep(wait)
                continue
            raise last_err from None
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"Network error reaching {url}: {e.reason}")
            if attempt < retries:
                wait = 3.0 + attempt * 2.0
                if on_wait:
                    on_wait(attempt + 1, wait, "net")
                time.sleep(wait)
                continue
            raise last_err from None
    if data is None:
        raise last_err or RuntimeError("AI request failed")
    msg = data["choices"][0]["message"]
    # reasoning models (e.g. gpt-oss) may put everything in `reasoning_content`
    content = (msg.get("content") or "").strip()
    if not content:
        content = (msg.get("reasoning_content") or "").strip()
    return content


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


def _outline(cfg, user_prompt, on_wait=None):
    msg = ("Before writing anything, reply with a numbered outline of "
           "2-5 section headings only, no extra text.\n\n" + user_prompt)
    return _chat(cfg, [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": msg}], max_tokens=300,
                 on_wait=on_wait)


def _draft_section(cfg, user_prompt, preset, i, n, section_hint,
                   on_wait=None):
    msg = (f"Write section {i} of {n} now: '{section_hint}'\n"
           f"Style: {PRESETS.get(preset, PRESETS['study_guide'])}\n\n"
           f"Topic/request:\n{user_prompt}")
    return _extract_json(_chat(cfg, [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": msg}],
                               max_tokens=1500, on_wait=on_wait))


def _single_pass(cfg, user_prompt, preset, on_wait=None):
    """One call that returns the whole document - much cheaper on tight
    tokens-per-minute limits than the multi-pass pipeline."""
    msg = (f"Style: {PRESETS.get(preset, PRESETS['study_guide'])}\n"
           f"Write 2-4 sections covering this request:\n{user_prompt}")
    return _extract_json(_chat(cfg, [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": msg}],
                               max_tokens=2800, on_wait=on_wait))


def _truncate(text, limit=14000):
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]..."


def ai_generate_notes(user_prompt, preset="study_guide", cfg=None, on_wait=None):
    """Multi-pass: outline, then draft each section, merge into one doc.

    Falls back to a single-pass generation if the multi-pass pipeline fails
    (e.g. a rate-limited free tier that keeps returning 429).
    """
    cfg = cfg or load_config()
    try:
        outline = _outline(cfg, user_prompt, on_wait)
        sections = [ln.strip().lstrip("0123456789.)- ") for ln in outline.splitlines()
                    if ln.strip() and any(c.isalnum() for c in ln)]
        if not sections:
            sections = ["Key Concepts", "Details", "Summary"]
        result = {"title": "", "sections": []}
        n = len(sections)
        for i, sec in enumerate(sections, 1):
            data = _draft_section(cfg, user_prompt, preset, i, n, sec, on_wait)
            if not isinstance(data, dict) or "items" not in data:
                data = {"heading": sec, "items": []}
            result["sections"].append(data)
            if not result["title"] and data.get("heading"):
                result["title"] = data["heading"]
        if not any(s.get("items") for s in result["sections"]):
            raise RuntimeError("multi-pass produced no items")
        return _normalize(result, preset)
    except Exception as first_err:
        # cheaper single call instead of failing outright
        try:
            return _normalize(_single_pass(cfg, user_prompt, preset, on_wait),
                              preset)
        except Exception:
            raise first_err from None


def ai_summarize_notes(raw_text, preset="study_guide", extra="", cfg=None,
                       on_wait=None):
    """Condense long PDF/text into structured notes (single JSON doc)."""
    cfg = cfg or load_config()
    user_msg = ("Condense the following content into notes.\n"
                + (f"Extra instruction: {extra}\n" if extra else "")
                + f"Style: {PRESETS[preset]}\n\nCONTENT:\n"
                + _truncate(raw_text))
    data = _extract_json(_chat(cfg, [{"role": "system", "content": SYSTEM},
                                     {"role": "user", "content": user_msg}],
                               max_tokens=3200, on_wait=on_wait))
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