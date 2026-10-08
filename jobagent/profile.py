"""The candidate profile: schema v2 (flat fields plus citable facts), validation and the v1 migration.

Stdlib and PyYAML only. A v1 profile (no `version`) is upgraded in memory on load; the file on disk is only
rewritten by `--setup`, after the user confirms.
"""
import copy
import logging
import math
import re
import unicodedata
from itertools import chain, count
from pathlib import Path

import yaml

from jobagent.safety import strip_sensitive

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
KINDS = {"skill", "cert", "experience", "education", "language"}
ID_PREFIX = {"skill": "skill", "cert": "cert", "experience": "exp", "education": "edu", "language": "lang"}
# Matched with fullmatch: a `$` would let a trailing newline through.
ID_PATTERN = re.compile(r"(skill|cert|exp|edu|lang)\.[a-z0-9-]+(\.[a-z0-9-]+)?")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
DATE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
REQUIRED_FLAT = ("first_name", "last_name", "email")
REQUIRED_FACT = {"skill": ("name",), "cert": ("name",), "experience": ("title", "org"), "education": ("name",),
                 "language": ("name",)}
LANGUAGES = ("english", "spanish", "portuguese", "french", "german", "italian")
ACRONYMS = {"sql", "api", "apis", "rest", "aws", "css", "html", "ci", "cd", "ml", "ai"}
PREFIX = "profile.yaml: "


class ProfileError(Exception):
    """The profile can't be used. `messages` has every problem found, not just the first."""

    def __init__(self, messages):
        self.messages = list(messages)
        super().__init__("\n".join(self.messages))


def slug(text):
    """Lowercase ASCII words joined by "-". "+" and "#" are spelled out so that C, C++ and C# differ; accents
    are dropped. Empty when nothing usable is left (e.g. a name in another alphabet)."""
    text = unicodedata.normalize("NFKD", str(text)).replace("+", " plus ").replace("#", " sharp ")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def new_id(prefix, text, used):
    """An id like `skill.c-plus-plus` that is not in `used`. A "-2", "-3"... suffix breaks ties; a name with
    nothing to slug becomes `item-1`, `item-2`... The caller adds the id to `used`."""
    name = slug(text)
    names = chain([name], (f"{name}-{n}" for n in count(2))) if name else (f"item-{n}" for n in count(1))
    return next(f"{prefix}.{n}" for n in names if f"{prefix}.{n}" not in used)


def is_number(value):
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def is_date(value, allow_present=False):
    return isinstance(value, str) and (bool(DATE.fullmatch(value)) or allow_present and value == "present")


def migrate(data):
    """Returns a v2 copy of `data`. Pure and idempotent: v2 (or newer) input comes back unchanged."""
    out = copy.deepcopy(data)
    version = out.get("version") if isinstance(out, dict) else 0
    if version is not None and (type(version) is not int or version != 1):
        return out
    logger.info("v1 profile, run --setup to upgrade")
    facts = out.get("facts")
    if facts is not None and not isinstance(facts, list):  # validate() reports it
        out.pop("version", None)
        return {"version": SCHEMA_VERSION, **out}
    facts = list(facts or [])
    used = {i for f in facts if isinstance(f, dict)
            for i in [f.get("id"), *(b.get("id") for b in f.get("bullets") or [] if isinstance(b, dict))]
            if isinstance(i, str)}

    def add(fact):
        fact = {"id": new_id(ID_PREFIX[fact["kind"]], fact.pop("seed"), used), **fact}
        used.add(fact["id"])
        facts.append(fact)

    years = out.pop("years_of_experience", None)
    for key, value in (years.items() if isinstance(years, dict) else []):
        words = str(key).replace("_", " ").split()
        name = " ".join(w.upper() if w in ACRONYMS else w for w in words)
        add({"seed": key, "kind": "skill", "name": name[:1].upper() + name[1:], "years": value})
    if isinstance(out.get("degree"), str) and out["degree"].strip():
        add({"seed": "degree", "kind": "education", "name": out["degree"].strip()})
    for lang in LANGUAGES:
        if out.get(lang):
            add({"seed": lang, "kind": "language", "name": lang.capitalize(), "level": str(out[lang]).strip()})
    out.pop("version", None)
    return {"version": SCHEMA_VERSION, **out, "facts": facts}


def _need_text(value):
    return isinstance(value, str) and bool(value.strip())


