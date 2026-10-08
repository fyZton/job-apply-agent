from pathlib import Path

import pytest

from jobagent import facts as fx
from jobagent import profile as prof

V1 = Path(__file__).parent / "fixtures" / "profile_v1.yaml"


@pytest.fixture
def facts():
    return fx.load_facts(prof.load_profile(V1))


def test_ids_are_stable_after_reload(facts):
    again = fx.load_facts(prof.load_profile(V1))
    assert list(facts) == list(again) and facts == again
    assert "skill.python" in facts and facts["skill.python"].years == 3


def test_fact_is_frozen(facts):
    with pytest.raises(AttributeError):
        facts["skill.python"].years = 10


def test_prompt_has_one_line_per_fact(facts):
    lines = fx.facts_prompt(facts).splitlines()
    assert len(lines) == len(facts)
    assert "[skill.python] Python, 3 years" in lines
    assert "[skill.docker] Docker, 1 year" in lines


def test_bullets_and_other_kinds_are_facts():
    data = {"facts": [
        {"id": "cert.aws-ccp", "kind": "cert", "name": "AWS Cloud Practitioner", "year": 2024},
        {"id": "exp.acme-2023", "kind": "experience", "title": "Backend Developer", "org": "Acme",
         "start": "2023-01", "end": "present",
         "bullets": [{"id": "exp.acme-2023.b1", "text": "Built REST integrations"}]},
        {"id": "lang.english", "kind": "language", "name": "English", "level": "B1"},
    ]}
    f = fx.load_facts(data)
    assert set(f) == {"cert.aws-ccp", "exp.acme-2023", "exp.acme-2023.b1", "lang.english"}
    assert f["exp.acme-2023.b1"].text == "Built REST integrations"
    assert "Backend Developer" in f["exp.acme-2023"].text and "Acme" in f["exp.acme-2023"].text
    assert f["lang.english"].text == "English, B1"


def test_load_facts_without_facts_is_empty():
    assert fx.load_facts({}) == {} and fx.load_facts({"facts": None}) == {}


@pytest.mark.parametrize("question, expected", [
    ("How many years of Python?", 3),
    ("How many years of experience do you have with python development?", 3),
    ("Years of experience with SQL", 2),
    ("Years of experience with Kubernetes?", 0),
    ("Years with Pythonic style", 0),  # word boundaries
    ("Años de experiencia con Docker", 1),
    ("", 0),
])
def test_years_for(facts, question, expected):
    assert fx.years_for(facts, question) == expected


def test_years_for_uses_aliases():
    f = fx.load_facts({"facts": [{"id": "skill.javascript", "kind": "skill", "name": "JavaScript", "years": 4}]})
    assert fx.years_for(f, "Years of JS?") == 4


def test_years_for_symbols():
    f = fx.load_facts({"facts": [{"id": "skill.c", "kind": "skill", "name": "C", "years": 2},
                                 {"id": "skill.c-sharp", "kind": "skill", "name": "C#", "years": 5}]})
    assert fx.years_for(f, "Years of C#?") == 5


def test_check_citations(facts):
    assert fx.check_citations(["skill.python", "skill.nope", "cert.fake"], facts) == ["skill.nope", "cert.fake"]
    assert fx.check_citations([], facts) == []
