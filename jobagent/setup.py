"""Interactive profile setup (`python -m jobagent --setup`).

Asks field by field, offering the draft value (from an old profile or a CV) in brackets, re-asks anything the
profile validator would reject, and shows the final YAML. Nothing touches the disk until the user answers y,
once. The file is replaced atomically and the old one is kept as profile.yaml.bak-YYYYMMDD-HHMMSS.
"""
import datetime as dt
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from jobagent.profile import (
    EMAIL,
    ID_PATTERN,
    ID_PREFIX,
    LANGUAGES,
    PREFIX,
    SCHEMA_VERSION,
    is_date,
    is_number,
    migrate,
    new_id,
    validate,
)

YES = ("y", "yes")
CLEAR = "-"  # typed on a draft item or optional field: remove it

# (key, label, kind, required)
FLAT = [("first_name", "First name", "text", True), ("last_name", "Last name", "text", True),
        ("email", "Email", "email", True), ("phone", "Phone", "text", False), ("city", "City", "text", False),
        ("country", "Country", "text", False), ("timezone", "Time zone", "text", False),
        ("linkedin", "LinkedIn URL", "text", False), ("github", "GitHub URL", "text", False),
        ("work_mode", "Work mode (remote, hybrid, on-site)", "text", False),
        ("available_to_start", "Available to start", "text", False),
        ("expected_salary_usd_monthly", "Expected monthly salary in USD", "number", False),
        ("summary", "Short summary", "text", False)]


def _text(raw):
    return raw


def _email(raw):
    if not EMAIL.fullmatch(raw):
        raise ValueError("an email looks like name@example.com")
    return raw


def _number(raw):
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        value = -1
    if not is_number(value):
        raise ValueError("enter a number of 0 or more, such as 3 or 1.5")
    return int(value) if value == int(value) else value


def _year(raw):
    if not (raw.isdigit() and 1900 <= int(raw) <= 2100):
        raise ValueError("enter a four-digit year, such as 2024")
    return int(raw)


def _start(raw):
    if not is_date(raw):
        raise ValueError("enter a date as YYYY-MM, such as 2023-01")
    return raw


def _end(raw):
    if not is_date(raw, allow_present=True):
        raise ValueError("enter a date as YYYY-MM or the word present")
    return raw


CONVERT = {"text": _text, "email": _email, "number": _number, "year": _year, "start": _start, "end": _end}


class _Asker:
    def __init__(self, ask, out):
        self.ask, self.out = ask, out
        self.used = set()  # fact ids taken so far, bullets included; an id that was freed is not handed out again
        self.assigned = set()  # ids of the facts already in the new profile

    def field(self, label, default=None, kind="text", required=False):
        """One value. Enter keeps the default; '-' clears a default or an optional value (returns None).
        Invalid input is explained and asked again."""
        convert = CONVERT[kind]
        has_default = default not in (None, "")
        while True:
            raw = self.ask(f"{label} [{default}]: " if has_default else f"{label}: ").strip()
            if raw == CLEAR and not required:
                return None
            if raw == "":
                if not has_default:
                    if not required:
                        return None
                    self.out(f"{label} is required.")
                    continue
                raw = str(default)
            try:
                return convert(raw)
            except ValueError as e:
                self.out(f"{label}: {e}")

    def new_id(self, kind, seed):
        fact_id = new_id(ID_PREFIX[kind], seed, self.used)
        self.used.add(fact_id)
        return fact_id

    def bullets(self, fact_id, drafts):
        out = []
        for b in drafts:
            text = self.field("Bullet", b.get("text"))
            if text:
                out.append({"id": b.get("id") or self._bullet_id(fact_id), "text": text})
        while True:
            text = self.field("Add another bullet (blank to finish)")
            if not text:
                return out
            out.append({"id": self._bullet_id(fact_id), "text": text})

    def _bullet_id(self, fact_id):
        n = 1
        while f"{fact_id}.b{n}" in self.used:
            n += 1
        self.used.add(f"{fact_id}.b{n}")
        return f"{fact_id}.b{n}"


