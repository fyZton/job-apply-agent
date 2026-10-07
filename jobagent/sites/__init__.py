"""Site plugins: every module in this package is one job board.

To add a board, drop a module here that defines the names in REQUIRED:
  NAME, LABEL, LOGIN_URL   identifiers and the login page
  ID_FROM_URL              regex whose group 1 is the offer id inside a URL
  search(page, cfg, seen)  yields Offer objects not yet seen
  details(page, offer)     fills offer text; returns "ok", "already_applied" or "no_button"
  apply(page, offer, cv_path, assistant, dry_run) -> (result, note)
"""
import importlib
import pkgutil

REQUIRED = ("NAME", "LABEL", "LOGIN_URL", "ID_FROM_URL", "search", "details", "apply")


def _load():
    sites = {}
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        missing = [a for a in REQUIRED if not hasattr(mod, a)]
        if missing:
            raise TypeError(f"site plugin '{info.name}' is missing {missing}")
        sites[mod.NAME] = mod
    return sites


SITES = _load()


def offer_key(url):
    """Stable id of an offer from its URL, e.g. 'linkedin:4474619760'."""
    url = (url or "").strip()
    for name, mod in SITES.items():
        m = mod.ID_FROM_URL.search(url)
        if m:
            return f"{name}:{m.group(1)}"
    return url
