import os
import sys

import pytest

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


@pytest.mark.parametrize("key, result", [
    ("demo:backend-python", "sent"),
    ("demo:integrations-dev", "sent"),
    ("demo:needs-id", "manual"),
    ("demo:senior-backend", "title_excluded"),
    ("demo:onsite-madrid", "low_fit"),
    ("demo:already-applied", "already_applied"),
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
