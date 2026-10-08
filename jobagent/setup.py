"""Interactive profile setup (`python -m jobagent --setup`).

Asks field by field, offering the draft value (from an old profile or a CV) in brackets, re-asks anything the
profile validator would reject, and shows the final YAML. Nothing touches the disk until the user answers y.
"""
import shutil
from pathlib import Path

import yaml

from jobagent.profile import EMAIL, ID_PREFIX, SCHEMA_VERSION, is_date, is_number, migrate, slug, validate

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
    if not EMAIL.match(raw):
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
        self.used = set()  # fact ids taken so far, bullets included

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

    def new_id(self, base):
        candidate, n = base, 2
        while candidate in self.used:
            candidate, n = f"{base}-{n}", n + 1
        self.used.add(candidate)
        return candidate

    def bullets(self, fact_id, drafts):
        out = []
        for b in drafts:
            text = self.field("Bullet", b.get("text"))
            if text:
                out.append({"id": b.get("id") or self._bullet_id(fact_id), "text": text})
            else:
                self.used.discard(b.get("id"))
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
        if not fact["id"]:
            seed = f"{fact['org']}-{str(fact['start'])[:4]}" if kind == "experience" else name
            fact["id"] = a.new_id(f"{ID_PREFIX[kind]}.{slug(seed)}")
        if kind == "experience":
            fact["bullets"] = a.bullets(fact["id"], draft.get("bullets") or [])
        out.append(fact)

    for d in drafts:
        build(d)
    while True:
        name = a.field(f"Add another {label} (blank to finish)")
        if not name:
            return out
        build({}, name)


def interview(ask=input, out=print, draft=None):
    """Runs the questions and returns the new v2 profile, or None if the user doesn't confirm at the end."""
    a = _Asker(ask, out)
    draft = migrate(draft or {})
    asked = {f[0] for f in FLAT}
    kept = {k: v for k, v in draft.items() if k not in ("version", "facts") and k not in asked}
    drafts = {k: [f for f in draft.get("facts") or [] if isinstance(f, dict) and f.get("kind") == k]
              for k in KINDS}
    a.used = {f["id"] for fs in drafts.values() for f in fs if isinstance(f.get("id"), str)}
    out("Press Enter to keep the value in brackets, type - to clear one.")
    flat = {}
    for key, label, kind, required in FLAT:
        value = a.field(label, draft.get(key), kind, required)
        if value is not None:
            flat[key] = value
    facts = [f for kind in KINDS for f in _collect(a, kind, drafts[kind])]
    profile = {"version": SCHEMA_VERSION, **flat, **kept, "facts": facts}
    problems = validate(profile)
    if problems:
        out("The profile has problems, nothing was written:\n" + "\n".join(problems))
        return None
    out("\n" + yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
    return profile if ask("Write profile.yaml? [y/N] ").strip().lower() in YES else None


def write_profile(profile, path, confirm):
    """Writes the profile as YAML. An existing file is only replaced if confirm() says yes, and a .bak copy
    of it is kept. Returns True if the file was written."""
    path = Path(path)
    if path.exists():
        if not confirm():
            return False
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True


def load_draft(path):
    """The existing profile as a v2 draft (no validation, so a file with mistakes can be fixed here); {} if
    there is none or it can't be read."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return migrate(data) if isinstance(data, dict) else {}


def setup(path, draft=None, ask=input, out=print):
    """Interview, then write `path` if the user confirms. Returns True if a file was written."""
    path = Path(path)
    profile = interview(ask, out, draft)
    if profile is None:
        out("Nothing written.")
        return False

    def overwrite():
        return ask(f"{path.name} already exists. Overwrite it (a .bak copy is kept)? [y/N] ").strip().lower() in YES

    written = write_profile(profile, path, overwrite)
    out(f"Wrote {path}." if written else f"Kept the existing {path.name}; nothing written.")
    return written
