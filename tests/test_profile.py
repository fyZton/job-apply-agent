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
         "bullets": [{"id": "skill.python", "text": "x"}, {"id": "exp.acme.b1", "text": "y"}]},
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