# kind: (label, key of the main field, extra fields as (key, label, kind, required))
KINDS = {
    "skill": ("skill", "name", [("years", "Years of experience", "number", True)]),
    "cert": ("certificate", "name", [("year", "Year", "year", False)]),
    "experience": ("experience", "title", [
        ("org", "Company", "text", True), ("start", "Start (YYYY-MM)", "start", True),
        ("end", "End (YYYY-MM or present)", "end", False)]),
    "education": ("education entry", "name", [("org", "School", "text", False), ("year", "Year", "year", False)]),
    "language": ("language", "name", [("level", "Level (A1-C2, native)", "text", False)]),
}


def _usable_id(value, kind):
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value)) and value.startswith(ID_PREFIX[kind] + ".")


def _collect(a, kind, drafts):
    """Asks for every fact of one kind: the draft ones first, then new ones until a blank name."""
    label, main, extras = KINDS[kind]
    out = []

    def build(draft, name=None):
        name = name or a.field(label.capitalize() if main == "name" else "Job title", draft.get(main))
        if name is None:
            a.used.discard(draft.get("id"))
            return
        fact = {"id": draft.get("id"), "kind": kind, main: name}
        for key, text, ekind, required in extras:
            default = draft.get(key, "present" if key == "end" and not draft else None)
            value = a.field(text, default, ekind, required)
            if value is not None:
                fact[key] = value
        known = {"id", "kind", "bullets", main, *(e[0] for e in extras)}
        fact.update({k: v for k, v in draft.items() if k not in known})  # keys the interview doesn't ask about
        if not _usable_id(fact["id"], kind) or fact["id"] in a.assigned:
            seed = f"{fact['org']}-{str(fact['start'])[:4]}" if kind == "experience" else name
            fact["id"] = a.new_id(kind, seed)
        a.assigned.add(fact["id"])
        if kind == "experience":
            bullets = draft.get("bullets")
            fact["bullets"] = a.bullets(fact["id"], [b for b in bullets if isinstance(b, dict)]
                                        if isinstance(bullets, list) else [])
        out.append(fact)

    for d in drafts:
        build(d)
    while True:
        name = a.field(f"Add another {label} (blank to finish)")
        if not name:
            return out
        build({}, name)


def _split_draft(draft, out):
    """The draft's facts by kind. Anything that can't be kept is reported, not silently lost."""
    facts = draft.get("facts")
    if facts is not None and not isinstance(facts, list):
        out(f"Dropped from the draft: facts is not a list ({facts!r:.60}).")
        facts = []
    by_kind = {k: [] for k in KINDS}
    for f in facts or []:
        if isinstance(f, dict) and f.get("kind") in KINDS:
            by_kind[f["kind"]].append(f)
        else:
            out(f"Dropped from the draft: {f!r:.80} is not a fact of a known kind.")
    return by_kind


def _converted(draft, by_kind):
    """Legacy flat keys (degree, english...) that the migration turned into facts."""
    degree = str(draft.get("degree") or "").strip()
    keys = ["degree"] if degree and any(f.get("name") == degree for f in by_kind["education"]) else []
    return keys + [k for k in LANGUAGES if draft.get(k)
                   and any(f.get("name") == k.capitalize() for f in by_kind["language"])]


def _drop_invalid(profile, kept, out):
    """Removes the facts (and kept keys) the validator rejects, saying so. Returns the problems left."""
    problems = validate(profile)
    bad = {}
    for msg in problems:
        if m := re.match(rf"{re.escape(PREFIX)}facts\[(\d+)\]", msg):
            bad.setdefault(int(m[1]), []).append(msg[len(PREFIX):])
    for i in sorted(bad, reverse=True):
        fact = profile["facts"].pop(i)
        out(f"Dropped {fact.get('id', fact)!r} because it is not valid: {'; '.join(bad[i])}")
    for key in [k for k in kept if any(msg[len(PREFIX):].startswith(k) for msg in problems)]:
        out(f"Dropped the draft key {key!r} because it is not valid.")
        profile.pop(key)
    return validate(profile) if bad or problems else []


