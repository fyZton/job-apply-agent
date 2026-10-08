"""Job-apply agent: finds offers, scores them with an LLM and applies on its own.

  python -m jobagent              apply for real
  python -m jobagent --dry-run    do everything except submitting
  python -m jobagent --login      open every board to log in (first time only)
  python -m jobagent --only linkedin
  python -m jobagent --demo       run the whole flow on a local fake board, no accounts needed
  python -m jobagent --eval       run the offline evals (add --live to score the configured model)
"""
import argparse
import datetime as dt
import os
import re
import sys
import tempfile
import threading
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from jobagent import evals, llm
from jobagent.core import DATA_DIR, SessionExpired, pause
from jobagent.forms import FormAssistant
from jobagent.safety import looks_injected, stop_requested
from jobagent.sites import SITES
from jobagent.tracker import Tracker

ROOT = Path.cwd()
DEMO = Path(__file__).parent / "demo"
BROWSER_PROFILE = Path(os.environ.get("JOBAGENT_BROWSER", Path.home() / ".jobagent" / "browser"))


class LLMUnavailable(Exception):
    """Claude is not answering (e.g. the plan's usage limit was reached)."""


class StopRequested(Exception):
    """The file data/STOP exists."""


def log(msg):
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    folder = DATA_DIR / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{dt.date.today()}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def screenshot(page, site):
    folder = DATA_DIR / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{site}_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        return path.name
    except Exception:
        return ""


def open_browser(p):
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    options = dict(user_data_dir=str(BROWSER_PROFILE), headless=False, no_viewport=True,
                   args=["--start-maximized"])
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **options)
    except Exception:
        return p.chromium.launch_persistent_context(**options)


def word_pattern(words, whole_word):
    if not words:
        return None
    if whole_word:
        return re.compile("|".join(rf"(?<!\w){re.escape(w)}(?!\w)" for w in words), re.I)
    return re.compile("|".join(re.escape(w) for w in words), re.I)


def load_yaml(name, root=ROOT):
    path = root / name
    if not path.exists():
        sys.exit(f"{name} not found. Copy {path.stem}.example.yaml to {name} and edit it.")
    return path.read_text(encoding="utf-8")


def login_mode(cfg):
    with sync_playwright() as p:
        ctx = open_browser(p)
        sites = [s for s, on in cfg["sites"].items() if on]
        for i, s in enumerate(sites):
            page = ctx.pages[0] if i == 0 and ctx.pages else ctx.new_page()
            page.goto(SITES[s].LOGIN_URL)
        print("\nLog in on every tab and make sure each profile has your CV uploaded.")
        input("When done, press Enter here to save the sessions... ")
        ctx.close()
    print("Done. Sessions are saved.")


