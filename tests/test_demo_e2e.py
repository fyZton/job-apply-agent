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


@pytest.fixture
def run_dir(monkeypatch, tmp_path):
    """Makes demo() use tmp_path as its data folder, so STOP files go in the run's own folder."""
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    monkeypatch.setattr(cli.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
    return tmp_path


def test_stop_file_in_the_run_folder_stops_the_run_before_any_offer(run_dir, capsys):
    (run_dir / "STOP").write_text("")
    run = demo(headless=True)
    assert run.tracker.history["seen"] == {}
    assert "STOP file found" in capsys.readouterr().out
    assert (run_dir / "STOP").exists()  # never deleted automatically


def test_stop_file_during_the_form_blocks_the_final_submit(run_dir, monkeypatch, capsys):
    real_fill = cli.FormAssistant.fill

    def fill_then_stop(self, *a, **kw):
        missing = real_fill(self, *a, **kw)
        (run_dir / "STOP").write_text("")
        return missing

    monkeypatch.setattr(cli.FormAssistant, "fill", fill_then_stop)
    run = demo(headless=True)
    assert "sent" not in [v["result"] for v in run.tracker.history["seen"].values()]
    assert "STOP file found" in capsys.readouterr().out


def test_run_all_stops_when_budget_is_exceeded(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    seen = []

    class FakeRun:
        dry_run = True
        data = tmp_path

        def process(self, page, site):
            seen.append(site)
            raise llm.BudgetExceeded("LLM cost $2.00 is over the $1.00 limit for this run")

    ctx = type("Ctx", (), {"pages": [object()]})()
    cli.run_all(FakeRun(), ["demo", "demo"], ctx)
    assert seen == ["demo"]  # the second board is never started
    assert "over the $1.00 limit" in next((tmp_path / "logs").glob("*.log")).read_text(encoding="utf-8")


def log_text(folder):
    return next((folder / "logs").glob("*.log")).read_text(encoding="utf-8")


def test_transient_llm_errors_count_as_failures_and_stop_after_three(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(llm, "score_offer", lambda *a: (_ for _ in ()).throw(llm.LLMTransient("429")))
    run = demo(headless=True)
    assert "Claude is not answering" in log_text(tmp_path)
    assert run.llm_failures == 3


def test_config_error_aborts_the_whole_run(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(llm, "score_offer", lambda *a: (_ for _ in ()).throw(llm.ConfigError("bad key")))
    run = demo(headless=True)
    assert "bad key" in log_text(tmp_path) and "Stopping" in log_text(tmp_path)
    assert run.tracker.history["seen"].get("demo:backend-python") is None


@pytest.mark.parametrize("exc", [llm.BudgetExceeded("over"), llm.ConfigError("bad key")])
def test_errors_from_the_form_step_are_not_swallowed(monkeypatch, tmp_path, exc):
    monkeypatch.setenv("JOBAGENT_LLM", "fake")
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(llm, "answer_fields", lambda *a: (_ for _ in ()).throw(exc))
    run = demo(headless=True)
    assert "Stopping" in log_text(tmp_path)
    assert run.summary["demo", "error"] == 0
