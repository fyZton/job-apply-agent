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
    ("Years of experience with Kubernetes?", None),
    ("Years with Pythonic style", None),  # word boundaries
    ("Años de experiencia con Docker", 1),
    ("", None),
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


def skills(**years):
    return fx.load_facts({"facts": [{"id": f"skill.{i}", "kind": "skill", "name": n, "years": y}
                                    for i, (n, y) in enumerate(years.items())]})


def test_c_plus_plus_is_not_c_sharp_nor_c():
    f = fx.load_facts({"facts": [{"id": "skill.c", "kind": "skill", "name": "C", "years": 2},
                                 {"id": "skill.cs", "kind": "skill", "name": "C#", "years": 5},
                                 {"id": "skill.cpp", "kind": "skill", "name": "C++", "years": 4},
                                 {"id": "skill.cprog", "kind": "skill", "name": "C programming", "years": 1}]})
    assert [m.text for m in fx.match_skills(f, "Years of C++ programming?")] == ["C++"]
    assert [m.text for m in fx.match_skills(f, "Years of C# development?")] == ["C#"]
    assert [m.text for m in fx.match_skills(f, "Years of C programming?")] == ["C", "C programming"]
    assert fx.match_skills(f, "Are you a C-level executive?") == []
    assert fx.years_for(f, "Years of experience with C?") == 2


@pytest.mark.parametrize("name, question", [
    ("JavaScript", "Years of JS?"), ("JS", "Years of JavaScript?"),
    ("TypeScript", "Years of ts?"), ("TS", "Years of TypeScript?"),
    ("PostgreSQL", "Years of Postgres?"), ("Postgres", "Years of PostgreSQL?"),
    ("Kubernetes", "Years of k8s?"), ("k8s", "Years of Kubernetes?"),
])
def test_aliases_work_both_ways(name, question):
    assert fx.years_for(skills(**{name: 4}), question) == 4


def test_years_for_is_none_without_a_match_and_zero_without_years():
    assert fx.years_for(skills(Python=3), "Years of Rust?") is None
    f = fx.load_facts({"facts": [{"id": "skill.rust", "kind": "skill", "name": "Rust"}]})
    assert fx.years_for(f, "Years of Rust?") == 0


def test_duplicate_skill_names_keep_the_max_years_and_log(caplog):
    data = {"facts": [{"id": "skill.python", "kind": "skill", "name": "Python", "years": 2},
                      {"id": "skill.python-2", "kind": "skill", "name": "python", "years": 5}]}
    with caplog.at_level("WARNING"):
        f = fx.load_facts(data)
    assert "duplicate" in caplog.text.lower()
    assert [m.years for m in fx.match_skills(f, "Years of Python?")] == [5]
    assert fx.years_for(f, "Years of Python?") == 5
