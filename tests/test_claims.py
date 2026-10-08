"""jobagent.claims fails closed: an answer other than No / 0 / None needs a profile fact behind every thing it names."""
import pytest

from jobagent.claims import Claims
from jobagent.facts import load_facts

BASE = [
    {"id": "skill.sd", "kind": "skill", "name": "Software development", "years": 3},
    {"id": "skill.python", "kind": "skill", "name": "Python 3", "years": 3},
    {"id": "skill.sql", "kind": "skill", "name": "SQL", "years": 2},
    {"id": "skill.rest", "kind": "skill", "name": "REST APIs", "years": 2},
    {"id": "skill.docker", "kind": "skill", "name": "Docker", "years": 1},
    {"id": "lang.en", "kind": "language", "name": "English", "level": "B2"},
    {"id": "lang.es", "kind": "language", "name": "Spanish", "level": "native"},
    {"id": "edu.se", "kind": "education", "name": "B.Sc. Systems Engineering", "year": 2023},
    {"id": "exp.acme", "kind": "experience", "title": "Backend Developer", "org": "Acme", "start": "2023-01"},
]
CERT = {"id": "cert.aws", "kind": "cert", "name": "AWS Cloud Practitioner", "year": 2024}
PROFILE = {"country": "Venezuela", "city": "Caracas", "first_name": "Alex", "facts": BASE}
WITH_CERT = {**PROFILE, "facts": BASE + [CERT]}
YN = ["Yes", "No"]


def verdict(question, value, type_="radio", options=None, profile=PROFILE):
    claims = Claims(load_facts(profile), None, profile)
    field = {"type": type_, "options": YN if options is None and type_ in ("radio", "select") else options}
    return claims.check(field, question, value)[0]


REJECT_YES = [
    "Can you work with Kubernetes?", "Have you managed Kubernetes clusters in production?",
    "Do you have a Kubernetes background?", "Do you have hands-on Kubernetes?", "Kubernetes?",
    "Can you code in Go?", "Have you programmed in Rust?", "Are you able to write Terraform?",
    "Have you deployed to AWS?", "Do you hold the CKA?", "Are you a PMP?", "Do you hold an AWS certification?",
    "¿Has trabajado con Kubernetes?", "¿Sabes Kubernetes?", "¿Manejas Kubernetes?", "¿Dominas Kubernetes?",
    "Do you have a bachelor's degree in Medicine?",
]


@pytest.mark.parametrize("question", REJECT_YES)
@pytest.mark.parametrize("type_, value", [("radio", "Yes"), ("select", "Yes"), ("checkbox", True)])
def test_yes_to_something_not_in_the_profile_is_rejected(question, type_, value):
    assert not verdict(question, value, type_, None if type_ == "checkbox" else YN)


@pytest.mark.parametrize("type_, value", [("number", "4"), ("text", "4 years"), ("checkbox", True),
                                          ("radio", "Yes"), ("text", "Yes")])
def test_bare_technology_label_is_a_claim_question(type_, value):
    assert not verdict("Kubernetes", value, type_)


@pytest.mark.parametrize("question, value, type_, options", [
    ("List your main technical skills", "Rust, Go, Kubernetes, Terraform", "textarea", None),
    ("Which certifications do you hold?", "AWS Solutions Architect Professional, PMP", "textarea", None),
    ("Anything else?", "Python for 9 years", "textarea", None),
    ("Anything else?", "Ten years of Python.", "textarea", None),
    ("Anything else?", "Diez años de Python.", "textarea", None),
    ("Anything else?", "I built Kubernetes operators in Go.", "textarea", None),
    ("Anything else?", "I hold a PhD in Computer Science.", "textarea", None),
    ("Anything else?", "I speak fluent German.", "textarea", None),
    ("Anything else?", "Hablo alemán con fluidez.", "textarea", None),
    ("Anything else?", "I am a certified Kubernetes administrator.", "textarea", None),
    ("Anything else?", "I speak English at a native level.", "textarea", None),
    ("Rate your French (1-5)", "5", "select", ["1", "2", "3", "4", "5"]),
    ("Rate your English (1-5)", "5", "select", ["1", "2", "3", "4", "5"]),
    ("How well do you speak German?", "Very well", "text", None),
    ("Your English proficiency?", "Excellent", "text", None),
])
def test_claims_the_profile_does_not_back_are_rejected(question, value, type_, options):
    assert not verdict(question, value, type_, options)


