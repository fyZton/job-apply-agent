"""Opt-in smoke test against the real Anthropic API: JOBAGENT_LIVE_API=1 pytest tests/test_live_api.py

It makes one tiny call through llm._call_api to check the SDK parameter names (output_config, betas, fallbacks).
It costs a fraction of a cent and never runs in CI."""
import os

import pytest

from jobagent import llm

pytestmark = pytest.mark.skipif(os.environ.get("JOBAGENT_LIVE_API") != "1", reason="set JOBAGENT_LIVE_API=1 to run")


@pytest.mark.parametrize("alias", ["haiku", "sonnet"])
def test_one_real_call_returns_text_and_is_counted(alias):
    llm.configure({"backend": "api", "max_cost_usd_per_run": 0.05})
    text = llm._call_api("Reply with the single word OK.", alias)
    assert text and llm.USAGE["calls"] == 1 and llm.USAGE["output_tokens"] > 0
