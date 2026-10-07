from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from jobagent.forms import JS_SCAN

HTML = (Path(__file__).parent / "fixtures" / "tricky_form.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.set_content(HTML)
        yield pg
        browser.close()


@pytest.fixture(scope="module")
def fields(page):
    found = page.locator("#apply").evaluate(JS_SCAN)
    return {f["question"]: f for f in found}


def test_reads_labels_from_for_and_aria_labelledby(fields):
    assert fields["Email address"]["type"] == "email"
    assert fields["Email address"]["required"] is True
    assert fields["Years of experience with Python"]["type"] == "number"


def test_radio_question_from_legend_and_from_surrounding_text(fields):
    auth = fields["Are you authorized to work remotely?"]
    assert auth["options"] == ["Yes", "No"]
    visa = fields["Do you need visa sponsorship? *"]
    assert visa["options"] == ["Yes", "No"] and visa["required"] is True


def test_checkbox_takes_question_and_required_mark_from_outside_label(fields):
    agree = fields["Confirmed"]
    assert agree["type"] == "checkbox"
    assert "privacy policy" in agree["context"] and agree["required"] is True


def test_select_combobox_and_textarea(fields):
    assert fields["English level"]["options"] == ["Select an option", "Basic", "Fluent"]
    assert fields["City"]["autocomplete"] is True
    assert fields["Why do you want this job?"]["type"] == "textarea"


def test_ignores_hidden_disabled_password_and_search_fields(page, fields):
    assert "Old field" not in fields and "Hidden field" not in fields
    assert len(fields) == 8
    assert page.locator("#search").evaluate(JS_SCAN) == []


def test_rescan_never_tags_two_fields_with_the_same_id(page):
    root = page.locator("#apply")
    root.evaluate(JS_SCAN)
    page.evaluate("document.getElementById('email').disabled = true")
    root.evaluate(JS_SCAN)
    assert page.locator('[data-ap="ap0"]').count() == 1