class Run:
    def __init__(self, cfg, dry_run, root=ROOT, data=DATA_DIR):
        self.cfg = cfg
        self.dry_run = dry_run
        llm.configure(cfg.get("llm", {}))
        self.profile_text = load_yaml("profile.yaml", root)
        profile = yaml.safe_load(self.profile_text)
        self.rules = profile.get("screening_rules", [])
        self.cv_dir = (root / cfg["cv_dir"]).resolve()
        self.cvs = cfg["cvs"]
        missing = [c["file"] for c in self.cvs if not (self.cv_dir / c["file"]).exists()]
        if missing:
            sys.exit(f"CVs not found in {self.cv_dir}: {missing}")
        self.tracker = Tracker((root / cfg["excel"]).resolve(), data, log)
        self.assistant = FormAssistant(profile, self.profile_text, data, cfg["llm"]["form_model"], log)
        self.exclude = word_pattern(cfg.get("exclude_if_title_has"), whole_word=True)
        self.keywords = word_pattern(cfg.get("title_keywords"), whole_word=False)
        self.summary = Counter()
        self.llm_failures = 0

    def process(self, page, site):
        mod = SITES[site]
        limit = self.cfg["daily_limit"][site]
        for offer in mod.search(page, self.cfg, self.tracker.seen):
            if stop_requested(DATA_DIR):
                raise StopRequested()
            sent = self.summary[site, "dry_run"] if self.dry_run else self.tracker.sent_today(site)
            if sent >= limit:
                log(f"{mod.LABEL}: daily limit reached ({limit}).")
                return
            self.one_offer(page, site, mod, offer)

    def flag_suspicious(self, site, mod, offer, reasons):
        """Skips a posting that looks like a prompt injection: no LLM call, left for the user to read."""
        log(f"{mod.LABEL}: {offer.title} | {offer.company} -> suspicious posting ({reasons}); skipped")
        self.summary[site, "suspicious"] += 1
        self.tracker.mark(offer.key, "suspicious", title=offer.title, reason=reasons)
        if not self.dry_run:
            self.tracker.add_row({"Company": offer.company, "Title": offer.title, "Source": mod.LABEL,
                                  "Link": offer.url, "Status": "To apply", "Next step": "Read it before applying",
                                  "Notes": f"Suspicious posting: {reasons}"})

    def one_offer(self, page, site, mod, offer):
        k = offer.key
        if self.exclude and offer.title and self.exclude.search(offer.title):
            self.tracker.mark(k, "title_excluded", title=offer.title)
            return
        try:
            status = mod.details(page, offer)
        except SessionExpired:
            raise
        except Exception as e:
            log(f"{mod.LABEL}: could not open {offer.url} ({type(e).__name__})")
            return
        if status != "ok":
            self.tracker.mark(k, status)
            return
        if self.exclude and self.exclude.search(offer.title):
            self.tracker.mark(k, "title_excluded", title=offer.title)
            return
        if self.keywords and not self.keywords.search(offer.title):
            self.tracker.mark(k, "no_keywords", title=offer.title)
            return

        reasons = looks_injected("\n".join([offer.title, offer.company, offer.text]))
        if reasons:
            self.flag_suspicious(site, mod, offer, ", ".join(reasons))
            return

        ev = llm.score_offer(offer, self.profile_text, self.cvs, self.rules, self.cfg["llm"]["score_model"])
        if ev is None:
            self.llm_failures += 1
            if self.llm_failures >= 3:
                raise LLMUnavailable()
            return
        self.llm_failures = 0
        fit = ev["fit"]
        offer.company = offer.company or ev.get("company", "")
        offer.title = offer.title or ev.get("title", "")
        reason = ev.get("reason", "")
        log(f"{mod.LABEL}: {offer.title} | {offer.company} -> fit {fit}. {reason}")
        if fit < self.cfg["min_fit"]:
            self.tracker.mark(k, "low_fit", fit=fit, title=offer.title, reason=reason)
            self.summary[site, "discarded"] += 1
            return

        names = [c["file"] for c in self.cvs]
        cv_name = ev.get("cv") if ev.get("cv") in names else names[0]
        cv_path = self.cv_dir / cv_name
        try:
            result, note = mod.apply(page, offer, cv_path, self.assistant, self.dry_run)
        except SessionExpired:
            raise
        except Exception as e:
            result, note = "error", f"{type(e).__name__}: {str(e)[:150]}"
        if result in ("manual", "error"):
            img = screenshot(page, site)
            note = f"{note} (screenshot: {img})" if img else note
        log(f"   -> {result.upper()} {note}")
        self.summary[site, result] += 1

        if result == "already_applied":
            self.tracker.mark(k, "already_applied")
            return
        if self.dry_run:
            return  # dry runs never write to the Excel file
        row = {"Company": offer.company, "Title": offer.title, "Source": mod.LABEL, "Link": offer.url,
               "Fit (1-10)": fit, "CV used": cv_name}
        if result == "sent":
            row.update({"Lane": "Easy apply", "Status": "Sent", "Next step": "Wait for reply",
                        "Notes": f"Auto. {reason}"})
            self.tracker.add_sent(site)
        else:
            external = "external" in note
            row.update({"Lane": "Company site" if external else "Easy apply", "Status": "To apply",
                        "Next step": "Apply by hand", "Notes": f"Bot: {note}. {reason}"})
        self.tracker.add_row(row)
        self.tracker.mark(k, result, fit=fit)
        pause(*self.cfg["pause_between_applications"])


def run_all(run, sites, ctx):
    log(f"=== Start {'(DRY RUN: nothing is sent)' if run.dry_run else ''} | boards: {', '.join(sites)} ===")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    for site in sites:
        label = SITES[site].LABEL
        log(f"--- {label} ---")
        try:
            run.process(page, site)
        except SessionExpired:
            log(f"{label}: not logged in. Run `python -m jobagent --login` once and retry.")
        except LLMUnavailable:
            log("Claude is not answering (usage limit?). Stopping; retry later.")
            break
        except StopRequested:
            log("STOP file found; delete it to run again.")
            break
        except llm.BudgetExceeded as e:
            log(f"{e}. Stopping.")
            break
        except Exception as e:
            log(f"{label}: unexpected error, moving to the next board: {type(e).__name__}: {e}")
            screenshot(page, site)


