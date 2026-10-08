"""Reads any application form, decides the answers and fills them in."""
import difflib
import json
import re
from pathlib import Path

from jobagent import llm
from jobagent.claims import Claims, fold
from jobagent.core import pause
from jobagent.facts import check_citations, load_facts
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
IS_CV = re.compile(r"resume|curr[ií]cul|\bcv\b|hoja de vida", re.I)


def normalize(text):
    return re.sub(r"[^a-z0-9áéíóúñü ]", "", re.sub(r"\s+", " ", str(text).lower())).strip()[:200]


def best_option(value, options):
    """Index of the option that best matches `value`, or None. Order: exact (normalized), then a match on word
    boundaries (one starts with the other, then one contains the other as whole words), then fuzzy. A step with
    more than one hit is ambiguous and returns None, so "no" never lands inside "knowledge" or "Node.js" and
    "Yes" never picks one of "Yes, 5+ years" / "Yes, less than 2 years"."""
    v = normalize(value)
    if not v:
        return None
    norm = [normalize(o) for o in options]
    for i, o in enumerate(norm):
        if o == v:
            return i
    for hit in (lambda o: o.startswith(v + " ") or v.startswith(o + " "),
                lambda o: f" {v} " in f" {o} " or f" {o} " in f" {v} "):
        hits = [i for i, o in enumerate(norm) if o and hit(o)]
        if hits:
            return hits[0] if len(hits) == 1 else None
    # 0.8 tolerates typos ("venezula") but not different words: at 0.5 "maybe" matched "yes".
    # Accents are ignored here: "Si" finds "Sí".
    folded = [fold(o) for o in norm]
    close = difflib.get_close_matches(fold(v), folded, n=1, cutoff=0.8)
    return folded.index(close[0]) if close else None


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
        self.claims = Claims(self.facts, profile.get("years_of_experience"), profile)
        self.v2 = isinstance(profile.get("version"), int) and profile["version"] >= 2
        self._warned = False

    def _save_cache(self):
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def _resolve(field, value):
        """What apply_answers will fill: for a select or radio, the exact text of the option best_option picks
        (None if there is none); otherwise the value itself (None if empty). Every check runs on this."""
        if value in (None, ""):
            return None
        options = field.get("options")
        if not options:
            return value
        i = best_option(value, options)
        return None if i is None else options[i]

    def _claim_ok(self, field, question, value, fixed=False):
        """(ok, reason): the one honesty check, run on the resolved value of every field type and every source
        (rule, cache, model). See jobagent.claims."""
        try:
            return self.claims.check(field, question, value, fixed)
        except Exception as e:  # a checker bug must leave the field to the user, never crash the run
            self.log(f"honesty check failed on {question[:60]!r} ({type(e).__name__}); left for you to answer")
            return False, f"the check failed ({type(e).__name__})"

    def _years_blocked(self, text):
        """A v2 profile with no skill facts has nothing to back a years answer: those questions go to manual
        review instead of being answered (or skipped) silently."""
        if not (self.v2 and YEARS_QUESTION.search(text)) or any(f.kind == "skill" for f in self.facts.values()):
            return False
        if not self._warned:
            self._warned = True
            self.log("Warning: the profile has no skill facts; years-of-experience "
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
        if field["type"] not in ("number", "text", "textarea") or not self.claims.years_q(text):
            return True
        years = self.claims.stated_years(text, value)
        if years == 0:
            return True
        named = self.claims.named(text)
        skills = [self.facts[i] for i in cited if self.facts[i].kind == "skill"]
        if named:
            skills = [f for f in skills if self.claims.key(f.text) in named]
        skills = [f for f in skills if f.years is not None]
        label = field["question"][:60]
        if not skills:
            self.log(f"years answer for {label!r} cites no skill fact with years"
                     f"{' for ' + ', '.join(sorted(named)) if named else ''} (cited {cited}); not used")
            return False
        limit = max(f.years for f in skills)
        if years is None or years > limit:
            shown = f"{years:g}" if years is not None else str(value)[:40]
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
            rule, cached = self._resolve(f, rule), self._resolve(f, cached)
            if rule is not None:
                ok, reason = self._claim_ok(f, text, rule, fixed=True)
                if ok:
                    answers[f["id"]] = rule
                else:
                    self.log(f"fixed answer {str(rule)[:30]!r} to {f['question'][:60]!r}: {reason}; not used")
                    if f["required"]:
                        missing.append(f["question"])
            elif cached is not None and self._claim_ok(f, text, cached)[0]:
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
                value = self._resolve(f, llm_answers.get(f["id"]))
                ok, reason = (False, "") if value is None else self._claim_ok(
                    f, f'{f.get("context", "")} {f["question"]}', value)
                if reason:
                    self.log(f"{str(value)[:30]!r} to {f['question'][:60]!r}: {reason}; not used")
                if (f["id"] in unknown or not ok or not self._grounded(f, value, cites.get(f["id"]))):
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
                    check = str(value).lower() in ("true", "1", "checked", "yes", "sí", "si")
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
