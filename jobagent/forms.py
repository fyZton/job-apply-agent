"""Reads any application form, decides the answers and fills them in."""
import difflib
import json
import re
from pathlib import Path

from jobagent import llm
from jobagent.core import pause
from jobagent.facts import check_citations, load_facts, match_skills
from jobagent.safety import is_sensitive, looks_injected

# Walks the visible fields inside `root`, tags each with a data-ap attribute and returns their description.
JS_SCAN = r"""
(root) => {
  const out = []; let n = 0;
  // Ids restart on every scan: drop stale tags so one id never matches two fields.
  root.querySelectorAll('[data-ap]').forEach(e => e.removeAttribute('data-ap'));
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const byId = id => root.querySelector(`label[for="${CSS.escape(id)}"]`) || document.querySelector(`label[for="${CSS.escape(id)}"]`);
  const label = el => {
    if (el.id) { const l = byId(el.id); if (l && txt(l)) return txt(l); }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(' ').map(i => txt(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    const wrap = el.closest('label'); if (wrap && txt(wrap)) return txt(wrap);
    let p = el.parentElement;
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) { const t = txt(p); if (t && t.length < 300) return t; }
    return el.name || el.placeholder || '';
  };
  const context = el => { const fs = el.closest('fieldset'); const lg = fs && fs.querySelector('legend'); return lg ? txt(lg).slice(0, 300) : ''; };
  // Question of a radio group: climb to the container that holds every radio and has more than the options.
  const groupQuestion = (el, group, options) => {
    let p = el.parentElement;
    for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
      if (!group.every(r => p.contains(r))) continue;
      let t = txt(p);
      options.forEach(o => { t = t.replace(o, ' '); });
      t = t.replace(/este campo es obligatorio|this field is required|please make a selection/ig, ' ').replace(/\s+/g, ' ').trim();
      if (t.length > 3) return t;
    }
    return '';
  };
  // Visible text of an option: its <label> or, if empty, the closest text not shared with other options.
  const optionText = (r, group) => {
    const l = r.id && byId(r.id); if (l && txt(l)) return txt(l);
    let p = r.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      if (group.some(o => o !== r && p.contains(o))) break;
      const t = txt(p); if (t) return t;
    }
    return r.value || r.getAttribute('aria-label') || '';
  };
  const radios = new Set();
  root.querySelectorAll('input, select, textarea').forEach(el => {
    const type = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : (el.type || 'text').toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search', 'password'].includes(type)) return;
    if (/buscar|search/i.test((el.name || '') + ' ' + (el.placeholder || ''))) return;
    if (!['radio', 'checkbox', 'file'].includes(type) && !vis(el)) return;
    if (el.disabled) return;
    if (type === 'radio') {
      const name = el.name; if (!name || radios.has(name)) return; radios.add(name);
      const group = Array.from(root.querySelectorAll(`input[type=radio][name="${CSS.escape(name)}"]`));
      const id = 'ap' + (n++);
      group.forEach((r, i) => r.setAttribute('data-ap', id + '_' + i));
      const checked = group.find(r => r.checked);
      const options = group.map(r => optionText(r, group));
      const aria = el.getAttribute('aria-label');
      const sharedAria = aria && group.every(r => r.getAttribute('aria-label') === aria) ? aria : '';
      const around = groupQuestion(el, group, options);
      const question = context(el) || sharedAria || around || label(el);
      out.push({id, type: 'radio', question: question.slice(0, 300), options,
                value: checked ? optionText(checked, group) : '',
                required: group.some(r => r.required) || /\*|obligatori|required/i.test(question + ' ' + around)});
      return;
    }
    const id = 'ap' + (n++);
    el.setAttribute('data-ap', id);
    const c = {id, type, question: label(el).slice(0, 300), required: el.required || el.getAttribute('aria-required') === 'true'};
    const ctx = context(el); if (ctx && ctx !== c.question) c.context = ctx;
    if (type === 'select') {
      c.options = Array.from(el.options).map(o => o.text.trim()).filter(t => t);
      c.value = el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : '';
    } else if (type === 'checkbox') {
      c.value = el.checked;
      // "Confirmed"-style boxes: the real question (and the required *) is in the surrounding text.
      const around = groupQuestion(el, [el], [c.question]);
      if (around && !c.context) c.context = around.slice(0, 300);
      if (/\*|obligatori|required/i.test(around)) c.required = true;
    } else {
      c.value = el.value || '';
    }
    if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list') c.autocomplete = true;
    out.push(c);
  });
  return out;
}
"""

