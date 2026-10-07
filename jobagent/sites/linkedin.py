"""LinkedIn: offers with Easy Apply."""
import json
import re
from urllib.parse import urlencode

from jobagent.core import DATA_DIR, Offer, SessionExpired, click_text, pause, visible_text

NAME = "linkedin"
LABEL = "LinkedIn"
LOGIN_URL = "https://www.linkedin.com/login"
ID_FROM_URL = re.compile(r"linkedin\.com/.*(?:jobs/view/|currentJobId=)(\d+)")
BASE = "https://www.linkedin.com"

EASY_BUTTON = re.compile(r"easy apply|solicitud sencilla", re.I)
SUBMIT = re.compile(r"^(submit application|enviar solicitud)$", re.I)
REVIEW = re.compile(r"^(review( your application)?|revisar( tu solicitud)?)$", re.I)
NEXT = re.compile(r"^(next|siguiente|continue( to next step)?|continuar( al siguiente paso)?)$", re.I)
SENT = re.compile(r"application (was )?sent|se envi[oó] tu solicitud|solicitud enviada|"
                  r"tu solicitud se ha enviado", re.I)
ALREADY_APPLIED = re.compile(r"\b(applied|solicitado|solicitud enviada|postulado)\b", re.I)
MODAL = '.jobs-easy-apply-modal, [data-test-modal-id="easy-apply-modal"], [role="dialog"], dialog[open]'
IS_APPLY_FORM = re.compile(r"aplicar a|apply to|solicitar|contact info|informaci[oó]n de contacto|"
                           r"resume|curr[ií]culum|enviar solicitud|submit application", re.I)

# Id and title of each card in the result list, to drop senior/lead offers without opening them.
JS_CARDS = r"""() => {
  const out = {};
  document.querySelectorAll('[data-occludable-job-id], [data-job-id]').forEach(e => {
    const id = e.getAttribute('data-occludable-job-id') || e.getAttribute('data-job-id');
    if (!id || !/^\d+$/.test(id)) return;
    const a = e.querySelector('a[href*="/jobs/view/"]');
    const t = a ? (a.getAttribute('aria-label') || a.innerText || '') : '';
    if (!out[id] || t) out[id] = t.split('\n')[0].trim();
  });
  return Object.entries(out).map(([id, title]) => ({id, title}));
}"""

# Scrolls the result list so LinkedIn loads all 25 cards.
JS_SCROLL = r"""async () => {
  const card = document.querySelector('[data-occludable-job-id], [data-job-id]');
  if (!card) return;
  let p = card.parentElement;
  while (p && p.scrollHeight <= p.clientHeight + 5) p = p.parentElement;
  p = p || document.scrollingElement;
  for (let i = 0; i < 12; i++) { p.scrollBy(0, 400); await new Promise(r => setTimeout(r, 350)); }
}"""

JS_WALK = r"""async (m) => {
  const boxes = [m, ...m.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 5);
  for (const c of boxes) {
    for (let y = 0; y <= c.scrollHeight; y += 300) { c.scrollTop = y; await new Promise(r => setTimeout(r, 120)); }
    c.scrollTop = 0;
  }
}"""

# File input whose surroundings talk about CV/resume (and not about a cover letter).
JS_CV_INPUT = r"""(modal) => {
  const ins = [...modal.querySelectorAll('input[type=file]')];
  for (const el of ins) {
    let p = el, t = '';
    for (let i = 0; i < 4 && p; i++, p = p.parentElement) t = (p.innerText || '') + ' ' + t;
    if (/resume|curr[ií]cul|\bcv\b/i.test(t) && !/cover letter|carta de presentaci/i.test(t)) {
      el.setAttribute('data-ap-cv', '1'); return true;
    }
  }
  return false;
}"""


def _logged_out(page):
    return any(s in page.url for s in ("/login", "/authwall", "/checkpoint", "/uas/"))


def search(page, cfg, seen):
    days = cfg.get("max_age_days", 7)
    found = set()
    for s in cfg["searches"]["linkedin"]:
        params = {"keywords": s["keywords"], "location": s.get("location", ""), "f_AL": "true",
                  "f_TPR": f"r{days * 86400}", "sortBy": "DD"}
        if s.get("remote"):
            params["f_WT"] = "2"
        if cfg.get("linkedin_experience_levels"):
            params["f_E"] = cfg["linkedin_experience_levels"]
        for page_no in range(cfg.get("pages_per_search", 2)):
            params["start"] = page_no * 25
            page.goto(f"{BASE}/jobs/search/?{urlencode(params)}", wait_until="domcontentloaded")
            pause(3, 5)
            if _logged_out(page):
                raise SessionExpired(LABEL)
            page.evaluate(JS_SCROLL)
            cards = page.evaluate(JS_CARDS)
            if not cards:
                break
            for c in cards:
                k = f"linkedin:{c['id']}"
                if k in found or seen(k):
                    continue
                found.add(k)
                yield Offer(NAME, k, f"{BASE}/jobs/view/{c['id']}/", title=c["title"])


def _first_visible(loc):
    for i in range(loc.count()):
        if loc.nth(i).is_visible():
            return loc.nth(i)
    return None


def _easy_button(page, wait=12):
    """The button shows up a few seconds after page load: keep looking for `wait` seconds."""
    for _ in range(wait * 2):
        for role in ("button", "link"):
            el = _first_visible(page.get_by_role(role, name=EASY_BUTTON))
            if el:
                return el
        page.wait_for_timeout(500)
    return None


def _text_of(page, selectors, limit):
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            t = visible_text(loc.first, limit)
            if t:
                return t
    return ""


