import pytest

from jobagent import llm
from jobagent.core import Offer
from jobagent.forms import FormAssistant, best_option, normalize

OFFER = Offer("demo", "demo:1", "https://example.com/jobs/1", title="Backend Developer", company="Acme")
PROFILE = {"fixed_answers": [{"pattern": "e-?mail", "value": "alex@example.com"}]}


@pytest.mark.parametrize("value, options, expected", [
    ("Yes", ["Yes", "No"], 0),
    ("yes", ["Sí", "No", "YES"], 2),
    ("Basic", ["Basic (A2)", "Fluent"], 0),
    ("Venezula", ["Venezuela", "Colombia"], 0),
    ("Rust", ["Python", "Java"], None),
    ("Maybe", ["Yes", "No"], None),
    ("", ["Yes", "No"], None),
])
def test_best_option(value, options, expected):
    assert best_option(value, options) == expected


def field(id_, question, type_="text", required=True, **extra):
    return {"id": id_, "type": type_, "question": question, "required": required, "value": "", **extra}


@pytest.fixture
def assistant(tmp_path):
    return FormAssistant(PROFILE, "name: Alex", tmp_path, "fake-model", print)


def fake_llm(monkeypatch, reply):
    calls = []

    def answer_fields(fields, *args):
        calls.append([f["id"] for f in fields])
        return reply

    monkeypatch.setattr(llm, "answer_fields", answer_fields)
    return calls


def test_fixed_rule_beats_cache_and_llm(assistant, monkeypatch):
    calls = fake_llm(monkeypatch, {"answers": {"a": "llm@example.com"}})
    assistant.cache[normalize(" Email address")] = "cached@example.com"
    answers, missing = assistant.decide([field("a", "Email address")], OFFER)
    assert answers == {"a": "alex@example.com"}
    assert missing == [] and calls == []


def test_cached_answer_skips_llm(assistant, monkeypatch):
    calls = fake_llm(monkeypatch, None)
    assistant.cache[normalize(" How many years with Python?")] = "3"
    answers, _ = assistant.decide([field("a", "How many years with Python?", "number")], OFFER)
    assert answers == {"a": "3"} and calls == []


def test_llm_answers_rest_and_caches_only_reusable_ones(assistant, monkeypatch):
    fake_llm(monkeypatch, {"answers": {"a": "3", "b": "I like backend work.", "c": "No"}, "unknown": []})
    fields = [field("a", "How many years with Python?", "number"),
              field("b", "Why do you want this job?", "textarea"),
              field("c", "Visa?")]
    answers, missing = assistant.decide(fields, OFFER)
    assert answers == {"a": "3", "b": "I like backend work.", "c": "No"} and missing == []
    assert normalize(" How many years with Python?") in assistant.cache
    assert normalize(" Why do you want this job?") not in assistant.cache  # open text is offer-specific
    assert normalize(" Visa?") not in assistant.cache  # too short to be a safe key


def test_unknown_required_field_is_reported_missing(assistant, monkeypatch):
    fake_llm(monkeypatch, {"answers": {}, "unknown": ["a", "b"]})
    fields = [field("a", "National ID number"), field("b", "Referral code", required=False)]
    answers, missing = assistant.decide(fields, OFFER)
    assert answers == {} and missing == ["National ID number"]


def test_llm_down_reports_required_fields(assistant, monkeypatch):
    fake_llm(monkeypatch, None)
    _, missing = assistant.decide([field("a", "Expected salary")], OFFER)
    assert missing == ["Expected salary"]


def test_malformed_llm_reply_does_not_crash(assistant, monkeypatch):
    fake_llm(monkeypatch, {"answers": None, "unknown": None})
    _, missing = assistant.decide([field("a", "Expected salary")], OFFER)
    assert missing == ["Expected salary"]


def test_llm_answer_outside_options_is_rejected(assistant, monkeypatch):
    fake_llm(monkeypatch, {"answers": {"a": "Maybe"}, "unknown": []})
    radio = field("a", "Do you need visa sponsorship?", "radio", options=["Yes", "No"])
    answers, missing = assistant.decide([radio], OFFER)
    assert answers == {}
    assert missing == ["Do you need visa sponsorship?"]
    assert normalize(" Do you need visa sponsorship?") not in assistant.cache
