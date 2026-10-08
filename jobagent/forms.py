"""Reads any application form, decides the answers and fills them in."""
import difflib
import json
import re
from pathlib import Path

from jobagent import llm
from jobagent.core import pause

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
    def __init__(self, profile, profile_text, data_dir, model, log):
        self.profile = profile
        self.profile_text = profile_text
        self.model = model
        self.log = log
        self.cache_path = Path(data_dir) / "learned_answers.json"
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}
        self.rules = [(re.compile(r["pattern"], re.I), r["value"]) for r in profile.get("fixed_answers", [])]

    def _save_cache(self):
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _valid(self, field, value):
        if field.get("options"):
            return best_option(value, field["options"]) is not None
        return value not in (None, "")

    def _overstates_years(self, field, value):
        """True if a years-of-experience answer is a number above anything the profile claims."""
        years = [v for v in (self.profile.get("years_of_experience") or {}).values() if isinstance(v, int | float)]
        if not years or not YEARS_QUESTION.search(f'{field.get("context", "")} {field["question"]}'):
            return False
        try:
            return float(str(value).strip()) > max(years)
        except ValueError:
            return False

    def decide(self, fields, offer):
        """Returns (answers {id: value}, unanswered required questions [text]).

        Order: fixed rules from the profile -> learned answers cache -> LLM for the rest."""
        answers, pending = {}, []
        for f in fields:
            if f["type"] == "file" or not _empty(f):
                continue
            text = f'{f.get("context", "")} {f["question"]}'
            rule = next((v for rx, v in self.rules if rx.search(text)), None)
            cached = self.cache.get(normalize(text)) if len(normalize(text)) >= 15 else None
            if rule is not None and self._valid(f, rule):
                answers[f["id"]] = rule
            elif cached is not None and self._valid(f, cached):
                answers[f["id"]] = cached
            elif f["type"] == "checkbox" and not f["required"]:
                continue
            else:
                pending.append(f)
        missing = []
        if pending:
            r = llm.answer_fields(pending, self.profile_text, offer, self.model)
            if r is None:
                return answers, [f["question"] for f in pending if f["required"]] or ["(the LLM did not answer)"]
            unknown = set(r.get("unknown") or [])
            llm_answers = r.get("answers") or {}
            for f in pending:
                value = llm_answers.get(f["id"])
                if f["id"] in unknown or not self._valid(f, value) or self._overstates_years(f, value):
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
