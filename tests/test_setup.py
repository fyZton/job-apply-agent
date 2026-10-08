from pathlib import Path

import pytest
import yaml

from jobagent import profile as prof
from jobagent import setup

V1 = Path(__file__).parent / "fixtures" / "profile_v1.yaml"
BLANK_FLAT = [""] * 10  # phone, city, country, timezone, linkedin, github, work_mode, start, salary, summary


class Script:
    """Stands in for input(): hands out the scripted answers in order and records the prompts."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []
        self.out = []

    def ask(self, prompt):
        self.prompts.append(prompt)
        assert self.answers, f"script ran out at {prompt!r}"
        return self.answers.pop(0)

    def say(self, text=""):
        self.out.append(str(text))


FULL = ["Alex", "Example", "alex@example.com", *BLANK_FLAT,
        "Python", "3", "",                      # skills
        "AWS Cloud Practitioner", "2024", "",   # certs
        "Backend Developer", "Acme", "2023-01", "present", "Built REST integrations", "", "",  # experience, bullets
        "",                                     # education
        "English", "B1", "",                    # languages
        "y"]


def run(script, draft=None):
    return setup.interview(script.ask, script.say, draft)


def test_scripted_answers_produce_a_valid_profile():
    s = Script(*FULL)
    p = run(s)
    assert prof.validate(p) == [] and not s.answers
    ids = {f["id"]: f for f in p["facts"]}
    assert ids["skill.python"]["years"] == 3
    assert ids["cert.aws-cloud-practitioner"]["year"] == 2024
    assert ids["exp.acme-2023"]["bullets"] == [{"id": "exp.acme-2023.b1", "text": "Built REST integrations"}]
    assert ids["lang.english"]["level"] == "B1"
    assert p["version"] == 2 and p["email"] == "alex@example.com"
    assert "phone" not in p  # blank optional fields are left out


def test_final_yaml_is_printed_before_the_question():
    s = Script(*FULL)
    run(s)
    assert "first_name: Alex" in "\n".join(s.out)
    assert s.prompts[-1] == "Write profile.yaml? [y/N] "


def test_bad_email_is_asked_again():
    answers = list(FULL)
    answers[2:3] = ["nope", "alex@example.com"]
    s = Script(*answers)
    p = run(s)
    assert p["email"] == "alex@example.com"
    assert any("email" in line.lower() for line in s.out)
    assert sum(pr.startswith("Email") for pr in s.prompts) == 2


def test_negative_years_and_bad_dates_are_asked_again():
    answers = list(FULL)
    answers[14:15] = ["-1", "three", "3"]     # years after "Python"
    answers[answers.index("2023-01")] = "Jan 2023"
    answers.insert(answers.index("Jan 2023") + 1, "2023-01")
    s = Script(*answers)
    p = run(s)
    assert prof.validate(p) == []
    assert next(f for f in p["facts"] if f["id"] == "skill.python")["years"] == 3


def test_required_field_cannot_be_blank():
    answers = list(FULL)
    answers[0:1] = ["", "Alex"]
    p = run(Script(*answers))
    assert p["first_name"] == "Alex"


def test_no_at_the_end_returns_nothing():
    s = Script(*FULL[:-1], "n")
    assert run(s) is None
    s = Script(*FULL[:-1], "")
    assert run(s) is None


def test_blank_keeps_the_draft_value_and_ids():
    draft = prof.load_profile(V1)
    n_skills = sum(f["kind"] == "skill" for f in draft["facts"])
    n_other = {k: sum(f["kind"] == k for f in draft["facts"]) for k in ("cert", "experience", "education", "language")}
    # Enter on every question keeps the draft; the extra blank ends each "add more" loop.
    blanks = ([""] * 13                                    # flat fields
              + [""] * (n_skills * 2) + [""]                  # draft skills (name, years) + no new one
              + [""] * (n_other["cert"] * 2) + [""]
              + [""] * (n_other["experience"] * 5) + [""]
              + [""] * (n_other["education"] * 3) + [""]
              + [""] * (n_other["language"] * 2) + [""]
              + ["y"])
    s = Script(*blanks)
    p = run(s, draft)
    assert not s.answers
    assert p["facts"] == draft["facts"] and p["email"] == draft["email"]
    assert p["fixed_answers"] == draft["fixed_answers"]  # keys the interview doesn't ask about survive
    assert any("[Alex]" in pr for pr in s.prompts) and any("[3]" in pr for pr in s.prompts)


def test_draft_item_can_be_removed_and_new_ids_do_not_collide():
    draft = {"first_name": "Alex", "last_name": "Example", "email": "alex@example.com", "version": 2,
             "facts": [{"id": "skill.python", "kind": "skill", "name": "Python", "years": 3}]}
    s = Script("", "", "", *BLANK_FLAT, "-", "Python", "2", "Python", "1", "", "", "", "", "", "y")
    # "-" removes the draft skill; then two new skills with the same name get different ids
    p = run(s, draft)
    ids = [f["id"] for f in p["facts"]]
    assert ids == ["skill.python", "skill.python-2"] and prof.validate(p) == []


def test_write_profile_creates_the_file(tmp_path):
    path = tmp_path / "profile.yaml"
    p = run(Script(*FULL))
    assert setup.write_profile(p, path, confirm=lambda: pytest.fail("no need to confirm")) is True
    assert prof.load_profile(path)["email"] == "alex@example.com"


def test_existing_file_is_not_overwritten_without_confirmation(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("old: data\n", encoding="utf-8")
    assert setup.write_profile({"version": 2}, path, confirm=lambda: False) is False
    assert path.read_text(encoding="utf-8") == "old: data\n"
    assert not (tmp_path / "profile.yaml.bak").exists()


def test_confirmed_overwrite_keeps_a_backup(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("old: data\n", encoding="utf-8")
    assert setup.write_profile({"version": 2, "x": 1}, path, confirm=lambda: True) is True
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"version": 2, "x": 1}
    assert (tmp_path / "profile.yaml.bak").read_text(encoding="utf-8") == "old: data\n"


def test_setup_declined_writes_nothing(tmp_path):
    path = tmp_path / "profile.yaml"
    s = Script(*FULL[:-1], "n")
    assert setup.setup(path, None, s.ask, s.say) is False
    assert not path.exists() and "Nothing written" in "\n".join(s.out)


def test_setup_asks_before_overwriting(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("old: data\n", encoding="utf-8")
    s = Script(*FULL, "n")
    assert setup.setup(path, None, s.ask, s.say) is False
    assert path.read_text(encoding="utf-8") == "old: data\n"
    s = Script(*FULL, "y")
    assert setup.setup(path, None, s.ask, s.say) is True
    assert (tmp_path / "profile.yaml.bak").exists()


def test_load_draft_upgrades_v1_and_survives_junk(tmp_path):
    assert setup.load_draft(V1)["version"] == 2
    assert setup.load_draft(tmp_path / "missing.yaml") == {}
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [", encoding="utf-8")
    assert setup.load_draft(bad) == {}


def test_cli_setup_upgrades_an_existing_v1_profile(tmp_path, monkeypatch, capsys):
    from jobagent import cli

    (tmp_path / "profile.yaml").write_text(V1.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "y" if prompt.startswith(("Write", "profile.yaml")) else "")
    assert cli.setup_mode(tmp_path) is True
    new = prof.load_profile(tmp_path / "profile.yaml")
    assert new["version"] == 2 and any(f["id"] == "skill.python" for f in new["facts"])
    assert (tmp_path / "profile.yaml.bak").read_text(encoding="utf-8") == V1.read_text(encoding="utf-8")
