import os
import sys

import openpyxl
import pytest

from jobagent import cli, llm
from jobagent.cli import demo, main


@pytest.fixture(scope="module")
def monkeypatch_module():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


@pytest.fixture(scope="module")
def results(monkeypatch_module):
    monkeypatch_module.setenv("JOBAGENT_LLM", "fake")
    run = demo(headless=True)
    return {k: v["result"] for k, v in run.tracker.history["seen"].items()}


def sheet_rows(run):
    wb = openpyxl.load_workbook(run.tracker.excel, read_only=True)
    header, *rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    return [dict(zip(header, r, strict=False)) for r in rows]


def test_suspicious_offer_gets_a_review_row_and_no_llm_call(monkeypatch):
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    titles = []
    real = llm.score_offer
    monkeypatch.setattr(llm, "score_offer", lambda offer, *a: titles.append(offer.title) or real(offer, *a))
    run = demo(headless=True)
    assert "Python Integrations Developer" not in titles
    row = next(r for r in sheet_rows(run) if "prompt-injection" in r["Link"])
    assert row["Status"] == "To apply"
    assert row["Notes"].startswith("Suspicious posting: ") and "ignore-previous-instructions" in row["Notes"]
    assert run.summary["demo", "suspicious"] == 1


@pytest.mark.parametrize("key, result", [
    ("demo:backend-python", "sent"),
    ("demo:integrations-dev", "sent"),
    ("demo:needs-id", "manual"),
    ("demo:senior-backend", "title_excluded"),
    ("demo:onsite-madrid", "low_fit"),
    ("demo:already-applied", "already_applied"),
    ("demo:prompt-injection", "suspicious"),
])
def test_each_demo_offer_takes_its_path(results, key, result):
    assert results.get(key) == result


def test_dry_run_never_submits_and_leaves_env_untouched(monkeypatch):
    monkeypatch.delenv("JOBAGENT_LLM", raising=False)
    run = demo(headless=True, dry_run=True)
    results = [v["result"] for v in run.tracker.history["seen"].values()]
    assert "sent" not in results
    assert run.summary["demo", "dry_run"] == 2
    assert "JOBAGENT_LLM" not in os.environ


def test_real_run_refuses_fake_llm(monkeypatch):
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    monkeypatch.setattr(sys, "argv", ["jobagent", "--dry-run"])
    with pytest.raises(SystemExit, match="only allowed with --demo"):
        main()


def test_stop_file_stops_the_run_before_any_offer(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    (tmp_path / "STOP").write_text("")
    run = demo(headless=True)
    assert run.tracker.history["seen"] == {}
    assert "STOP file found" in (tmp_path / "logs").glob("*.log").__next__().read_text(encoding="utf-8")
    assert (tmp_path / "STOP").exists()  # never deleted automatically


def test_run_all_stops_when_budget_is_exceeded(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    seen = []

    class FakeRun:
        dry_run = True

        def process(self, page, site):
            seen.append(site)
            raise llm.BudgetExceeded("LLM cost $2.00 is over the $1.00 limit for this run")

    ctx = type("Ctx", (), {"pages": [object()]})()
    cli.run_all(FakeRun(), ["demo", "demo"], ctx)
    assert seen == ["demo"]  # the second board is never started
    assert "over the $1.00 limit" in next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")
