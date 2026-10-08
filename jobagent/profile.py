"""The candidate profile: schema v2 (flat fields plus citable facts), validation and the v1 migration.

Stdlib and PyYAML only. A v1 profile (no `version`) is upgraded in memory on load; the file on disk is only
rewritten by `--setup`, after the user confirms.
"""
import copy
import logging
import math
import re
from pathlib import Path

import yaml

from jobagent.safety import strip_sensitive

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2
KINDS = {"skill", "cert", "experience", "education", "language"}
ID_PREFIX = {"skill": "skill", "cert": "cert", "experience": "exp", "education": "edu", "language": "lang"}
ID_PATTERN = re.compile(r"^(skill|cert|exp|edu|lang)\.[a-z0-9-]+(\.[a-z0-9-]+)?$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
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
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "item"


def is_number(value):
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def is_date(value, allow_present=False):
    return isinstance(value, str) and (bool(DATE.match(value)) or allow_present and value == "present")


def migrate(data):
    """Returns a v2 copy of `data`. Pure and idempotent: v2 (or newer) input comes back unchanged."""
    out = copy.deepcopy(data)
    if not isinstance(out, dict) or out.get("version") not in (None, 1):
        return out
    logger.info("v1 profile, run --setup to upgrade")
    facts = list(out.get("facts") or [])
    years = out.pop("years_of_experience", None)
    for key, value in (years.items() if isinstance(years, dict) else []):
        words = str(key).replace("_", " ").split()
        name = " ".join(w.upper() if w in ACRONYMS else w for w in words)
        facts.append({"id": f"skill.{slug(key)}", "kind": "skill", "name": name[:1].upper() + name[1:],
                      "years": value})
    if isinstance(out.get("degree"), str) and out["degree"].strip():
        facts.append({"id": "edu.degree", "kind": "education", "name": out["degree"].strip()})
    for lang in LANGUAGES:
        if out.get(lang):
            facts.append({"id": f"lang.{lang}", "kind": "language", "name": lang.capitalize(),
                          "level": str(out[lang]).strip()})
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
        if not isinstance(value, str) or not ID_PATTERN.match(value):
            errs.append(f"{PREFIX}{label} must look like skill.python or exp.acme-2023.b1 (got {value!r})")
        elif value in seen:
            errs.append(f"{PREFIX}{label} {value!r} is a duplicate")
        else:
            seen.add(value)

    check_id(fact.get("id"), f"{where}.id")
    kind = fact.get("kind")
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
    if not isinstance(version, int) or isinstance(version, bool):
        errs.append(f"{PREFIX}version must be a number (got {version!r})")
    elif version > SCHEMA_VERSION:
        errs.append(f"{PREFIX}version {version} was made by a newer jobagent (this one reads up to {SCHEMA_VERSION})")
    for key in REQUIRED_FLAT:
        if not _need_text(data.get(key)):
            errs.append(f"{PREFIX}{key} is required")
    if _need_text(data.get("email")) and not EMAIL.match(data["email"].strip()):
        errs.append(f"{PREFIX}email must look like name@example.com (got {data['email']!r})")
    facts = data.get("facts") or []
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
