"""Computrabajo Venezuela: applies with the CV stored in the Computrabajo profile."""
import re
import unicodedata

from jobagent.core import Offer, SessionExpired, best_form, click_text, pause, visible_text

NAME = "computrabajo"
LABEL = "Computrabajo"
LOGIN_URL = "https://candidato.ve.computrabajo.com/acceso/"
ID_FROM_URL = re.compile(r"computrabajo\.com.*-([0-9A-F]{32})")
BASE = "https://ve.computrabajo.com"

BUTTON = r"^\s*postular(me)?\s*$"
SUCCESS = re.compile(r"(te )?has postulado|postulaci[oó]n (enviada|realizada|exitosa|completada)|"
                     r"ya est[aá]s postulad|inscripci[oó]n (realizada|exitosa)|te postulaste", re.I)
ALREADY_APPLIED = re.compile(r"ya (te )?(has )?postula|ya est[aá]s postulad|te postulaste", re.I)

JS_LIST = r"""() => [...document.querySelectorAll('article.box_offer')].map(a => {
  const l = a.querySelector('a.js-o-link');
  return {id: a.getAttribute('data-id'), href: l ? l.getAttribute('href') : '', title: l ? l.innerText.trim() : ''};
}).filter(x => x.id && x.href)"""


def _slug(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _logged_out(page):
    return any(s in page.url.lower() for s in ("/acceso", "/login"))


def search(page, cfg, seen):
    found = set()
    for term in cfg["searches"]["computrabajo"]:
        for p in range(1, cfg.get("pages_per_search", 2) + 1):
            url = f"{BASE}/trabajo-de-{_slug(term)}?pubdate={cfg.get('max_age_days', 7)}"
            if p > 1:
                url += f"&p={p}"
            page.goto(url, wait_until="domcontentloaded")
            pause(2, 4)
            items = page.evaluate(JS_LIST)
            if not items:
                break
            for it in items:
                k = f"computrabajo:{it['id']}"
                if k in found or seen(k):
                    continue
                found.add(k)
                yield Offer(NAME, k, BASE + it["href"].split("#")[0], title=it["title"])


def details(page, offer):
    page.goto(offer.url, wait_until="domcontentloaded")
    pause(2, 4)
    h1 = page.locator("h1")
    if h1.count():
        offer.title = visible_text(h1.first, 200) or offer.title
    root = page.locator("main") if page.locator("main").count() else page.locator("body")
    offer.text = visible_text(root.first, 8000)
    if page.locator("a.postulated:visible").count() or ALREADY_APPLIED.search(offer.text[:3000]):
        return "already_applied"
    return "ok" if _button(page) else "no_button"


def _button(page):
    # The button is an <a> without href (no "link" role), so it is found by its attribute.
    loc = page.locator("[data-href-offer-apply]:visible")
    if not loc.count():
        loc = page.locator("a:visible, button:visible").filter(has_text=re.compile(BUTTON, re.I))
    return loc.first if loc.count() else None


def apply(page, offer, cv_path, assistant, dry_run):
    if dry_run:
        # On Computrabajo the button may apply in a single click, so dry runs never press it.
        return "dry_run", "Good fit; in dry-run mode 'Postularme' is not clicked"
    button = _button(page)
    if not button:
        return "manual", "Apply button not found"
    button.scroll_into_view_if_needed(timeout=5000)
    button.click(timeout=10000)
    pause(3, 5)
    if _logged_out(page):
        raise SessionExpired(LABEL)
    for _ in range(4):
        if SUCCESS.search(visible_text(page.locator("body"), 6000)):
            return "sent", ""
        form = best_form(page)
        if form is None:
            break
        missing = assistant.fill(form, offer, cv_path)
        if missing:
            return "manual", "Unanswered question: " + " | ".join(missing)[:250]
        if not click_text(form, r"enviar|postular|continuar|finalizar", roles=("button",)):
            break
        pause(3, 5)
    if SUCCESS.search(visible_text(page.locator("body"), 6000)):
        return "sent", ""
    return "error", "No confirmation after applying"
