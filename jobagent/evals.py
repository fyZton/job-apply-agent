"""Eval suites: fit scoring, honest form answers and prompt-injection resistance.

Offline (default) the fake backend stands in for the model, so the cases test the pipeline around it: the
injection detector, output validation, length caps and the years-of-experience check. Live mode sends the same
cases to the configured backend and measures the model itself.

The case files live in `evals/` at the repo root, so --eval works from a source checkout, not from a wheel.
"""
import datetime as dt
import functools
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

from jobagent import llm
from jobagent.core import Offer
from jobagent.forms import FormAssistant
from jobagent.safety import looks_injected

CASES_DIR = Path(__file__).resolve().parent.parent / "evals"
PROFILE_PATH = Path(__file__).parent / "demo" / "profile.yaml"
CVS = [{"file": "Alex_Example_CV_EN.pdf", "use_for": "English. Any offer written in English."},
       {"file": "Alex_Example_CV_ES.pdf", "use_for": "Spanish. Any offer written in Spanish."}]
SCORE_MODEL, FORM_MODEL = "haiku", "sonnet"


class EvalsError(Exception):
    """The eval cases can't be run (folder missing, no cases)."""


@functools.cache
def load_profile():
    """(text, parsed) of the demo candidate profile the cases are written for."""
    text = PROFILE_PATH.read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def load_cases(cases_dir):
    cases_dir = Path(cases_dir)
    if not cases_dir.is_dir():
        raise EvalsError(f"Eval cases folder not found: {cases_dir}. --eval runs from a source checkout "
                         "(the evals/ folder is not part of the installed package).")
    cases = []
    for path in sorted(cases_dir.glob("*.yaml")):
        cases += [{**c, "suite": path.stem} for c in yaml.safe_load(path.read_text(encoding="utf-8")) or []]
    if not cases:
        raise EvalsError(f"No eval cases found in {cases_dir}.")
    return cases


def _score(text, title="Backend Developer"):
    profile_text, profile = load_profile()
    offer = Offer("eval", "eval:1", "https://example.com/eval", title=title, company="Example Co", text=text)
    return llm.score_offer(offer, profile_text, CVS, profile["screening_rules"], SCORE_MODEL)


def _check_fit(ev, expect):
    if ev is None:
        return "scorer returned no valid score"
    if not expect["fit_min"] <= ev["fit"] <= expect["fit_max"]:
        return f"fit {ev['fit']} outside {expect['fit_min']}-{expect['fit_max']}"
    if "cv" in expect and ev["cv"] != expect["cv"]:
        return f"picked {ev['cv']}, expected {expect['cv']}"
    return ""


def _fit(case):
    o = case["offer"]
    return _check_fit(_score(o["text"], o["title"]), case["expect"])


def _honesty(case):
    """Runs one form field through FormAssistant.decide. `llm_reply` forces the raw model reply."""
    profile_text, profile = load_profile()
    field = {"required": True, "value": "", **case["field"]}
    offer = Offer("eval", "eval:1", "https://example.com/eval", title="Backend Developer", company="Example Co")
    with tempfile.TemporaryDirectory() as tmp:
        assistant = FormAssistant(profile, profile_text, tmp, FORM_MODEL, lambda *_: None,
                                  forced_reply=case.get("llm_reply"))
        answers, _ = assistant.decide([field], offer)
    answer, expect = answers.get(field["id"]), case["expect"]
    if expect.get("unanswered"):
        return "" if answer is None else f"answered {str(answer)[:60]!r}, expected no answer"
    if answer is None and not expect.get("allow_unanswered"):
        return "no answer (the model call failed or the answer was rejected)"
    if "answer" in expect:
        return "" if str(answer) == expect["answer"] else f"answered {answer!r}, expected {expect['answer']!r}"
    if "contains" in expect:
        return "" if expect["contains"] in str(answer) else f"answer lacks {expect['contains']!r}"
    if "max_number" in expect:
        if answer is None:
            return ""  # allow_unanswered: leaving the field for the user is as honest as answering 0
        try:
            return "" if float(answer) <= expect["max_number"] else f"answered {answer}"
        except ValueError:
            return f"non-numeric answer {answer!r}"
    if "max_length" in expect:
        return "" if len(str(answer)) <= expect["max_length"] else "answer too long"
    return "case has no known expectation"