def report(run, sites):
    s = run.summary
    log("=== Summary ===")
    for site in sites:
        log(f"{SITES[site].LABEL}: sent {s[site, 'sent']} | dry-run OK {s[site, 'dry_run']} | "
            f"to do by hand {s[site, 'manual'] + s[site, 'error']} | discarded by fit {s[site, 'discarded']} | "
            f"suspicious {s[site, 'suspicious']}")
    log(llm.usage_summary())
    if run.tracker.pending:
        log("Some rows are waiting for the Excel file to be closed; they will be saved on the next run.")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def demo(headless=False, dry_run=False):
    """Runs the full flow against the fake board in jobagent/demo. Data goes to a fresh temp folder."""
    previous_llm = os.environ.get("JOBAGENT_LLM")
    os.environ.setdefault("JOBAGENT_LLM", "fake")  # JOBAGENT_LLM=claude runs the demo with the real model
    cfg = yaml.safe_load(load_yaml("config.yaml", DEMO))
    data = Path(tempfile.mkdtemp(prefix="jobagent-demo-"))
    cfg["excel"] = str(data / "applications.xlsx")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(DEMO / "board")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg["demo_url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        run = Run(cfg, dry_run, root=DEMO, data=data)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=0 if headless else 400)
            run_all(run, ["demo"], browser.new_context())
    except KeyboardInterrupt:
        log("Stopped by the user.")
    finally:
        server.shutdown()
        server.server_close()
        if previous_llm is None:
            os.environ.pop("JOBAGENT_LLM", None)
        else:
            os.environ["JOBAGENT_LLM"] = previous_llm
    report(run, ["demo"])
    log(f"Demo Excel and history are in {data}; logs are in {DATA_DIR / 'logs'}")
    return run


def eval_mode(live):
    """Runs the eval suites and writes a report. Returns the process exit code."""
    if live:
        if os.environ.get("JOBAGENT_LLM") == "fake":
            sys.exit("--live needs a real backend: unset JOBAGENT_LLM or set it to claude or api.")
        llm.configure(yaml.safe_load(load_yaml("config.yaml")).get("llm", {}))
    else:
        llm.configure({})
    results = evals.run(evals.CASES_DIR, live=live)
    json_path, md_path = evals.write_report(results, DATA_DIR / "evals", "live" if live else "offline")
    for suite, s in evals.summarize(results).items():
        print(f"{suite}: {s['passed']}/{s['total']} ({s['rate']:.0%})")
    for r in results:
        if not r["passed"]:
            print(f"FAILED {r['suite']}/{r['id']}: {r['detail']}")
    print(llm.usage_summary())
    print(f"Report: {md_path} and {json_path.name}")
    return 0 if live or all(r["passed"] for r in results) else 1


def main():
    ap = argparse.ArgumentParser(prog="jobagent")
    ap.add_argument("--dry-run", action="store_true", help="do everything except submitting")
    ap.add_argument("--login", action="store_true", help="open the boards to log in")
    ap.add_argument("--only", choices=[s for s in SITES if s != "demo"], help="use a single board")
    ap.add_argument("--demo", action="store_true", help="run on a local fake board, no accounts needed")
    ap.add_argument("--eval", action="store_true", help="run the eval suites (offline, fake backend)")
    ap.add_argument("--live", action="store_true", help="with --eval: score the configured backend instead")
    ap.add_argument("--headless", action="store_true", help="with --demo: don't show the browser")
    args = ap.parse_args()
    if args.demo:
        demo(args.headless, args.dry_run)
        return
    if args.eval:
        sys.exit(eval_mode(args.live))
    if os.environ.get("JOBAGENT_LLM") == "fake":
        sys.exit("JOBAGENT_LLM=fake is only allowed with --demo or --eval: "
                 "it would submit canned answers to real boards.")
    cfg = yaml.safe_load(load_yaml("config.yaml"))
    if args.login:
        login_mode(cfg)
        return
    dry_run = args.dry_run or cfg.get("dry_run", False)
    run = Run(cfg, dry_run)
    sites = [args.only] if args.only else [s for s, on in cfg["sites"].items() if on]
    try:
        with sync_playwright() as p:
            ctx = open_browser(p)
            run_all(run, sites, ctx)
            ctx.close()
    except KeyboardInterrupt:
        log("Stopped by the user.")
    report(run, sites)
