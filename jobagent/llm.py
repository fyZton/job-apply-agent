"""LLM access: Claude Code CLI (`claude -p`, no API key), the Anthropic API (optional extra) or a fake.

Every reply goes through jobagent.safety validation before the rest of the agent sees it.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import yaml

from jobagent.safety import DATA_RULE, validate_answers, validate_score, wrap_posting

logger = logging.getLogger(__name__)

DEFAULTS = {
    "backend": "claude",
    "api_models": {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"},
    "prices_usd_per_mtok": {"claude-haiku-5-5": [0.10, 0.50], "claude-sonnet-5-5": [2.0, 10.0]},
    "max_cost_usd_per_run": 1.0,
}
FALLBACK_MODEL = "claude-sonnet-5-5"  # the only model that uses the server-side refusal fallback beta
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_cfg = dict(DEFAULTS)
USAGE = {}


class BudgetExceeded(Exception):
    """The run spent more than llm.max_cost_usd_per_run."""


def reset_usage():
    USAGE.clear()
    USAGE.update(calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0, by_model={})


def configure(llm_cfg):
    """Applies the `llm:` section of config.yaml and resets the usage counter."""
    global _cfg
    _cfg = {**DEFAULTS, **{k: v for k, v in (llm_cfg or {}).items() if v is not None}}
    reset_usage()


def backend():
    return os.environ.get("JOBAGENT_LLM") or _cfg["backend"]


def _record(model, input_tokens, output_tokens, cost=None):
    """Adds one call to USAGE and raises BudgetExceeded when the run is over budget."""
    if cost is None:
        price_in, price_out = _cfg["prices_usd_per_mtok"].get(model, (0, 0))
        cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    per_model = USAGE["by_model"].setdefault(model, dict(calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0))
    for d in (USAGE, per_model):
        d["calls"] += 1
        d["input_tokens"] += input_tokens
        d["output_tokens"] += output_tokens
        d["cost_usd"] += cost
    limit = _cfg["max_cost_usd_per_run"]
    if limit is not None and USAGE["cost_usd"] > limit:
        raise BudgetExceeded(f"LLM cost ${USAGE['cost_usd']:.2f} is over the ${limit:.2f} limit for this run")


def usage_summary():
    lines = [f"LLM usage: {USAGE['calls']} calls, {USAGE['input_tokens']} input / {USAGE['output_tokens']} output "
             f"tokens, ${USAGE['cost_usd']:.2f}"]
    for model, u in USAGE["by_model"].items():
        lines.append(f"  {model}: {u['calls']} calls, ${u['cost_usd']:.2f}")
    return "\n".join(lines)


reset_usage()


def _claude_exe():
    for name in ("claude.cmd", "claude.exe", "claude"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError('Claude Code ("claude" command) not found. Is it installed?')


def _call_claude(prompt, model):
    r = subprocess.run(
        [_claude_exe(), "-p", "--model", model, "--tools", "", "--no-session-persistence",
         "--output-format", "json"],
        input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=tempfile.gettempdir(), timeout=300,
    )
    try:
        data = json.loads(r.stdout)
        text = data["result"]
        usage = data.get("usage") or {}
    except (json.JSONDecodeError, KeyError, TypeError):
        _record(model, 0, 0, cost=0.0)  # plain text: count the call, tokens unknown
        return r.stdout
    tokens_in = sum(usage.get(k) or 0 for k in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    _record(model, tokens_in, usage.get("output_tokens") or 0, cost=data.get("total_cost_usd"))
    return text


def _call_api(prompt, model):
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("The API backend needs the Anthropic SDK: pip install 'jobagent[api]'") from None
    model_id = _cfg["api_models"].get(model, model)
    client = anthropic.Anthropic().with_options(timeout=120.0, max_retries=2)
    kwargs = dict(model=model_id, max_tokens=4000, messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": "low"})
    try:
        if model_id == FALLBACK_MODEL:
            response = client.beta.messages.create(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        raise RuntimeError("Anthropic credentials missing or invalid: set ANTHROPIC_API_KEY") from None
    except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        logger.warning("Anthropic API error: %s", type(e).__name__)
        return None
    u = response.usage
    tokens_in = sum(getattr(u, k, None) or 0 for k in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    _record(model_id, tokens_in, u.output_tokens or 0)
    if response.stop_reason == "refusal":
        logger.warning("The model refused the request")
        return None
    return "".join(b.text for b in response.content if b.type == "text")


def _complete(prompt, model):
    """Sends the prompt to the configured backend and returns the raw text, or None."""
    if backend() == "api":
        return _call_api(prompt, model)
    try:
        return _call_claude(prompt, model)
    except subprocess.TimeoutExpired:
        return None


def extract_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def ask_json(prompt, model="sonnet", attempts=2):
    """Sends the prompt to the LLM and returns the JSON in its answer, or None."""
    for _ in range(attempts):
        data = extract_json(_complete(prompt, model))
        if data is not None:
            return data
    return None


def score_offer(offer, profile_text, cvs, rules, model):
    """Returns {"fit", "cv", "company", "title", "reason"} or None."""
    cv_list = "\n".join(f'- "{c["file"]}": {c["use_for"]}' for c in cvs)
    rule_list = "\n".join(f"- {r}" for r in rules)
    prompt = f"""{DATA_RULE}

Decide whether this job offer fits the candidate. Be strict and realistic.

CANDIDATE PROFILE (YAML):
{profile_text}

AVAILABLE CVS:
{cv_list}

OFFER (source: {offer.site}, link: {offer.url}):
{wrap_posting(f"Title: {offer.title}{chr(10)}Company: {offer.company}{chr(10)}Text:{chr(10)}{offer.text[:7000]}")}

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
    raw = _fake_score(offer, cvs) if backend() == "fake" else ask_json(prompt, model)
    return validate_score(raw, [c["file"] for c in cvs])


def answer_fields(fields, profile_text, offer, model):
    """Returns {"answers": {id: value}, "unknown": [ids]} or None."""
    prompt = f"""{DATA_RULE}

You are a candidate's application assistant. Answer the fields of an application form
with TRUE answers based only on their profile.

CANDIDATE PROFILE (YAML):
{profile_text}

OFFER:
{wrap_posting(f"{offer.title} at {offer.company} ({offer.site})")}

FIELDS (JSON):
<form_fields>
{json.dumps(fields, ensure_ascii=False, indent=1).replace("</form_fields>", "[/form_fields]")}
</form_fields>

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
    raw = _fake_answers(fields, profile_text) if backend() == "fake" else ask_json(prompt, model)
    return validate_answers(raw, fields)


# Fake backend (JOBAGENT_LLM=fake): deterministic rules that behave like an honest model and ignore any
# instruction inside the posting. Used by the demo, CI and the offline evals, so those test the pipeline
# around the model (detector, validation, caps), not the model itself.
def _fake_score(offer, cvs):
    text = offer.text
    onsite = re.search(r"on-site|onsite|hybrid|presencial|h[ií]brido", text, re.I)
    senior = re.search(r"\bsenior\b|\b([5-9]|\d{2})\+?\s*(years|años)", text, re.I)
    spanish = re.search(r"\b(desarrollador|remoto|experiencia|buscamos|empresa)\b", text, re.I)
    cv = next((c["file"] for c in cvs if spanish and "spanish" in c["use_for"].lower()), cvs[0]["file"])
    fit, reason = (2, "on-site") if onsite else (3, "too senior") if senior else (8, "remote and matching keywords")
    return {"fit": fit, "cv": cv, "company": offer.company, "title": offer.title, "reason": reason}


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
