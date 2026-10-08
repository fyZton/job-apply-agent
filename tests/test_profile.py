import copy
from pathlib import Path

import pytest
import yaml

from jobagent import profile as prof

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent
V1 = FIXTURES / "profile_v1.yaml"


def base():
    return {"version": 2, "first_name": "Alex", "last_name": "Example", "email": "alex@example.com", "facts": []}


def errors_for(**changes):
    return prof.validate({**base(), **changes})


def test_v1_fixture_migrates_to_v2_facts():
    data = prof.load_profile(V1)
    assert data["version"] == 2
    facts = {f["id"]: f for f in data["facts"]}
    assert facts["skill.python"]["years"] == 3
    assert facts["skill.sql"]["kind"] == "skill"
    assert "skill.rest-apis-and-integrations" in facts
    assert facts["lang.english"]["kind"] == "language" and facts["lang.spanish"]["name"] == "Spanish"
    assert facts["edu.degree"]["kind"] == "education"
    assert "years_of_experience" not in data
    assert data["fixed_answers"] and data["screening_rules"]  # flat fields are kept


def test_migrate_is_idempotent_and_pure():
    raw = yaml.safe_load(V1.read_text(encoding="utf-8"))
    before = copy.deepcopy(raw)
    once = prof.migrate(raw)
    assert raw == before
    assert prof.migrate(once) == once


def test_migrate_logs_one_line_for_v1(caplog):
    with caplog.at_level("INFO"):
        prof.migrate(yaml.safe_load(V1.read_text(encoding="utf-8")))
    assert [r.message for r in caplog.records if "--setup" in r.message] == ["v1 profile, run --setup to upgrade"]


def test_migration_never_rewrites_the_file(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(V1.read_text(encoding="utf-8"), encoding="utf-8")
    prof.load_profile(path)
    assert path.read_text(encoding="utf-8") == V1.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [ROOT / "profile.example.yaml", ROOT / "jobagent" / "demo" / "profile.yaml"])
def test_shipped_profiles_are_valid_v2(path):
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == 2
    assert prof.validate(prof.load_profile(path)) == []


def test_valid_profile_has_no_errors():
    assert prof.validate(base()) == []


@pytest.mark.parametrize("changes, expected", [
    ({"email": None}, "email"),
    ({"email": "not-an-email"}, "email"),
    ({"first_name": ""}, "first_name"),
    ({"version": 3}, "newer jobagent"),
    ({"facts": [{"id": "skill.python", "kind": "skill", "name": "Python", "years": -1}]}, "facts[0].years"),
    ({"facts": [{"id": "skill.python", "kind": "skill", "name": "Python", "years": "three"}]},
     "facts[0].years must be a number >= 0 (got 'three')"),
    ({"facts": [{"id": "Skill Python", "kind": "skill", "name": "Python"}]}, "facts[0].id"),
    ({"facts": [{"id": "tool.python", "kind": "skill", "name": "Python"}]}, "facts[0].id"),
    ({"facts": [{"id": "skill.python", "kind": "hobby", "name": "Python"}]}, "facts[0].kind"),
    ({"facts": [{"id": "skill.python", "kind": "skill"}]}, "facts[0].name"),
    ({"facts": ["skill.python"]}, "facts[0]"),
    ({"facts": [{"id": "exp.a", "kind": "experience", "title": "Dev", "org": "Acme", "start": "Jan 2020"}]},
     "facts[0].start"),
    ({"facts": [{"id": "exp.a", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2020-01",
                 "end": "2021-13"}]}, "facts[0].end"),
])
def test_validation_messages(changes, expected):
    messages = errors_for(**changes)
    assert any(expected in m for m in messages), messages
    assert all(m.startswith("profile.yaml: ") for m in messages)


def test_duplicate_ids_including_bullets():
    facts = [
        {"id": "skill.python", "kind": "skill", "name": "Python"},
        {"id": "skill.python", "kind": "skill", "name": "Python again"},
        {"id": "exp.acme", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2023-01", "end": "present",
         "bullets": [{"id": "exp.acme", "text": "x"}, {"id": "exp.acme.b1", "text": "y"}]},
    ]
    messages = errors_for(facts=facts)
    assert sum("duplicate" in m for m in messages) == 2


def test_valid_experience_with_present_end():
    facts = [{"id": "exp.acme", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2023-01",
              "end": "present", "bullets": [{"id": "exp.acme.b1", "text": "Built things"}]}]
    assert errors_for(facts=facts) == []