def _injection(case):
    if case.get("bypass_detector"):
        return _check_fit(_score(case["text"]), case["expect"])
    found = looks_injected(case["text"])
    if case["expect"]["detected"] != bool(found):
        return "detector flagged nothing" if case["expect"]["detected"] else f"false positive: {found}"
    return ""


SUITES = {"fit": _fit, "honesty": _honesty, "injection": _injection}


def run_case(case):
    """Returns {id, suite, passed, detail}. An exception inside a case counts as a failure, except for
    BudgetExceeded and ConfigError, which end the whole run."""
    try:
        detail = SUITES[case["suite"]](case)
    except (llm.BudgetExceeded, llm.ConfigError):
        raise
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
    return {"id": case["id"], "suite": case["suite"], "passed": not detail, "detail": detail}


@contextmanager
def _env(name, value):
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _run_cases(cases):
    """Runs the cases in order. If the budget runs out, the case that hit it is recorded as failed and the
    rest are not run, so the report still shows what was measured."""
    results = []
    for c in cases:
        try:
            results.append(run_case(c))
        except llm.BudgetExceeded as e:
            results.append({"id": c["id"], "suite": c["suite"], "passed": False,
                            "detail": f"run stopped, budget exceeded: {e}"})
            break
    return results


def run(cases_dir, live=False):
    """Runs every case. Offline forces the fake backend; live uses the configured one and skips the cases
    that force a model reply (they only make sense for the fake)."""
    cases = load_cases(cases_dir)
    if live:
        return _run_cases([c for c in cases if "llm_reply" not in c])
    with _env("JOBAGENT_LLM", "fake"):
        return _run_cases(cases)


def skipped_count(cases_dir, live=False):
    """How many cases `run` leaves out: in live mode, the ones with a forced model reply."""
    return sum("llm_reply" in c for c in load_cases(cases_dir)) if live else 0


def summarize(results):
    suites = {}
    for r in results:
        s = suites.setdefault(r["suite"], {"passed": 0, "total": 0})
        s["total"] += 1
        s["passed"] += r["passed"]
    for s in suites.values():
        s["rate"] = round(s["passed"] / s["total"], 3)
    return suites


def overall_rate(results):
    return sum(r["passed"] for r in results) / len(results) if results else 0.0


def write_report(results, out_dir, mode="offline", skipped=0):
    """Writes report-YYYYMMDD-HHMMSS.json and .md into out_dir. Returns (json_path, md_path)."""
    now = dt.datetime.now()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suites = summarize(results)
    stem = f"report-{now:%Y%m%d-%H%M%S}"
    json_path, md_path = out / f"{stem}.json", out / f"{stem}.md"
    json_path.write_text(json.dumps({"generated": now.isoformat(timespec="seconds"), "mode": mode,
                                     "skipped": skipped, "suites": suites, "results": results},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Eval report {now:%Y-%m-%d %H:%M:%S} ({mode})", "", "| Suite | Passed | Total | Pass rate |",
             "|---|---|---|---|"]
    lines += [f"| {name} | {s['passed']} | {s['total']} | {s['rate']:.0%} |" for name, s in suites.items()]
    if skipped:
        lines += ["", f"Skipped: {skipped} cases that force a model reply (offline only)."]
    failures = [r for r in results if not r["passed"]]
    lines += ["", "## Failures", ""] + ([f"- {r['suite']}/{r['id']}: {r['detail']}" for r in failures] or ["None."])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
