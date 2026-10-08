"""Facts: the citable statements of a v2 profile (skills with years, certificates, jobs, bullets, languages).

Every fact has a stable id such as `skill.python`. Form answers cite those ids, so a claim can be traced back
to the profile, and a CV generator can reorder facts by id without inventing any.
"""
import re
from dataclasses import dataclass

# Short forms people write in forms; mapped to the name used in the profile.
ALIASES = {"js": "javascript", "ts": "typescript", "py": "python", "k8s": "kubernetes", "postgres": "postgresql"}
_EDGE = r"(?<![\w+#]){}(?![\w+#])"


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
    out = {}
    for f in (profile or {}).get("facts") or []:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str):
            continue
        years = f.get("years")
        ok = isinstance(years, int | float) and not isinstance(years, bool)
        out[f["id"]] = Fact(f["id"], str(f.get("kind", "")), _text(f), years if ok else None)
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


def match_skills(facts, question):
    """Skill facts whose name (or a known alias of it) appears in `question`, as whole words, ignoring case."""
    q = str(question).lower()
    q += "".join(f" {canon}" for alias, canon in ALIASES.items() if re.search(_EDGE.format(re.escape(alias)), q))
    words = set(re.findall(r"\w+", q))
    found = []
    for f in facts.values():
        if f.kind != "skill" or not f.text:
            continue
        name = f.text.lower()
        tokens = re.findall(r"\w+", name)
        if re.search(_EDGE.format(re.escape(name)), q) or len(tokens) > 1 and set(tokens) <= words:
            found.append(f)
    return found


def years_for(facts, question):
    """Whole years of the best matching skill named in the question; 0 when none is named."""
    return int(max((f.years or 0 for f in match_skills(facts, question)), default=0))


def check_citations(ids, facts):
    """The ids in `ids` that are not facts of the profile, in order."""
    return [i for i in ids if i not in facts]
