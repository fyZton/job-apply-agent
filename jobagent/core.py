"""Shared pieces used by the site plugins."""
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(os.environ.get("JOBAGENT_DATA", "data")).resolve()


@dataclass
class Offer:
    site: str
    key: str
    url: str
    title: str = ""
    company: str = ""
    text: str = ""
    extra: dict = field(default_factory=dict)


class StopRequested(BaseException):
    """The STOP file exists. A BaseException on purpose: the `except Exception` blocks that make browser steps
    best-effort must not swallow the kill switch."""


_stop_check = None


def set_stop_check(func):
    """Registers a callable returning True when the run must stop (None removes it)."""
    global _stop_check
    _stop_check = func


def check_stop():
    """Raises StopRequested if the registered check says so. Call it before irreversible steps."""
    if _stop_check is not None and _stop_check():
        raise StopRequested()


class SessionExpired(Exception):
    """The platform asks to log in: run `python -m jobagent --login`."""


# Index of the <form> with the most visible fields (ignores search boxes); -1 if none.
JS_BEST_FORM = r"""() => {
  let best = -1, max = 0;
  document.querySelectorAll('form').forEach((f, i) => {
    const n = [...f.querySelectorAll('input, select, textarea')].filter(e =>
      !['hidden', 'submit', 'button', 'search'].includes((e.type || '').toLowerCase()) &&
      (e.offsetWidth || e.offsetHeight) &&
      !/buscar|search|^q$/i.test((e.name || '') + (e.placeholder || ''))).length;
    if (n > max) { max = n; best = i; }
  });
  return best;
}"""


def best_form(page):
    """Locator of the visible application form (or of a dialog), or None."""
    i = page.evaluate(JS_BEST_FORM)
    if i >= 0:
        return page.locator("form").nth(i)
    dialog = page.locator('[role="dialog"]')
    for j in range(dialog.count() - 1, -1, -1):
        if dialog.nth(j).is_visible():
            return dialog.nth(j)
    return None


def pause(low=1.0, high=2.5):
    """Sleeps a random time, checking the STOP file about once a second."""
    end = time.monotonic() + random.uniform(low, high)
    while True:
        check_stop()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(1.0, left))


def click_text(root, pattern, roles=("button", "link")):
    """Clicks the first visible button/link whose name matches the pattern. Returns True on success."""
    regex = re.compile(pattern, re.I)
    for role in roles:
        loc = root.get_by_role(role, name=regex)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible() and el.is_enabled():
                    el.scroll_into_view_if_needed(timeout=3000)
                    el.click(timeout=5000)
                    return True
            except Exception:
                continue
    # Fallback: <a> without href or <div role=button> have no accessible button/link role.
    loc = root.locator('a:visible, button:visible, [role="button"]:visible, input[type="submit"]:visible')
    loc = loc.filter(has_text=regex)
    for i in range(min(loc.count(), 5)):
        try:
            loc.nth(i).scroll_into_view_if_needed(timeout=3000)
            loc.nth(i).click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def visible_text(root, limit=8000):
    try:
        return re.sub(r"\s+", " ", root.inner_text(timeout=5000))[:limit]
    except Exception:
        return ""