def fact_errors(fact, where, seen=None):
    """Messages for one fact (and its bullets). `seen` is the set of ids already used, updated in place."""
    seen = set() if seen is None else seen
    if not isinstance(fact, dict):
        return [f"{PREFIX}{where} must be a mapping (got {fact!r})"]
    errs = []

    def check_id(value, label):
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            errs.append(f"{PREFIX}{label} must look like skill.python or exp.acme-2023.b1 (got {value!r})")
        elif value.partition(".")[0] != ID_PREFIX.get(kind):
            errs.append(f"{PREFIX}{label} {value!r} has the wrong prefix for kind {kind!r}: "
                        f"use {ID_PREFIX.get(kind, '?')}.")
        elif value in seen:
            errs.append(f"{PREFIX}{label} {value!r} is a duplicate")
        else:
            seen.add(value)

    kind = fact.get("kind")
    check_id(fact.get("id"), f"{where}.id")
    if kind not in KINDS:
        errs.append(f"{PREFIX}{where}.kind must be one of {sorted(KINDS)} (got {kind!r})")
    for key in REQUIRED_FACT.get(kind, ()):
        if not _need_text(fact.get(key)):
            errs.append(f"{PREFIX}{where}.{key} is required for kind {kind}")
    if "years" in fact and not is_number(fact["years"]):
        errs.append(f"{PREFIX}{where}.years must be a number >= 0 (got {fact['years']!r})")
    if "year" in fact and not (isinstance(fact["year"], int) and not isinstance(fact["year"], bool)
                               and 1900 <= fact["year"] <= 2100):
        errs.append(f"{PREFIX}{where}.year must be a four-digit year (got {fact['year']!r})")
    for key in ("start", "end"):
        if key in fact and not is_date(fact[key], allow_present=key == "end"):
            errs.append(f"{PREFIX}{where}.{key} must be YYYY-MM{' or present' if key == 'end' else ''} "
                        f"(got {fact[key]!r})")
    if kind == "experience" and "start" not in fact:
        errs.append(f"{PREFIX}{where}.start is required for kind experience")
    if (is_date(fact.get("start")) and is_date(fact.get("end")) and fact["end"] < fact["start"]):
        errs.append(f"{PREFIX}{where}.end {fact['end']} is before start {fact['start']}")
    bullets = fact.get("bullets", [])
    if not isinstance(bullets, list):
        errs.append(f"{PREFIX}{where}.bullets must be a list")
        bullets = []
    for j, b in enumerate(bullets):
        label = f"{where}.bullets[{j}]"
        if not isinstance(b, dict):
            errs.append(f"{PREFIX}{label} must be a mapping with id and text (got {b!r})")
            continue
        check_id(b.get("id"), f"{label}.id")
        if not _need_text(b.get("text")):
            errs.append(f"{PREFIX}{label}.text is required")
    return errs


def validate(data):
    """Every problem in a (migrated) profile as a list of messages; empty when it is valid."""
    if not isinstance(data, dict):
        return [f"{PREFIX}the top level must be a mapping of fields"]
    errs = []
    version = data.get("version", SCHEMA_VERSION)
    if type(version) is not int or version < 1:
        errs.append(f"{PREFIX}version must be a whole number of 1 or more (got {version!r})")
    elif version > SCHEMA_VERSION:
        errs.append(f"{PREFIX}version {version} was made by a newer jobagent (this one reads up to {SCHEMA_VERSION})")
    for key in REQUIRED_FLAT:
        if not _need_text(data.get(key)):
            errs.append(f"{PREFIX}{key} is required")
    if _need_text(data.get("email")) and not EMAIL.fullmatch(data["email"]):
        errs.append(f"{PREFIX}email must look like name@example.com (got {data['email']!r})")
    if "years_of_experience" in data and type(version) is int and version >= 2:
        errs.append(f"{PREFIX}years_of_experience is a version 1 key; put the years in skill facts "
                    "(run --setup to convert)")
    for key, value in data.items():
        if key.startswith("expected_salary") and value is not None and not is_number(value):
            errs.append(f"{PREFIX}{key} must be a number >= 0 (got {value!r})")
    rules = data.get("fixed_answers")
    if rules is not None and not isinstance(rules, list):
        errs.append(f"{PREFIX}fixed_answers must be a list of pattern/value pairs")
    for i, rule in enumerate(rules if isinstance(rules, list) else []):
        if not isinstance(rule, dict) or not isinstance(rule.get("pattern"), str) or "value" not in rule:
            errs.append(f"{PREFIX}fixed_answers[{i}] needs a pattern and a value (got {rule!r})")
            continue
        try:
            re.compile(rule["pattern"])
        except re.error as e:
            errs.append(f"{PREFIX}fixed_answers[{i}].pattern {rule['pattern']!r} is not a valid regex ({e})")
    facts = data.get("facts")
    if facts is None:
        return errs
    if not isinstance(facts, list):
        return errs + [f"{PREFIX}facts must be a list"]
    seen = set()
    for i, fact in enumerate(facts):
        errs += fact_errors(fact, f"facts[{i}]", seen)
    return errs


def load_profile(path):
    """Reads, migrates and validates a profile file. Raises ProfileError listing every problem."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ProfileError([f"{PREFIX}not valid YAML ({str(e).splitlines()[0]})"]) from e
    data = migrate(raw)
    errs = validate(data)
    if errs:
        raise ProfileError(errs)
    return data


def dump(profile):
    """The profile as YAML for prompts, without keys about ids, banking, passwords or birth dates."""
    return yaml.safe_dump(strip_sensitive(profile), allow_unicode=True, sort_keys=False)
