import os
import re
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
        "English", "B1", ""]                    # languages


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


def test_final_yaml_is_printed_before_the_question(tmp_path):
    s = Script(*FULL, "n")
    setup.setup(tmp_path / "profile.yaml", None, s.ask, s.say)
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


@pytest.mark.parametrize("answer", ["n", "", "no", "maybe"])
def test_anything_but_yes_at_the_end_writes_nothing(tmp_path, answer):
    s = Script(*FULL, answer)
    assert setup.setup(tmp_path / "profile.yaml", None, s.ask, s.say) is False
    assert not (tmp_path / "profile.yaml").exists()


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
              + [""] * (n_other["language"] * 2) + [""])
    s = Script(*blanks)
    p = run(s, draft)
    assert not s.answers
    assert p["facts"] == draft["facts"] and p["email"] == draft["email"]
    assert p["fixed_answers"] == draft["fixed_answers"]  # keys the interview doesn't ask about survive
    assert any("[Alex]" in pr for pr in s.prompts) and any("[3]" in pr for pr in s.prompts)


def test_draft_item_can_be_removed_and_new_ids_do_not_collide():
    draft = {"first_name": "Alex", "last_name": "Example", "email": "alex@example.com", "version": 2,
             "facts": [{"id": "skill.python", "kind": "skill", "name": "Python", "years": 3}]}
    s = Script("", "", "", *BLANK_FLAT, "-", "Python", "2", "Python", "1", "", "", "", "", "")
    # "-" removes the draft skill; then two new skills with the same name get different ids
    p = run(s, draft)
    ids = [f["id"] for f in p["facts"]]
    assert ids == ["skill.python", "skill.python-2"] and prof.validate(p) == []


def test_write_profile_creates_the_file(tmp_path):
    path = tmp_path / "profile.yaml"
    p = run(Script(*FULL))
    assert setup.write_profile(p, path, print) is True
    assert prof.load_profile(path)["email"] == "alex@example.com"
    assert [f.name for f in tmp_path.iterdir()] == ["profile.yaml"]  # no temp file left


def test_overwrite_keeps_a_timestamped_backup_and_never_replaces_an_older_one(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("old: data\n", encoding="utf-8")
    assert setup.write_profile({"version": 2, "x": 1}, path, print) is True
    assert setup.write_profile({"version": 2, "x": 2}, path, print) is True
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"version": 2, "x": 2}
    backups = sorted(tmp_path.glob("profile.yaml.bak-*"))
    assert len(backups) == 2
    assert all(re.fullmatch(r"profile\.yaml\.bak-\d{8}-\d{6}(-\d+)?", b.name) for b in backups)
    assert {b.read_text(encoding="utf-8") for b in backups} == {"old: data\n", "version: 2\nx: 1\n"}


def test_a_failed_write_keeps_the_old_file_and_saves_a_profile_yaml_new(tmp_path, monkeypatch):
    path = tmp_path / "profile.yaml"
    path.write_text("old: data\n", encoding="utf-8")

    def locked(src, dst):
        raise PermissionError("file is locked by OneDrive")

    monkeypatch.setattr(os, "replace", locked)
    said = []
    assert setup.write_profile({"version": 2, "x": 1}, path, said.append) is False
    assert path.read_text(encoding="utf-8") == "old: data\n"
    assert yaml.safe_load((tmp_path / "profile.yaml.new").read_text(encoding="utf-8")) == {"version": 2, "x": 1}
    assert any("profile.yaml.new" in m for m in said)
    assert not list(tmp_path.glob("*.tmp"))


