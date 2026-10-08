"""Draft profile from an existing CV (`python -m jobagent --setup --from-cv cv.pdf`).

The draft is only a starting point for the interview: nothing is written until the user confirms there.
CV text is treated as untrusted. Contact details come from regexes; facts come from the LLM, and a fact is
kept only if the quote the model gives as its source really appears in the CV and mentions the fact.
"""
import re
from pathlib import Path

from jobagent import llm
from jobagent.profile import ID_PREFIX, SCHEMA_VERSION, fact_errors, slug
from jobagent.safety import looks_injected

MISSING = "Reading {} files needs the cv extra: pip install 'jobagent[cv]'"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
LINKEDIN = re.compile(r"(?:https?://)?(?:[\w-]+\.)?linkedin\.com/in/[\w%-]+", re.I)
GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
MAX_CHARS = 20000
MIN_QUOTE = 4  # characters left after normalising; shorter quotes would match anywhere


def extract_text(path):
    """Plain text of a .pdf, .docx or .txt file. PDF and DOCX need the `cv` extra."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError(MISSING.format(".pdf")) from e
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if ext == ".docx":
        try:
            import docx
        except ImportError as e:
            raise RuntimeError(MISSING.format(".docx")) from e
        doc = docx.Document(str(path))
        cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
        return "\n".join([p.text for p in doc.paragraphs] + cells)
    raise ValueError(f"Unsupported file type {ext or path.name!r}; use .pdf, .docx or .txt")


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _url(match):
    return match.group() if match.group().startswith("http") else "https://" + match.group()


def _contact(text):
    out = {}
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    words = first.split()
    if 2 <= len(words) <= 3 and all(w.replace("-", "").isalpha() for w in words):
        out["first_name"], out["last_name"] = words[0], " ".join(words[1:])
    if m := EMAIL.search(text):
        out["email"] = m.group()
    for m in PHONE.finditer(text):
        if sum(c.isdigit() for c in m.group()) >= 9:
            out["phone"] = m.group().strip()
            break
    if m := LINKEDIN.search(text):
        out["linkedin"] = _url(m)
    if m := GITHUB.search(text):
        out["github"] = _url(m)
    return out


def _backed(quote, haystack, *names):
    """The quote is in the CV and mentions at least one of the fact's own words (name, title or org)."""
    q = _norm(quote)
    return len(q) >= MIN_QUOTE and q in haystack and any(_norm(n) in q for n in names if _norm(n))


def _fact(raw, haystack, used):
    """A clean fact from one LLM item, or None if its quote is not in the CV or it does not validate."""
    if not isinstance(raw, dict) or raw.get("kind") not in ID_PREFIX:
        return None
    if not _backed(raw.get("source", ""), haystack, raw.get("name", ""), raw.get("title", ""), raw.get("org", "")):
        return None
    fact = {k: v for k, v in raw.items() if k not in ("source", "bullets", "id")}
    seed = (f"{fact.get('org', '')}-{str(fact.get('start', ''))[:4]}" if fact["kind"] == "experience"
            else fact.get("name", ""))
    base, n = f"{ID_PREFIX[fact['kind']]}.{slug(seed)}", 2
    fact["id"] = base
    while fact["id"] in used:
        fact["id"], n = f"{base}-{n}", n + 1
    bullets = []
    for b in raw.get("bullets") if isinstance(raw.get("bullets"), list) else []:
        if (isinstance(b, dict) and isinstance(b.get("text"), str)
                and _backed(b.get("source", ""), haystack, b["text"][:12])):
            bullets.append({"id": f"{fact['id']}.b{len(bullets) + 1}", "text": b["text"]})
    if bullets:
        fact["bullets"] = bullets
    if fact_errors(fact, "fact"):
        return None
    used.add(fact["id"])
    return fact


def draft_from_text(text, use_llm=True, log=print):
    """A v2 profile draft: contact details by regex and, with `use_llm`, facts the LLM found in the text."""
    draft = {"version": SCHEMA_VERSION, **_contact(text), "facts": []}
    if not use_llm:
        return draft
    reasons = looks_injected(text)
    if reasons:
        log(f"The CV text looks like a prompt injection ({', '.join(reasons)}); skipping the LLM step, "
            "only contact details were read.")
        return draft
    try:
        items = llm.extract_cv_facts(text[:MAX_CHARS])
    except llm.LLMError as e:
        log(f"Could not ask the LLM for facts ({e}); only contact details were read.")
        return draft
    if not isinstance(items, list):
        return draft
    haystack, used = _norm(text), set()
    facts = [f for f in (_fact(i, haystack, used) for i in items) if f]
    if len(facts) < len(items):
        log(f"Dropped {len(items) - len(facts)} facts the CV text does not back up.")
    draft["facts"] = facts
    return draft