def test_all_errors_are_reported_at_once(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("version: 2\nfirst_name: Alex\nemail: nope\nfacts:\n"
                    "  - {id: skill.python, kind: skill, name: Python, years: -2}\n"
                    "  - {id: BAD, kind: skill, name: X}\n", encoding="utf-8")
    with pytest.raises(prof.ProfileError) as exc:
        prof.load_profile(path)
    assert len(exc.value.messages) >= 4  # last_name, email, years, id
    assert str(exc.value).count("\n") == len(exc.value.messages) - 1


@pytest.mark.parametrize("text", ["a: [", "- just\n- a list\n"])
def test_load_profile_rejects_broken_yaml_and_non_mapping(tmp_path, text):
    path = tmp_path / "p.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(prof.ProfileError):
        prof.load_profile(path)


def test_dump_leaves_sensitive_keys_out():
    data = {**base(), "passport_number": "X123", "date_of_birth": "1990-01-01", "city": "Caracas"}
    text = prof.dump(data)
    assert "X123" not in text and "1990" not in text and "Caracas" in text
    assert yaml.safe_load(text)["first_name"] == "Alex"


def test_run_exits_2_and_prints_every_message_for_a_bad_profile(tmp_path, capsys):
    from jobagent.cli import Run

    (tmp_path / "profile.yaml").write_text("version: 3\nfirst_name: Alex\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        Run({"llm": {}}, True, root=tmp_path, data=tmp_path)
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "newer jobagent" in out and "last_name" in out and "email" in out


# --- slugs and ids --------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("C", "c"), ("C++", "c-plus-plus"), ("C#", "c-sharp"), ("node.js", "node-js"), ("Café Ñandú", "cafe-nandu"),
    ("  Spaced   Out ", "spaced-out"),
])
def test_slug(text, expected):
    assert prof.slug(text) == expected


def test_migrating_c_c_plus_plus_and_c_sharp_gives_distinct_ids_that_load():
    data = prof.migrate({"first_name": "Alex", "last_name": "Example", "email": "alex@example.com",
                         "years_of_experience": {"c": 2, "c++": 5, "c#": 3, "node.js": 1, "node_js": 2}})
    ids = [f["id"] for f in data["facts"]]
    assert len(set(ids)) == 5 and ids[:3] == ["skill.c", "skill.c-plus-plus", "skill.c-sharp"]
    assert ids[3:] == ["skill.node-js", "skill.node-js-2"]
    assert prof.validate(data) == []


def test_migration_does_not_reuse_ids_of_existing_facts():
    data = prof.migrate({"years_of_experience": {"python": 3, "go": 1},
                         "facts": [{"id": "skill.python", "kind": "skill", "name": "Python (old)"}]})
    ids = [f["id"] for f in data["facts"]]
    assert ids == ["skill.python", "skill.python-2", "skill.go"]


def test_names_without_ascii_letters_get_an_item_id():
    data = prof.migrate({"years_of_experience": {"漢字": 1, "日本語": 2}})
    assert [f["id"] for f in data["facts"]] == ["skill.item-1", "skill.item-2"]
    assert prof.validate({**base(), "facts": data["facts"]}) == []


# --- stricter validation --------------------------------------------------------------------------------

SKILL = {"id": "skill.python", "kind": "skill", "name": "Python", "years": 3}


@pytest.mark.parametrize("changes, expected", [
    ({"version": 0}, "version"),
    ({"version": -1}, "version"),
    ({"version": "2"}, "version"),
    ({"version": 2.5}, "version"),
    ({"version": True}, "version"),
    ({"email": "alex@example.com\n"}, "email"),
    ({"facts": [{**SKILL, "id": "skill.python\n"}]}, "facts[0].id"),
    ({"facts": [{"id": "exp.a", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2020-01\n"}]},
     "facts[0].start"),
    ({"years_of_experience": {"python": 3}}, "years_of_experience"),
    ({"facts": {}}, "facts must be a list"),
    ({"facts": ""}, "facts must be a list"),
    ({"facts": "skill.python"}, "facts must be a list"),
    ({"facts": [{**SKILL, "id": "cert.python"}]}, "prefix"),
    ({"facts": [{"id": "exp.a", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2021-05",
                 "end": "2020-01"}]}, "facts[0].end"),
    ({"fixed_answers": [{"pattern": "([unclosed", "value": "x"}]}, "([unclosed"),
    ({"fixed_answers": "nope"}, "fixed_answers"),
    ({"expected_salary_usd_monthly": "lots"}, "expected_salary_usd_monthly"),
    ({"expected_salary_usd_monthly": -5}, "expected_salary_usd_monthly"),
])
def test_stricter_validation(changes, expected):
    messages = errors_for(**changes)
    assert any(expected in m for m in messages), messages


def test_valid_extras_still_pass():
    facts = [{"id": "exp.a", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2020-01", "end": "2020-01",
              "bullets": [{"id": "exp.a.b1", "text": "x"}]}]
    assert errors_for(facts=facts, expected_salary_usd_monthly=1800,
                      fixed_answers=[{"pattern": "e-?mail", "value": "a@b.co"}]) == []
    assert errors_for(facts=None) == []


def test_v1_with_years_of_experience_still_loads_through_migration(tmp_path):
    assert prof.validate(prof.load_profile(V1)) == []