def interview(ask=input, out=print, draft=None):
    """Runs the questions and returns the new v2 profile, or None if it can't be made valid."""
    a = _Asker(ask, out)
    draft = migrate(draft or {})
    asked = {f[0] for f in FLAT}
    drafts = _split_draft(draft, out)
    converted = _converted(draft, drafts)
    if converted:
        out(f"Moved {', '.join(converted)} into facts; the old keys are not written.")
    kept = {k: v for k, v in draft.items()
            if k not in ("version", "facts", *converted) and k not in asked}
    a.used = {i for fs in drafts.values() for f in fs
              for i in [f.get("id"), *(b.get("id") for b in f.get("bullets") or [] if isinstance(b, dict))]
              if isinstance(i, str)}
    out("Press Enter to keep the value in brackets, type - to clear one.")
    flat = {}
    for key, label, kind, required in FLAT:
        value = a.field(label, draft.get(key), kind, required)
        if value is not None:
            flat[key] = value
    facts = [f for kind in KINDS for f in _collect(a, kind, drafts[kind])]
    profile = {"version": SCHEMA_VERSION, **flat, **kept, "facts": facts}
    problems = _drop_invalid(profile, kept, out)
    if problems:
        out("The profile has problems, nothing was written:\n" + "\n".join(problems))
        return None
    return profile


def _backup_path(path):
    stamp = f"{path.name}.bak-{dt.datetime.now():%Y%m%d-%H%M%S}"
    candidate, n = path.with_name(stamp), 2
    while candidate.exists():
        candidate, n = path.with_name(f"{stamp}-{n}"), n + 1
    return candidate


def write_profile(profile, path, out=print):
    """Writes the profile as YAML through a temp file in the same folder, then swaps it in. An existing file
    is copied to profile.yaml.bak-YYYYMMDD-HHMMSS first (earlier backups are never overwritten). If the disk
    refuses (a file locked by OneDrive, say) the YAML goes to profile.yaml.new instead. True if `path` was
    written."""
    path = Path(path)
    text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)
    tmp = None
    try:
        if path.exists():
            backup = _backup_path(path)
            shutil.copy2(path, backup)
            out(f"Kept the previous file as {backup.name}.")
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except OSError as e:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        fallback = path.with_name(path.name + ".new")
        try:
            fallback.write_text(text, encoding="utf-8")
            out(f"Could not write {path.name} ({e}). Your answers are in {fallback.name}; "
                f"copy it over {path.name} once the file is free.")
        except OSError as e2:
            out(f"Could not write {path.name} ({e}) or {fallback.name} ({e2}). Your answers:\n{text}")
        return False


def load_draft(path, ask=input, out=print):
    """The existing profile as a v2 draft (no validation, so a file with mistakes can be fixed here).
    {} if there is none. If it exists but can't be read, says why and asks whether to start blank: None
    (abort) unless the answer is yes."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("the top level must be a mapping of fields")
    except (OSError, ValueError, yaml.YAMLError) as e:  # YAMLError is not a ValueError
        reason = str(e).splitlines()[0] if str(e) else type(e).__name__
        out(f"{path.name} can't be used as a starting point ({reason}).")
        return {} if ask("Start from a blank profile instead? [y/N] ").strip().lower() in YES else None
    return migrate(data)


def setup(path, draft=None, ask=input, out=print):
    """Interview, then write `path` if the user confirms (one question). True if a file was written."""
    path = Path(path)
    profile = interview(ask, out, draft)
    if profile is None:
        out("Nothing written.")
        return False
    out("\n" + yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
    question = (f"Overwrite the existing {path.name}? A timestamped backup is kept. [y/N] " if path.exists()
                else f"Write {path.name}? [y/N] ")
    if ask(question).strip().lower() not in YES:
        out("Nothing written.")
        return False
    written = write_profile(profile, path, out)
    if written:
        out(f"Wrote {path}.")
    return written
