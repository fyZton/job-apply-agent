"""LLM calls through Claude Code in non-interactive mode (`claude -p`), so no API key is needed."""
import json
import os
import re
import shutil
import subprocess
import tempfile

import yaml


def _claude_exe():
    for name in ("claude.cmd", "claude.exe", "claude"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError('Claude Code ("claude" command) not found. Is it installed?')


def extract_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def ask_json(prompt, model="sonnet", attempts=2):
    """Sends the prompt to Claude and returns the JSON in its answer, or None."""
    exe = _claude_exe()
    for _ in range(attempts):
        try:
            r = subprocess.run(
                [exe, "-p", "--model", model, "--tools", "", "--no-session-persistence",
                 "--output-format", "text"],
                input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=tempfile.gettempdir(), timeout=300,
            )
        except subprocess.TimeoutExpired:
            continue
        data = extract_json(r.stdout)
        if data is not None:
            return data
    return None


def score_offer(offer, profile_text, cvs, rules, model):
    """Returns {"fit", "cv", "company", "title", "reason"} or None."""
    if _fake():
        return _fake_score(offer, cvs)
    cv_list = "\n".join(f'- "{c["file"]}": {c["use_for"]}' for c in cvs)
    rule_list = "\n".join(f"- {r}" for r in rules)
    prompt = f"""Decide whether this job offer fits the candidate. Be strict and realistic.

CANDIDATE PROFILE (YAML):
{profile_text}

AVAILABLE CVS:
{cv_list}

OFFER (source: {offer.site}, link: {offer.url}):
Title: {offer.title}
Company: {offer.company}
Text:
{offer.text[:7000]}

Candidate-specific rules:
{rule_list}

General rules:
- Salary is NOT a reason to lower the fit (the candidate decides that).
- Judge like a recruiter: junior candidates apply (and get called) even when 2-3 years are asked.
  Up to 3 years asked: subtract at most 1-2 points. 5+ years or senior/lead level: fit at most 3.
- Equivalent tools count as transferable experience (n8n ≈ Zapier/Make/Workato; Salesforce ≈ other CRMs;
  Odoo ≈ other ERPs; PHP/Python/Java ≈ backend in general).
- Do not require ALL requirements: if the main ones are met and the offer is compatible, 5-7.
- Pick the most suitable CV; if the offer is written in Spanish, use the Spanish CV.

Reply ONLY with JSON:
{{"fit": <1-10>, "cv": "<exact file name>", "company": "<company>", "title": "<title>", "reason": "<max 20 words>"}}"""
    return ask_json(prompt, model)


def answer_fields(fields, profile_text, offer, model):
    """Returns {"answers": {id: value}, "unknown": [ids]} or None."""
    if _fake():
        return _fake_answers(fields, profile_text)
    prompt = f"""You are a candidate's application assistant. Answer the fields of an application form
with TRUE answers based only on their profile.

CANDIDATE PROFILE (YAML):
{profile_text}

OFFER: {offer.title} at {offer.company} ({offer.site})

FIELDS (JSON):
{json.dumps(fields, ensure_ascii=False, indent=1)}

Rules:
- Never invent or inflate experience. For "years of experience with X" use years_of_experience from the
  profile; if X is not there and is not clearly equivalent to something there, answer 0.
- Numeric fields: only the number.
- Salary / expectation / rate / amount (even in a text field): ONLY the number, no currency or words,
  derived from the profile's expected salary (monthly, yearly or hourly as asked).
- select/radio: answer EXACTLY the text of one of the options.
- checkbox: true or false (accept terms/privacy with true).
- Answer in the language of the question.
- Open questions (motivation, why this job, cover letter): 2-4 concrete first-person sentences
  based on the profile and the offer.
- If a field asks for data NOT in the profile that cannot be honestly deduced
  (e.g. ID number, references), put its id in "unknown".
- Leave out optional fields that don't apply.

Reply ONLY with JSON: {{"answers": {{"<id>": <value>}}, "unknown": ["<id>"]}}"""
    return ask_json(prompt, model)


# Fake backend (JOBAGENT_LLM=fake): fixed rules, no network. Used by the demo and by CI.
def _fake():
    return os.environ.get("JOBAGENT_LLM") == "fake"


def _fake_score(offer, cvs):
    onsite = re.search(r"on-site|onsite|hybrid|presencial|h[ií]brido", offer.text, re.I)
    return {"fit": 2 if onsite else 8, "cv": cvs[0]["file"], "company": offer.company, "title": offer.title,
            "reason": "on-site" if onsite else "remote and matching keywords"}


def _fake_answers(fields, profile_text):
    profile = yaml.safe_load(profile_text) or {}
    years = profile.get("years_of_experience") or {}
    answers, unknown = {}, []
    for f in fields:
        words = set(re.findall(r"\w+", f["question"].lower()))
        if "years" in words or "años" in words:
            answers[f["id"]] = str(next((v for k, v in years.items() if set(k.split("_")) & words), 0))
        elif f["type"] == "textarea":
            answers[f["id"]] = profile.get("summary", "").strip()
        elif f["type"] == "checkbox":
            answers[f["id"]] = "true"
        else:
            unknown.append(f["id"])
    return {"answers": answers, "unknown": unknown}