def details(page, offer):
    page.goto(offer.url, wait_until="domcontentloaded")
    pause(3, 5)
    if _logged_out(page):
        raise SessionExpired(LABEL)
    button = _easy_button(page)
    click_text(page, r"^(see more|ver más|mostrar más|… más)$", roles=("button",))
    # The new layout has no <h1>; the tab title is "Title | Company | LinkedIn".
    # The title may contain "|", so split from the right.
    parts = [x.strip() for x in page.title().rsplit("|", 2)]
    offer.title = _text_of(page, ["h1"], 200) or (parts[0] if len(parts) == 3 else offer.title)
    offer.company = _text_of(page, [".job-details-jobs-unified-top-card__company-name",
                                    ".jobs-unified-top-card__company-name"], 120) or (
        parts[1] if len(parts) == 3 else "")
    offer.text = _text_of(page, ["#job-details", ".jobs-description__content", ".jobs-box__html-content",
                                 "main"], 8000)
    if button:
        return "ok"
    header = _text_of(page, [".job-details-jobs-unified-top-card__container--two-pane",
                             ".jobs-unified-top-card", "main"], 1500)
    return "already_applied" if ALREADY_APPLIED.search(header) else "no_button"


def _modal(page):
    """The application dialog (LinkedIn keeps other dialogs open, like the search one)."""
    loc = page.locator(MODAL)
    candidates = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]
    for el in reversed(candidates):
        if IS_APPLY_FORM.search(visible_text(el, 600)):
            return el
    return None


def _button(root, pattern):
    return _first_visible(root.get_by_role("button", name=pattern))


def _discard(page):
    modal = _modal(page)
    if modal and not click_text(modal, r"^(dismiss|descartar|cerrar|close)$", roles=("button",)):
        page.keyboard.press("Escape")
    pause(1, 2)
    click_text(page, r"^(discard|descartar)$", roles=("button",))
    pause(1, 2)


def _close_success(page):
    pause(1, 2)
    click_text(page, r"^(done|listo|dismiss|cerrar|close|not now|ahora no)$", roles=("button",))


def _pick_cv(modal, cv_path):
    """Selects the CV on the resume step. Returns True if this step was the resume one."""
    card = modal.get_by_text(cv_path.stem, exact=False)
    if card.count() and card.first.is_visible():
        card.first.click(timeout=5000)
        pause(1, 2)
        return True
    if modal.evaluate(JS_CV_INPUT):
        modal.locator("input[data-ap-cv]").first.set_input_files(str(cv_path), timeout=15000)
        pause(3, 5)
        return True
    return False


def _save_diagnostics(modal, offer):
    """Saves the scanned fields and the HTML around 'required' errors to help fix the bot."""
    from jobagent.forms import JS_SCAN
    folder = DATA_DIR / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        data = {"offer": offer.url, "fields": modal.evaluate(JS_SCAN),
                "error_html": modal.evaluate(r"""(m) => [...m.querySelectorAll('*')]
                  .filter(e => /obligatorio|required/i.test(e.innerText || '') && e.children.length === 0)
                  .slice(0, 3).map(e => { let b = e; for (let i = 0; i < 4 && b.parentElement; i++) b = b.parentElement;
                    return b.outerHTML.replace(/ class="[^"]*"/g, '').slice(0, 2500); })""")}
        safe_key = re.sub(r"[^\w.-]", "_", offer.key)  # the key comes from a URL: no path separators
        (folder / f"diagnostics_{safe_key}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def apply(page, offer, cv_path, assistant, dry_run):
    # A click before the page finishes loading does nothing: wait and retry.
    for _ in range(3):
        button = _easy_button(page, wait=5)
        if not button:
            return "manual", "No Easy Apply button"
        pause(1.5, 2.5)
        button.click(timeout=10000)
        for _ in range(16):
            if _modal(page):
                break
            page.wait_for_timeout(500)
        if _modal(page):
            break
    pause(1, 2)
    cv_done, stuck = False, 0
    for _ in range(15):
        modal = _modal(page)
        if not modal:
            return "error", "Easy Apply form did not open"
        text = visible_text(modal, 4000)
        if SENT.search(text):
            _close_success(page)
            return "sent", ""
        if not cv_done:
            cv_done = _pick_cv(modal, cv_path)
        follow = modal.locator("#follow-company-checkbox")
        if follow.count():
            try:
                follow.uncheck(force=True, timeout=3000)
            except Exception:
                pass
        # The new form is one long page that loads questions on scroll: walk it before filling.
        modal.evaluate(JS_WALK)
        missing = assistant.fill(modal, offer)
        if missing:
            _discard(page)
            return "manual", "Unanswered question: " + " | ".join(missing)[:250]
        submit = _button(modal, SUBMIT)
        if submit:
            if dry_run:
                _discard(page)
                return "dry_run", "Reached 'Submit application' (not sent)"
            submit.click(timeout=10000)
            pause(3, 5)
            modal = _modal(page)
            final = visible_text(modal, 3000) if modal else ""
            if not modal or SENT.search(final):
                _close_success(page)
                return "sent", ""
            return "error", "Clicked Submit but no confirmation appeared"
        nxt = _button(modal, REVIEW) or _button(modal, NEXT)
        if not nxt:
            _discard(page)
            return "error", "Next/Review button not found"
        nxt.click(timeout=10000)
        pause(1.5, 3)
        modal = _modal(page)
        if modal and visible_text(modal, 4000) == text:
            stuck += 1
            if stuck >= 2:
                errors = _text_of(modal, [".artdeco-inline-feedback--error", "[role=alert]"], 300)
                _save_diagnostics(modal, offer)
                _discard(page)
                return "manual", f"Form does not advance: {errors or 'invalid field'}"
        else:
            stuck = 0
    _discard(page)
    return "error", "Too many form steps"