PLACEHOLDER = re.compile(r"^(select|selecciona|seleccionar|choose|elige|escoge|--|-)", re.I)
YEARS_QUESTION = re.compile(r"\byears?\b|\baños\b", re.I)
# What a years question is about: the word after "with|in|of|using|on|con|en|de|usando" or before "experience".
ABOUT = re.compile(r"\b(?:with|in|of|using|on|con|en|de|usando)\s+(?:(?:the|a|an|el|la|un|una)\s+)?([\w+#.-]+)"
                   r"|([\w+#.-]+)\s+experience\b", re.I)
NOT_A_SKILL = set(
    "experience experiencia years year a\u00f1os a\u00f1o professional profesional total overall work working trabajo "
    "relevant relevante industry the a an your tu su do you have tienes tiene how many much cu\u00e1ntos cuantos "
    "field area role position puesto software development desarrollo programming programaci\u00f3n this that our "
    "similar related of in".split())


def _lower_bound(option):
    """The least number of years an option claims: "3-5" is 3, "5+" is 5, "Less than 1" is 0, "M\u00e1s de 3" is 3.
    None when the option has no number."""
    text = str(option).lower()
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    if not m:
        return None
    if re.search(r"less than|under|up to|menos de|hasta|<", text[:m.start()]):
        return 0.0
    return float(m.group().replace(",", "."))
IS_CV = re.compile(r"resume|curr[ií]cul|\bcv\b|hoja de vida", re.I)


def normalize(text):
    return re.sub(r"[^a-z0-9áéíóúñü ]", "", re.sub(r"\s+", " ", str(text).lower())).strip()[:200]


def best_option(value, options):
    """Index of the option that best matches `value` (exact, then substring, then fuzzy), or None."""
    v = normalize(value)
    norm = [normalize(o) for o in options]
    for i, o in enumerate(norm):
        if o == v:
            return i
    for i, o in enumerate(norm):
        if v and (v in o or o in v) and o:
            return i
    # 0.8 tolerates typos ("venezula") but not different words: at 0.5 "maybe" matched "yes".
    close = difflib.get_close_matches(v, norm, n=1, cutoff=0.8)
    return norm.index(close[0]) if close else None


def _set_checked(el, state):
    """Checks/unchecks a radio or checkbox. Custom (React) widgets sometimes ignore a direct click,
    so it tries: check() -> click its <label> -> click through JavaScript."""
    tries = [
        lambda: el.check(force=True, timeout=3000) if state else el.uncheck(force=True, timeout=3000),
        lambda: el.evaluate("e => { const l = e.id && document.querySelector(`label[for='${e.id}']`); (l || e).click(); }"),
        lambda: el.evaluate("e => e.click()"),
    ]
    for attempt in tries:
        try:
            if el.is_checked() == state:
                return
            attempt()
        except Exception:
            continue


def _empty(field):
    v = field.get("value")
    if field["type"] == "checkbox":
        return not v
    return v in ("", None) or (field["type"] == "select" and bool(PLACEHOLDER.match(str(v))))