def test_setup_asks_once(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("old: data\n", encoding="utf-8")
    s = Script(*FULL, "n")
    assert setup.setup(path, None, s.ask, s.say) is False
    assert path.read_text(encoding="utf-8") == "old: data\n"
    assert sum(pr.endswith("[y/N] ") for pr in s.prompts) == 1
    s = Script(*FULL, "y")
    assert setup.setup(path, None, s.ask, s.say) is True
    assert sum(pr.endswith("[y/N] ") for pr in s.prompts) == 1
    assert prof.load_profile(path)["email"] == "alex@example.com" and list(tmp_path.glob("profile.yaml.bak-*"))
    assert "overwrite" in s.prompts[-1].lower()


def test_setup_declined_writes_nothing(tmp_path):
    path = tmp_path / "profile.yaml"
    s = Script(*FULL, "n")
    assert setup.setup(path, None, s.ask, s.say) is False
    assert not path.exists() and "Nothing written" in "\n".join(s.out)


def test_load_draft_upgrades_v1_and_a_missing_file_is_a_blank_start(tmp_path):
    assert setup.load_draft(V1)["version"] == 2
    assert setup.load_draft(tmp_path / "missing.yaml") == {}


@pytest.mark.parametrize("text", ["a: [", "- just\n- a list\n"])
def test_unreadable_draft_says_why_and_aborts_unless_told_otherwise(tmp_path, text):
    bad = tmp_path / "profile.yaml"
    bad.write_text(text, encoding="utf-8")
    s = Script("")
    assert setup.load_draft(bad, s.ask, s.say) is None
    assert s.out and "profile.yaml" in s.out[0] and "blank" in s.prompts[0]
    s = Script("y")
    assert setup.load_draft(bad, s.ask, s.say) == {}


def test_cli_setup_upgrades_an_existing_v1_profile(tmp_path, monkeypatch, capsys):
    from jobagent import cli

    (tmp_path / "profile.yaml").write_text(V1.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "y" if prompt.startswith(("Write", "Overwrite")) else "")
    assert cli.setup_mode(tmp_path) is True
    new = prof.load_profile(tmp_path / "profile.yaml")
    assert new["version"] == 2 and any(f["id"] == "skill.python" for f in new["facts"])
    (backup,) = tmp_path.glob("profile.yaml.bak-*")
    assert backup.read_text(encoding="utf-8") == V1.read_text(encoding="utf-8")


def test_cli_cancel_with_ctrl_c_or_end_of_input(tmp_path, monkeypatch, capsys):
    from jobagent import cli

    for exc in (KeyboardInterrupt, EOFError):
        def boom(prompt="", exc=exc):
            raise exc

        monkeypatch.setattr("builtins.input", boom)
        with pytest.raises(SystemExit) as e:
            cli.setup_mode(tmp_path)
        assert e.value.code == 130
        assert "Cancelled. Nothing written." in capsys.readouterr().out
    assert not (tmp_path / "profile.yaml").exists()


def test_cli_unreadable_profile_aborts_by_default(tmp_path, monkeypatch, capsys):
    from jobagent import cli

    (tmp_path / "profile.yaml").write_text("a: [", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    with pytest.raises(SystemExit):
        cli.setup_mode(tmp_path)
    assert (tmp_path / "profile.yaml").read_text(encoding="utf-8") == "a: ["
    assert "profile.yaml" in capsys.readouterr().out


# --- interview details ----------------------------------------------------------------------------------

def draft_with(*facts, **flat):
    return {"version": 2, "first_name": "Alex", "last_name": "Example", "email": "alex@example.com",
            "facts": list(facts), **flat}


def test_extra_keys_of_a_known_kind_survive():
    draft = draft_with({"id": "skill.python", "kind": "skill", "name": "Python", "years": 3, "category": "backend"})
    s = Script("", "", "", *BLANK_FLAT, "", "", "", "", "", "", "")
    p = run(s, draft)
    assert p["facts"] == draft["facts"] and not s.answers


def test_freed_bullet_ids_are_not_reused():
    exp = {"id": "exp.acme-2023", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2023-01",
           "end": "present", "bullets": [{"id": "exp.acme-2023.b1", "text": "one"},
                                         {"id": "exp.acme-2023.b2", "text": "two"}]}
    # keep title, company, start, end; remove bullet one, keep bullet two, add a new one, then nothing more
    s = Script("", "", "", *BLANK_FLAT, "", "", "", "", "", "", "-", "", "new one", "", "", "", "")
    p = run(s, draft_with(exp))
    assert [b["id"] for b in p["facts"][0]["bullets"]] == ["exp.acme-2023.b2", "exp.acme-2023.b3"]
    assert p["facts"][0]["bullets"][1]["text"] == "new one"


def test_one_bad_fact_is_dropped_and_said_instead_of_losing_everything():
    exp = {"id": "exp.acme-2023", "kind": "experience", "title": "Dev", "org": "Acme", "start": "2023-01",
           "end": "present"}
    # skill: keep name and years; no new skill, cert; experience: keep all but end 2020-01 (before the start)
    s = Script("", "", "", *BLANK_FLAT, "", "", "", "", "", "", "", "2020-01", "", "", "", "", "")
    p = run(s, draft_with({"id": "skill.python", "kind": "skill", "name": "Python", "years": 3}, exp))
    assert p is not None and [f["id"] for f in p["facts"]] == ["skill.python"]
    assert any("exp.acme-2023" in line and "dropped" in line.lower() for line in s.out)


def test_a_draft_id_that_is_not_usable_gets_a_new_one():
    draft = draft_with({"id": "Skill Rust", "kind": "skill", "name": "Rust", "years": 1},
                       {"id": "skill.go", "kind": "skill", "name": "Go", "years": 1},
                       {"id": "skill.go", "kind": "skill", "name": "Go again", "years": 2})
    p = run(Script("", "", "", *BLANK_FLAT, *([""] * 12)), draft)
    assert [f["id"] for f in p["facts"]] == ["skill.rust", "skill.go", "skill.go-again"]


def test_draft_facts_that_cannot_be_kept_are_reported():
    draft = draft_with({"id": "hobby.chess", "kind": "hobby", "name": "Chess"}, "not a mapping")
    s = Script("", "", "", *BLANK_FLAT, *([""] * 10))
    p = run(s, draft)
    assert p["facts"] == []
    text = "\n".join(s.out)
    assert "hobby" in text and "not a mapping" in text


def test_legacy_flat_keys_are_dropped_once_they_became_facts():
    legacy = yaml.safe_load(V1.read_text(encoding="utf-8"))
    assert "degree" in legacy and "english" in legacy
    draft = prof.migrate(legacy)
    assert "degree" in draft  # an in-memory load keeps them
    p = run(Script(*([""] * 300)), draft)
    assert p is not None
    assert not {"degree", "english", "spanish"} & set(p)
    assert any(f["kind"] == "education" for f in p["facts"]) and any(f["kind"] == "language" for f in p["facts"])