@pytest.mark.parametrize("question, value, type_, options", [
    ("Can you work with Python?", "Yes", "radio", YN),
    ("Do you have Python experience?", "Yes", "radio", YN),
    ("Do you have Python experience?", "Yes", "checkbox", None),
    ("How many years of experience do you have?", "3", "number", None),
    ("¿Cuántos años de experiencia tienes con Python?", "3", "number", None),
    ("List your skills", "Python (3 years), SQL (2 years)", "textarea", None),
    ("Tell us about yourself", "I have 3 years of Python experience building REST APIs.", "textarea", None),
    ("Are you legally authorized to work in the United States?", "Yes", "radio", YN),
    ("Expected monthly salary in USD", "1800", "number", None),
    ("Notice period", "2 weeks", "text", None),
    ("Country", "Venezuela", "text", None),
    ("Current city", "Caracas", "text", None),
    ("English level", "B2", "select", ["A2", "B1", "B2", "C1"]),
    ("What is your proficiency in English?", "Professional working proficiency", "select",
     ["Limited working proficiency", "Professional working proficiency"]),
    ("Your English level?", "Upper intermediate", "text", None),
    ("Your English proficiency?", "Intermediate", "text", None),
    ("Spanish level", "Native", "select", ["Basic", "Native"]),
    ("Do you speak Spanish?", "Yes", "radio", YN),
    ("Do you have a Bachelor's degree?", "Yes", "radio", YN),
    ("Do you have a bachelor's degree in Systems Engineering?", "Yes", "radio", YN),
    ("Rate your English (1-5)", "4", "select", ["1", "2", "3", "4", "5"]),
    ("Which languages do you speak?", "English and Spanish", "text", None),
    ("Why do you want this job?", "I like building backend services with Python at Acme.", "textarea", None),
    ("Do you have experience with Kubernetes?", "No", "radio", YN),
    ("How many years of Kubernetes?", "0", "number", None),
    ("Kubernetes", "None", "select", ["None", "Some"]),
    ("Kubernetes?", False, "checkbox", None),
    ("Do you hold the CKA?", "No", "radio", YN),
])
def test_claims_the_profile_backs_are_accepted(question, value, type_, options):
    assert verdict(question, value, type_, options)


def test_cert_question_needs_a_cert_fact():
    assert verdict("Do you hold an AWS certification?", "Yes", profile=WITH_CERT)
    assert verdict("Are you AWS certified?", "Yes", profile=WITH_CERT)
    assert not verdict("Do you hold the CKA?", "Yes", profile=WITH_CERT)
    assert not verdict("Have you deployed to AWS?", "Yes", profile=WITH_CERT)
    assert verdict("Which certifications do you hold?", "AWS Cloud Practitioner", "textarea", profile=WITH_CERT)
    assert not verdict("Which certifications do you hold?", "AWS Cloud Practitioner, PMP", "textarea",
                       profile=WITH_CERT)


def test_language_level_above_the_fact_is_rejected():
    assert not verdict("Your English level?", "Fluent", "text")
    assert not verdict("Anything else?", "My English is native.", "textarea")
    assert verdict("Anything else?", "My English is intermediate.", "textarea")


@pytest.mark.parametrize("answer, ok", [
    ("I have used kubernetes and terraform daily.", False),
    ("mostly python and sql", True),
    ("i know rust, go and kafka", False),
    ("I write rust code", False),
    ("ten years of golang", False),
    ("experience with c++ and .net", False),
    ("I like go-karts and I make coffee", True),
    ("we go to the market, then make dinner", True),
    ("I use docker and python", True),
    ("sparks of joy", True),
])
def test_lowercase_technology_names_in_free_text(answer, ok):
    assert verdict("Anything else?", answer, "textarea") is ok


def test_lowercase_city_answer_and_topic_questions():
    assert verdict("Current city", "caracas", "text")
    assert not verdict("Current city", "kubernetes", "text")
    assert verdict("Do you have a Kubernetes background?", "kubernetes", "text") is False
    assert verdict("Do you use terraform at work?", "we use terraform every day at the office", "text")


# --- round 6: a topic word in the question never switches the checks off ---------------------------------------

