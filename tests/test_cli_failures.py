from collections import Counter
from types import SimpleNamespace

import pytest

from jobagent import cli, llm
from jobagent.core import Offer


def test_transient_error_while_filling_counts_toward_llm_failures(monkeypatch):
    run = cli.Run.__new__(cli.Run)
    run.exclude = run.keywords = None
    run.llm_failures, run.summary, run.dry_run = 0, Counter(), True
    run.cfg = {"llm": {"score_model": "m"}, "min_fit": 1}
    run.cvs, run.cv_dir, run.rules, run.profile_text = [{"file": "a.pdf"}], cli.Path("."), [], ""
    run.assistant = None
    run.tracker = SimpleNamespace(mark=lambda *a, **k: None)
    monkeypatch.setattr(llm, "score_offer", lambda *a, **k: {"fit": 9, "cv": "a.pdf"})
    monkeypatch.setattr(cli, "screenshot", lambda *a: None)

    def apply(*a):
        raise llm.LLMTransient("rate limit")

    mod = SimpleNamespace(LABEL="x", details=lambda p, o: "ok", apply=apply)
    offer = Offer("x", "x:1", "https://example.com/1", title="Dev", company="Co", text="python")
    for _ in range(2):
        run.one_offer(None, "x", mod, offer)
    assert run.summary["x", "error"] == 2 and run.llm_failures == 2
    with pytest.raises(cli.LLMUnavailable):
        run.one_offer(None, "x", mod, offer)
