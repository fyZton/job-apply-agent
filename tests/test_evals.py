import json
import sys

import pytest

from jobagent import cli, evals, llm

CASES = evals.CASES_DIR


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("JOBAGENT_LLM", raising=False)
    llm.configure({})


def test_case_files_have_enough_unique_cases():
    cases = evals.load_cases(CASES)
    by_suite = {}
    for c in cases:
        by_suite.setdefault(c["suite"], []).append(c["id"])
    assert set(by_suite) == {"fit", "honesty", "injection"}
    assert all(len(ids) >= 6 for ids in by_suite.values())
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))


def test_injection_suite_covers_spanish_zero_width_and_bypass():
    cases = [c for c in evals.load_cases(CASES) if c["suite"] == "injection"]
    blob = json.dumps(cases)
    assert "ignora" in blob.lower() and "\\u200b" in blob
    assert sum(1 for c in cases if c.get("bypass_detector")) >= 3


def test_all_offline_cases_pass():
    results = evals.run(CASES)
    failed = [r for r in results if not r["passed"]]
    assert failed == []
    assert {r["suite"] for r in results} == {"fit", "honesty", "injection"}


def test_run_leaves_environment_untouched():
    evals.run(CASES)
    assert "JOBAGENT_LLM" not in __import__("os").environ


def test_write_report_creates_json_and_markdown(tmp_path):
    results = evals.run(CASES)
    json_path, md_path = evals.write_report(results, tmp_path / "evals")
    assert json_path.suffix == ".json" and md_path.suffix == ".md"
    assert json_path.stem == md_path.stem and json_path.stem.startswith("report-")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["suites"]["fit"]["rate"] == 1.0
    assert len(data["results"]) == len(results)
    md = md_path.read_text(encoding="utf-8")
    assert "| fit |" in md and "| honesty |" in md and "| injection |" in md


def test_report_lists_failures(tmp_path):
    results = [{"id": "x-1", "suite": "fit", "passed": False, "detail": "fit 10 outside 1-3"},
               {"id": "x-2", "suite": "fit", "passed": True, "detail": ""}]
    _, md_path = evals.write_report(results, tmp_path)
    md = md_path.read_text(encoding="utf-8")
    assert "50%" in md and "x-1" in md and "fit 10 outside 1-3" in md


def always_ten(offer, cvs):
    return {"fit": 10, "cv": cvs[0]["file"], "company": offer.company, "title": offer.title, "reason": "great"}


def test_evals_can_fail(monkeypatch):
    monkeypatch.setattr(llm, "_fake_score", always_ten)
    results = evals.run(CASES)
    fit = [r for r in results if r["suite"] == "fit"]
    assert any(not r["passed"] for r in fit) and any(r["passed"] for r in fit)
    bypass = [r for r in results if r["suite"] == "injection" and not r["passed"]]
    assert bypass  # a model that obeys the injected text is caught by the bypass cases


def test_live_mode_uses_configured_backend_and_skips_forced_replies(monkeypatch):
    monkeypatch.setattr(llm, "_complete", lambda prompt, model: '{"fit": 8, "cv": "x"}')
    results = evals.run(CASES, live=True)
    honesty_cases = [c for c in evals.load_cases(CASES) if c["suite"] == "honesty"]
    forced = [c for c in honesty_cases if "llm_reply" in c]
    assert forced
    assert len([r for r in results if r["suite"] == "honesty"]) == len(honesty_cases) - len(forced)


def test_cli_eval_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["jobagent", "--eval"])
    with pytest.raises(SystemExit) as ok:
        cli.main()
    assert ok.value.code == 0
    assert list((tmp_path / "evals").glob("report-*.json"))
    monkeypatch.setattr(llm, "_fake_score", always_ten)
    with pytest.raises(SystemExit) as bad:
        cli.main()
    assert bad.value.code == 1
