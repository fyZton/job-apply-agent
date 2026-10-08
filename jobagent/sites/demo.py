"""Demo board served from jobagent/demo/board by `python -m jobagent --demo`.

It is also the smallest complete plugin, so it doubles as the template for adding a real board.
"""
import re

from jobagent.core import Offer, check_stop, visible_text

NAME = "demo"
LABEL = "Demo board"
LOGIN_URL = ""  # the demo board has no accounts
ID_FROM_URL = re.compile(r"127\.0\.0\.1:\d+/offers/([\w-]+)\.html")

SUBMIT = re.compile(r"^submit application$", re.I)
NEXT = re.compile(r"^next$", re.I)


def search(page, cfg, seen):
    page.goto(f"{cfg['demo_url']}/index.html")
    # Read the whole list first: the caller navigates away between offers, which would detach live locators.
    items = page.locator("a.offer").evaluate_all("els => els.map(a => [a.dataset.id, a.innerText])")
    for offer_id, title in items:
        key = f"{NAME}:{offer_id}"
        if not seen(key):
            yield Offer(NAME, key, f"{cfg['demo_url']}/offers/{offer_id}.html", title=title)


def details(page, offer):
    page.goto(offer.url)
    offer.company = visible_text(page.locator(".company"), 200)
    offer.text = visible_text(page.locator("main"))
    if "already applied" in offer.text:
        return "already_applied"
    return "ok" if page.locator("a.apply").count() else "no_button"


def apply(page, offer, cv_path, assistant, dry_run):
    page.locator("a.apply").click()
    for _ in range(4):
        form = page.locator("form")
        missing = assistant.fill(form, offer, cv_path)
        if missing:
            return "manual", "Unanswered question: " + " | ".join(missing)
        submit = form.get_by_role("button", name=SUBMIT)
        if submit.count():
            if dry_run:
                return "dry_run", "Reached 'Submit application' (not sent)"
            check_stop()
            submit.click()
            page.wait_for_load_state()
            if "Application sent" in visible_text(page.locator("main")):
                return "sent", ""
            return "error", "No confirmation after submitting"
        form.get_by_role("button", name=NEXT).click()
        page.wait_for_load_state()
    return "error", "Too many form steps"
