"""Facts: the citable statements of a v2 profile (skills with years, certificates, jobs, bullets, languages).

Every fact has a stable id such as `skill.python`. Form answers cite those ids, so a claim can be traced back
to the profile, and a CV generator can reorder facts by id without inventing any.
"""
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Short forms people write in forms and the name they stand for. Works both ways: a profile that lists "JS"
# also answers a question about JavaScript.
ALIASES = {"js": "javascript", "ts": "typescript", "py": "python", "k8s": "kubernetes", "postgres": "postgresql"}
_EDGE = r"(?<![\w+#]){}(?![\w+#])"
_SYNONYMS = {}
for _short, _long in ALIASES.items():
    _SYNONYMS.setdefault(_short, {_short}).add(_long)
    _SYNONYMS.setdefault(_long, {_long}).add(_short)


@dataclass(frozen=True)
class Fact:
    id: str
    kind: str
    text: str
    years: float | None = None


def _join(*parts):
    return ", ".join(str(p) for p in parts if p not in (None, ""))


def _text(f):
    kind = f.get("kind")
    if kind == "experience":
        dates = f"{f['start']} to {f.get('end', 'present')}" if f.get("start") else ""
        return _join(f"{f.get('title', '')} at {f.get('org', '')}", dates)
    if kind == "education":
        return _join(f.get("name"), f.get("org"), f.get("year"))
    if kind == "language":
        return _join(f.get("name"), f.get("level"))
    if kind == "cert":
        return _join(f.get("name"), f.get("year"))
    return str(f.get("name", ""))


def load_facts(profile):
    """{id: Fact} for the facts and bullets of a profile dict. Entries that are not well formed are skipped
    (profile.validate reports them)."""
    out, seen = {}, {}
    for f in (profile or {}).get("facts") or []:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str):
            continue
        years = f.get("years")
        ok = isinstance(years, int | float) and not isinstance(years, bool)
        out[f["id"]] = Fact(f["id"], str(f.get("kind", "")), _text(f), years if ok else None)
        if f.get("kind") == "skill" and isinstance(f.get("name"), str):
            if f["name"].strip().lower() in seen:
                logger.warning("duplicate skill %r in the profile (%s and %s): the larger years are used",
                               f["name"], seen[f["name"].strip().lower()], f["id"])
            seen.setdefault(f["name"].strip().lower(), f["id"])
        for b in f.get("bullets") or []:
            if isinstance(b, dict) and isinstance(b.get("id"), str) and isinstance(b.get("text"), str):
                out[b["id"]] = Fact(b["id"], str(f.get("kind", "")), b["text"])
    return out


def facts_prompt(facts):
    """One line per fact: `[skill.python] Python, 3 years`."""
    lines = []
    for f in facts.values():
        years = "" if f.years is None else f", {f.years:g} year{'' if f.years == 1 else 's'}"
        lines.append(f"[{f.id}] {f.text}{years}")
    return "\n".join(lines)


def names_of(name):
    """The lowercase name and its aliases."""
    return _SYNONYMS.get(name, {name})


def _in_question(name, question):
    """`name` is in `question` as a whole word: C does not match C++, C# or "C-level". One-letter names
    (C, R) must also be capitalised, so that the letter in "a c section" is not a skill."""
    if len(name) == 1:
        return re.search(r"(?<!-)" + _EDGE.format(re.escape(name.upper())) + "(?!-)", question) is not None
    return re.search(_EDGE.format(re.escape(name)), question, re.I) is not None


def match_skills(facts, question):
    """Skill facts whose name (or an alias of it) is in `question` as a whole word, ignoring case. When two
    facts have the same name, only the one with the most years is returned."""
    q = str(question)
    words = set(re.findall(r"[\w+#]+", q.lower()))
    best = {}
    for f in facts.values():
        if f.kind != "skill" or not f.text:
            continue
        name = f.text.lower()
        tokens = re.findall(r"[\w+#]+", name)
        hit = (any(_in_question(n, q) for n in names_of(name))
               or len(tokens) > 1 and set(tokens) <= words)
        if hit and (name not in best or (f.years or 0) > (best[name].years or 0)):
            best[name] = f
    return list(best.values())


def years_for(facts, question):
    """Whole years of the best matching skill named in the question; None when no skill matches."""
    found = match_skills(facts, question)
    return int(max(f.years or 0 for f in found)) if found else None


def check_citations(ids, facts):
    """The ids in `ids` that are not facts of the profile, in order."""
    return [i for i in ids if i not in facts]