def verdict_q(question, value, type_="radio", options=None, context="", profile=PROFILE):
    claims = Claims(load_facts(profile), None, profile)
    field = {"type": type_, "question": question, "options": YN if options is None and type_ == "radio" else options}
    return claims.check(field, f"{context} {question}".strip(), value)[0]


TOPIC_REJECT = [
    ("number", "How many years have you worked with Kubernetes remotely?", "10"),
    ("number", "How many years have you run highly available Kubernetes clusters?", "7"),
    ("number", "How many years have you used Java at an employer?", "8"),
    ("text", "Years using Java with your current employer", "8 years"),
    ("number", "¿Cuántos años has trabajado con Kubernetes en remoto?", "9"),
    ("number", "Years with Kubernetes in your country", "8"),
    ("radio", "Do you have 5+ years working remotely with Kubernetes?", "Yes"),
    ("radio", "Have you used Kubernetes at your current employer?", "Yes"),
    ("radio", "Have you written Kubernetes network policy manifests?", "Yes"),
    ("radio", "Have you worked remotely with Kubernetes?", "Yes"),
    ("radio", "Can you write Go in our time zone?", "Yes"),
    ("radio", "Do you speak German fluently with remote clients?", "Yes"),
    ("radio", "Do you hold a Master's degree from a university in your country?", "Yes"),
    ("radio", "Are you PMP certified, as required by our hiring policy?", "Yes"),
    ("radio", "This is a remote role. Are you a native English speaker?", "Yes"),
    ("radio", "Do you speak German? (remote position)", "Yes"),
    ("radio", "Do you hold a Master's degree? Location: remote", "Yes"),
    ("select", "What is your German level? (needed for this location)", "Native"),
    ("textarea", "Why do you want to work here?", "I am a seasoned Deno and Qwik developer."),
    ("textarea", "Tell us about yourself", "I am a seasoned Deno and Qwik developer."),
    ("radio", "Do you speak English fluently?", "Yes"),
    ("textarea", "Anything else?", "I speak English fluently."),
    ("select", "English level", "Advanced"),
    ("textarea", "Anything else?", "I am a certified Scrum Master."),
]


@pytest.mark.parametrize("type_, question, value", TOPIC_REJECT)
def test_topic_words_do_not_switch_the_checks_off(type_, question, value):
    options = {"select": ["Native", "Basic"] if "German" in question else ["Basic", "Intermediate", "Advanced"]}
    assert not verdict_q(question, value, type_, options.get(type_))


def test_legend_context_does_not_make_a_topic():
    assert not verdict_q("Years of Kubernetes?", "5", "number", context="Remote work questionnaire")


@pytest.mark.parametrize("type_, question, value, options", [
    ("text", "Current city", "Caracas", None),
    ("text", "Country of residence", "Venezuela", None),
    ("number", "Expected monthly salary in USD", "1800", None),
    ("text", "Notice period", "2 weeks", None),
    ("radio", "Are you legally authorized to work in the United States?", "Yes", YN),
    ("textarea", "Why do you want to work here?",
     "I like your remote-first culture and I have 3 years of Python.", None),
    ("number", "How many years have you worked with Python remotely?", "3", None),
    ("select", "English level", "Upper intermediate", ["Basic", "Intermediate", "Upper intermediate", "Advanced"]),
    ("select", "¿Nivel de inglés?", "Intermedio alto", ["Básico", "Intermedio", "Intermedio alto", "Avanzado"]),
    ("radio", "Do you speak English fluently?", "No", YN),
    ("select", "Gender", "Prefer not to say", ["Male", "Female", "Prefer not to say"]),
    ("radio", "Do you agree to the terms and the privacy policy?", "Yes", YN),
])
def test_topic_questions_still_get_their_answers(type_, question, value, options):
    assert verdict_q(question, value, type_, options)


def test_scrum_master_is_a_cert_not_a_degree():
    claims = Claims(load_facts(PROFILE), None, PROFILE)
    why = claims.check({"type": "textarea"}, "Anything else?", "I am a certified Scrum Master.")[1]
    assert why and "degree" not in why


@pytest.mark.parametrize("answer", ["I know python, sql, excel and git", "html and css", "nosql"])
def test_generic_tech_names_are_known(answer):
    from jobagent.claims import known_tech
    assert known_tech(answer)