class FormAssistant:
    def __init__(self, profile, profile_text, data_dir, model, log, forced_reply=None):
        self.profile = profile
        self.profile_text = profile_text
        self.model = model
        self.log = log
        self.forced_reply = forced_reply  # evals only: stands in for the model's reply
        self.cache_path = Path(data_dir) / "learned_answers.json"
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}
        self.rules = [(re.compile(r["pattern"], re.I), r["value"]) for r in profile.get("fixed_answers", [])]
        self.facts = load_facts(profile)  # empty for a v1 profile: answers are then not checked against facts
        self.v2 = isinstance(profile.get("version"), int) and profile["version"] >= 2
        self._warned = False

    def _save_cache(self):
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _valid(self, field, value):
        if field.get("options"):
            return best_option(value, field["options"]) is not None
        return value not in (None, "")

    def _years_scope(self, text):
        """None if `text` is not a years question (or a v1 profile has no years). Otherwise (kind, names, limit):
        "named" (it names profile skills: limit is the best of their years), "other" (it names something that
        is not a profile skill: limit 0) or "generic" (names nothing: limit is the profile's best skill)."""
        if not YEARS_QUESTION.search(text):
            return None
        if self.facts:
            skills = {f.text.lower(): float(f.years or 0) for f in self.facts.values() if f.kind == "skill"}
            named = {f.text.lower(): float(f.years or 0) for f in match_skills(self.facts, text)}
        else:
            skills = {str(k).lower(): v for k, v in (self.profile.get("years_of_experience") or {}).items()
                      if isinstance(v, int | float) and not isinstance(v, bool)}
            if not skills:
                return None
            words = set(re.findall(r"\w+", text.lower()))
            named = {k: v for k, v in skills.items() if set(k.split("_")) <= words}
        if named:
            return "named", set(named), max(named.values())
        if any(not w.isdigit() and w not in NOT_A_SKILL
               for w in (m.strip(".-").lower() for g in ABOUT.findall(text) for m in g if m)):
            return "other", set(), 0.0
        return "generic", set(), max(skills.values(), default=0.0)

    def _overstates_years(self, field, value):
        """True if a years-of-experience answer claims more than the profile does (see _years_scope).

        A number or text answer is compared by its largest number (so "5+" is 5 and "5-7" is 7). For a select or
        radio, the chosen option's lower bound is used ("3-5" is 3, "Less than 1" is 0)."""
        scope = self._years_scope(f'{field.get("context", "")} {field["question"]}')
        if scope is None:
            return False
        options = field.get("options")
        if options and (i := best_option(value, options)) is not None:
            claimed = _lower_bound(options[i])
        else:
            numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", str(value))]
            claimed = max(numbers, default=None)
        if claimed is None:
            self.log(f"years check skipped for {field['question'][:60]!r}: no number in {str(value)[:40]!r}")
            return False
        if claimed > scope[2]:
            self.log(f"years answer {claimed:g} is above the profile's {scope[2]:g} ({', '.join(sorted(scope[1])) or scope[0]}); not used")
            return True
        return False

    def _years_blocked(self, text):
        """A v2 profile with no skill facts has nothing to back a years answer: those questions go to manual
        review instead of being answered (or skipped) silently."""
        if not (self.v2 and YEARS_QUESTION.search(text)) or any(f.kind == "skill" for f in self.facts.values()):
            return False
        if not self._warned:
            self._warned = True
            self.log("Warning: the profile is version 2 but has no skills in facts; years-of-experience "
                     "questions go to manual review. Run --setup to add them.")
        return True

    def _grounded(self, field, value, cited):
        """With facts in the profile, a cited id must exist, and an answer that claims experience must be
        backed by what it cites. Only years-of-experience questions (number, text, textarea) must cite: the
        cited facts need a skill matching the one asked, and the answer cannot be above that skill's years.
        A plain 0 claims nothing. Salary, dates and other fields need no citation: _valid and fixed_answers
        cover them. Without facts (v1 profile) there is nothing to check."""
        if not self.facts:
            return True
        cited = cited or []
        unknown = check_citations(cited, self.facts)
        if unknown:
            self.log(f"answer for {field['question'][:60]!r} cites unknown facts {unknown}; not used")
            return False
        text = f'{field.get("context", "")} {field["question"]}'
        scope = self._years_scope(text)
        if field["type"] not in ("number", "text", "textarea") or scope is None:
            return True
        numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", str(value))]
        if numbers and max(numbers) == 0:
            return True
        label = field["question"][:60]
        kind, named, _ = scope
        if kind == "other":
            self.log(f"years answer for {label!r} asks about something that is not in the profile; "
                     "only 0 is allowed")
            return False
        skills = [self.facts[i] for i in cited if self.facts[i].kind == "skill"]
        if named:
            skills = [f for f in skills if f.text.lower() in named]
        skills = [f for f in skills if f.years is not None]
        if not skills:
            self.log(f"years answer for {label!r} cites no skill fact with years"
                     f"{' for ' + ', '.join(sorted(named)) if named else ''} (cited {cited}); not used")
            return False
        limit = max(f.years for f in skills)
        if not numbers or max(numbers) > limit:
            shown = f"{max(numbers):g}" if numbers else str(value)[:40]
            self.log(f"years answer {shown} is above the cited facts {cited} ({limit:g}); not used")
            return False
        return True

    def _manual_form(self, reason, fields):
        self.log(f"Form sent to manual review: {reason}")
        return {}, [f["question"] for f in fields if f["type"] != "file" and f.get("required")] or [
            "(the form looks like a prompt injection; fill it by hand)"]

    def decide(self, fields, offer):
        """Returns (answers {id: value}, unanswered required questions [text]).

        Order: fixed rules from the profile -> learned answers cache -> LLM for the rest. Sensitive fields (ids,
        banking, passwords, birth dates) only ever get a fixed rule. A form whose labels look like an
        injection goes to manual review as a whole, with no LLM call."""
        for f in fields:
            labels = [f["question"], f.get("context", ""), *map(str, f.get("options") or [])]
            reasons = looks_injected(chr(10).join(map(str, labels)))
            if reasons:
                return self._manual_form(f"field {f['id']} text matches an injection instruction "
                                         f"({', '.join(reasons)})", fields)
        answers, pending = {}, []
        missing = []
        for f in fields:
            if f["type"] == "file" or not _empty(f):
                continue
            text = f'{f.get("context", "")} {f["question"]}'
            rule = next((v for rx, v in self.rules if rx.search(text)), None)
            sensitive = is_sensitive(text)
            if rule is None and not sensitive and self._years_blocked(text):
                if f["required"]:
                    missing.append(f["question"])
                continue
            cached = None if sensitive else self.cache.get(normalize(text)) if len(normalize(text)) >= 15 else None
            if rule is not None and self._valid(f, rule):
                answers[f["id"]] = rule
            elif cached is not None and self._valid(f, cached) and not self._overstates_years(f, cached):
                answers[f["id"]] = cached
            elif sensitive:
                if f["required"]:
                    missing.append(f["question"])
            elif f["type"] == "checkbox" and not f["required"]:
                continue
            else:
                pending.append(f)
        if pending:
            extra = {} if self.forced_reply is None else {"raw": self.forced_reply}
            if self.facts:
                extra["facts"] = self.facts
            r = llm.answer_fields(pending, self.profile_text, offer, self.model, **extra)
            if r is None:
                return answers, missing + [f["question"] for f in pending if f["required"]] or [
                    "(the LLM did not answer)"]
            unknown = set(r.get("unknown") or [])
            llm_answers = r.get("answers") or {}
            cites = r.get("facts") or {}
            for f in pending:
                value = llm_answers.get(f["id"])
                if (f["id"] in unknown or not self._valid(f, value) or self._overstates_years(f, value)
                        or not self._grounded(f, value, cites.get(f["id"]))):
                    if f["required"]:
                        missing.append(f["question"])
                    continue
                answers[f["id"]] = value
                key = normalize(f'{f.get("context", "")} {f["question"]}')
                if f["type"] != "textarea" and len(key) >= 15:  # never cache "Yes", "No", etc.
                    self.cache[key] = value
            self._save_cache()
        return answers, missing

    @staticmethod
    def apply_answers(root, fields, answers):
        for f in fields:
            if f["id"] not in answers:
                continue
            value = answers[f["id"]]
            try:
                if f["type"] == "radio":
                    i = best_option(value, f["options"])
                    if i is not None:
                        _set_checked(root.locator(f'[data-ap="{f["id"]}_{i}"]'), True)
                elif f["type"] == "checkbox":
                    check = str(value).lower() in ("true", "1", "yes", "sí", "si")
                    _set_checked(root.locator(f'[data-ap="{f["id"]}"]'), check)
                elif f["type"] == "select":
                    i = best_option(value, f["options"])
                    if i is not None:
                        root.locator(f'[data-ap="{f["id"]}"]').select_option(label=f["options"][i], timeout=5000)
                else:
                    el = root.locator(f'[data-ap="{f["id"]}"]')
                    if f.get("autocomplete"):
                        el.fill("", timeout=5000)
                        el.press_sequentially(str(value), delay=60)
                        pause(1.2, 2.0)
                        el.press("ArrowDown")
                        el.press("Enter")
                    else:
                        el.fill(str(value), timeout=5000)
                pause(0.3, 0.8)
            except Exception:
                continue

    def fill(self, root, offer, cv_path=None):
        """Scans, decides and fills the form inside `root`. Returns the questions left unanswered."""
        fields = root.evaluate(JS_SCAN)
        if cv_path:
            for f in fields:
                if f["type"] == "file" and IS_CV.search(f["question"] or "resume"):
                    try:
                        root.locator(f'[data-ap="{f["id"]}"]').set_input_files(str(cv_path), timeout=10000)
                        pause(1.5, 3)
                    except Exception:
                        pass
                    break
        answers, missing = self.decide(fields, offer)
        self.apply_answers(root, fields, answers)
        return missing
