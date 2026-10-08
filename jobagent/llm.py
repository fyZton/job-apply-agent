"""LLM access: Claude Code CLI (`claude -p`, no API key), the Anthropic API (optional extra) or a fake.

Every reply goes through jobagent.safety validation before the rest of the agent sees it.

Errors are typed so the caller can tell them apart from an unparseable reply (which is just None):
  ConfigError    credentials, package, model name or pricing are wrong: abort the whole run
  BudgetExceeded the run hit max_cost_usd_per_run or max_calls_per_run: abort the whole run
  LLMTransient   rate limit, 5xx, network or timeout: worth retrying later
  LLMError       anything else the backend rejected (e.g. a bad request): not retried
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import yaml

from jobagent.facts import facts_prompt, load_facts, match_skills
from jobagent.safety import (
    DATA_RULE,
    strip_sensitive,
    validate_answers,
    validate_score,
    wrap_cv,
    wrap_fields,
    wrap_posting,
)

logger = logging.getLogger(__name__)

DEFAULTS = {
    "backend": "claude",
    "form_model": "sonnet",  # also reads the CV in --setup --from-cv
    "api_models": {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"},
    "prices_usd_per_mtok": {"claude-haiku-5-5": [0.10, 0.50], "claude-sonnet-5-5": [2.0, 10.0]},
    "max_cost_usd_per_run": 1.0,  # null in config.yaml turns the cost limit off
    "max_calls_per_run": 300,  # null turns the call cap off
}
FALLBACK_MODEL = "claude-sonnet-5-5"  # the only model that uses the server-side refusal fallback beta
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NULLABLE = ("max_cost_usd_per_run", "max_calls_per_run")  # an explicit null disables the limit
ESTIMATED_OUTPUT_TOKENS = 1000  # floor used when the CLI reports no usage

_cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULTS.items()}
USAGE = {}


class LLMError(Exception):
    """The backend rejected or failed the request."""


class ConfigError(LLMError):
    """Wrong credentials, missing package, unknown model or unpriced model: nothing will work until fixed."""


class BudgetExceeded(LLMError):
    """The run spent more than llm.max_cost_usd_per_run or made more than llm.max_calls_per_run calls."""


class LLMTransient(LLMError):
    """Rate limit, server error, network failure or timeout."""


def reset_usage():
    USAGE.clear()
    USAGE.update(calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0, by_model={})


def configure(llm_cfg):
    """Applies the `llm:` section of config.yaml and resets the usage counter.

    Nested dicts are merged with the defaults. A null is ignored, except for the two budget limits, where it
    switches the limit off."""
    global _cfg
    merged = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULTS.items()}
    for key, value in (llm_cfg or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        elif value is not None or key in NULLABLE:
            merged[key] = value
    _cfg = merged
    reset_usage()
    if backend() != "fake":
        for alias in (_cfg.get("score_model"), _cfg.get("form_model")):
            if alias:
                _price(model_id(alias))


def backend():
    return os.environ.get("JOBAGENT_LLM") or _cfg["backend"]


def model_id(model):
    """Maps an alias ("haiku", "sonnet") to the model ID through llm.api_models."""
    return _cfg["api_models"].get(model, model)


def _price(model):
    try:
        return _cfg["prices_usd_per_mtok"][model]
    except KeyError:
        raise ConfigError(f"No price for model {model!r}: add it to llm.prices_usd_per_mtok "
                          f"([input, output] USD per million tokens)") from None


def _check_budget():
    """Raises BudgetExceeded before a call if the run is already over its cost or call limit."""
    limit, cap = _cfg["max_cost_usd_per_run"], _cfg["max_calls_per_run"]
    if limit is not None and USAGE["cost_usd"] > limit:
        raise BudgetExceeded(f"LLM cost ${USAGE['cost_usd']:.2f} is over the ${limit:.2f} limit for this run")
    if cap is not None and USAGE["calls"] >= cap:
        raise BudgetExceeded(f"{USAGE['calls']} LLM calls reached the limit of {cap} calls for this run")


def _record(model, input_tokens, output_tokens, cost=None):
    """Adds one call to USAGE and raises BudgetExceeded when the run is over budget."""
    model = model_id(model)
    if cost is None:
        price_in, price_out = _price(model)
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
    raise ConfigError('Claude Code ("claude" command) not found. Is it installed?')


def _call_claude(prompt, model):
    try:
        r = subprocess.run(
            [_claude_exe(), "-p", "--model", model, "--tools", "", "--no-session-persistence",
             "--output-format", "json"],
            input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=tempfile.gettempdir(), timeout=300,
        )
    except subprocess.TimeoutExpired:
        logger.warning("claude CLI timed out after 300 s")
        raise LLMTransient("claude CLI timed out") from None
    try:
        data = json.loads(r.stdout)
        text = data["result"]
        usage = data.get("usage") or {}
    except (json.JSONDecodeError, KeyError, TypeError):
        data, text, usage = {}, r.stdout, None
    if r.returncode != 0 or data.get("is_error"):
        logger.warning("claude CLI failed (exit %s): %s", r.returncode, (r.stderr or str(text)).strip()[:300])
        raise LLMError(f"claude CLI failed (exit {r.returncode})")
    if usage is None:  # plain text: tokens unknown, so estimate from the sizes instead of counting $0
        logger.warning("claude CLI output was not JSON; estimating the cost from the prompt size")
        _record(model, len(prompt) // 4, max(len(text) // 4, ESTIMATED_OUTPUT_TOKENS))
        return text
    tokens_in = sum(usage.get(k) or 0 for k in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    _record(model, tokens_in, usage.get("output_tokens") or 0, cost=data.get("total_cost_usd"))
    return text


def _call_api(prompt, model):
    try:
        import anthropic
    except ImportError:
        raise ConfigError("The API backend needs the Anthropic SDK: pip install 'jobagent[api]'") from None
    model_name = model_id(model)
    client = anthropic.Anthropic().with_options(timeout=120.0, max_retries=2)
    kwargs = dict(model=model_name, max_tokens=4000, messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": "low"})
    try:
        if model_name == FALLBACK_MODEL:
            response = client.beta.messages.create(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            response = client.messages.create(**kwargs)
    except anthropic.APIConnectionError as e:
        logger.warning("Anthropic API connection error: %s", type(e).__name__)
        raise LLMTransient(f"Anthropic API connection error ({type(e).__name__})") from None
    except anthropic.APIStatusError as e:
        code = getattr(e, "status_code", 0)
        logger.warning("Anthropic API error %s: %s", code, str(getattr(e, "message", e))[:200])
        if code in (401, 403):
            raise ConfigError(f"Anthropic API refused the credentials (HTTP {code}): "
                              "set a valid ANTHROPIC_API_KEY") from None
        if code == 404:
            raise ConfigError(f"Anthropic API does not know the model {model_name!r} (HTTP 404): "
                              "check llm.api_models") from None
        if code == 429 or code >= 500:
            raise LLMTransient(f"Anthropic API error (HTTP {code})") from None
        raise LLMError(f"Anthropic API rejected the request (HTTP {code})") from None
    u = response.usage
    tokens_in = sum(getattr(u, k, None) or 0 for k in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    _record(model_name, tokens_in, u.output_tokens or 0)
    if response.stop_reason == "refusal":
        logger.warning("The model refused the request")
        return None
    return "".join(b.text for b in response.content if b.type == "text")


def _complete(prompt, model):
    """Sends the prompt to the configured backend and returns the raw text, or None if the model refused."""
    _check_budget()
    return _call_api(prompt, model) if backend() == "api" else _call_claude(prompt, model)


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
    posting = wrap_posting("\n".join([f"Source: {offer.site}", f"Link: {offer.url}", f"Title: {offer.title}",
                                      f"Company: {offer.company}", "Text:", offer.text[:7000]]))
    prompt = f"""{DATA_RULE}

Decide whether this job offer fits the candidate. Be strict and realistic.

CANDIDATE PROFILE (YAML):
{profile_text}

AVAILABLE CVS:
{cv_list}

OFFER:
{posting}

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


def _without_sensitive(profile_text, drop=()):
    """The profile as YAML minus keys (and fixed-answer rules) about ids, banking, passwords or birth dates."""
    try:
        data = yaml.safe_load(profile_text)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        return "(profile unavailable)"
    data = {k: v for k, v in data.items() if k not in drop}
    return yaml.safe_dump(strip_sensitive(data), allow_unicode=True, sort_keys=False)


def answer_fields(fields, profile_text, offer, model, raw=None, facts=None):
    """Returns {"answers": {id: value}, "unknown": [ids], "facts": {id: [fact ids]}} or None.

    `facts` ({id: Fact}, from the profile) switches on grounded answers: the model sees the fact ids and must
    cite them. `raw`, if given, stands in for the model reply (the evals use it to test validation); it still
    goes through validate_answers."""
    if facts:
        years_rule = ('For "years of experience with X" use the years of the fact for X in FACTS; if X is not '
                      "there and is not clearly equivalent to a fact, answer 0.")
        profile_block = f"""{_without_sensitive(profile_text, drop=("facts",))}
FACTS (the only experience you may claim; cite their ids):
{facts_prompt(facts)}"""
        cite_rule = ('- A years-of-experience answer must cite the id of the skill fact it relies on, and cannot be '
                     'higher than that fact. Other answers may cite the facts they use; the "facts" list can be '
                     'empty when none is used. Never cite an id that is not in FACTS.\n')
        reply = ('{"answers": {"<id>": {"value": <value>, "facts": ["<fact id>"]}}, "unknown": ["<id>"]}')
    else:
        years_rule = ('For "years of experience with X" use years_of_experience from the profile; if X is not '
                      "there and is not clearly equivalent to something there, answer 0.")
        profile_block, cite_rule = _without_sensitive(profile_text), ""
        reply = '{"answers": {"<id>": <value>}, "unknown": ["<id>"]}'
    prompt = f"""{DATA_RULE}

You are a candidate's application assistant. Answer the fields of an application form
with TRUE answers based only on their profile.

CANDIDATE PROFILE (YAML):
{profile_block}

OFFER:
{wrap_posting(f"{offer.title} at {offer.company} ({offer.site})")}

FIELDS (JSON):
{wrap_fields(fields)}

Rules:
- Never invent or inflate experience. {years_rule}
{cite_rule}- Numeric fields: only the number.
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

Reply ONLY with JSON: {reply}"""
    if raw is None:
        raw = _fake_answers(fields, profile_text) if backend() == "fake" else ask_json(prompt, model)
    return validate_answers(raw, fields)


def extract_cv_facts(text, model=None):
    """Facts found in CV text, each with a `source` quote copied from it, or None. The caller must check
    that every quote really is in the text. Under the fake backend nothing is extracted."""
    if backend() == "fake":
        return []
    model = model or _cfg["form_model"]
    prompt = f"""{DATA_RULE}

Extract the facts a job application can rely on from this CV. Copy, never infer: only what the text says.

CV:
{wrap_cv(text)}

Reply ONLY with JSON: {{"facts": [ITEM, ...]}} where each ITEM has "kind" and a "source": a short quote copied
exactly from the CV that supports it. Kinds and their fields:
- skill: name, years (only if the CV states them; otherwise leave the item out)
- cert: name, year
- experience: title, org, start (YYYY-MM), end (YYYY-MM or "present"), bullets: [{{"text", "source"}}]
- education: name, org, year
- language: name, level"""
    raw = ask_json(prompt, model)
    return raw.get("facts") if isinstance(raw, dict) else None


# Fake backend (JOBAGENT_LLM=fake): deterministic rules that behave like an honest model and ignore any
# instruction inside the posting. Used by the demo, CI and the offline evals, so those test the pipeline
# around the model (detector, validation, caps), not the model itself.
def _fake_score(offer, cvs):
    text = offer.text
    onsite = re.search(r"on-site|onsite|hybrid|presencial|h[ií]brido", text, re.I)
    # 5 or more years as the minimum: "2-5 years" is not senior, "5-7 years" and "5+ years" are
    senior = re.search(r"\bsenior\b|(?<![\d-])([5-9]|\d{2})\+?(\s*-\s*\d+)?\s*(years|años)", text, re.I)
    spanish = re.search(r"\b(desarrollador|remoto|experiencia|buscamos|empresa)\b", text, re.I)
    cv = next((c["file"] for c in cvs if spanish and "spanish" in c["use_for"].lower()), cvs[0]["file"])
    fit, reason = (2, "on-site") if onsite else (3, "too senior") if senior else (8, "remote and matching keywords")
    return {"fit": fit, "cv": cv, "company": offer.company, "title": offer.title, "reason": reason}


def _fake_answers(fields, profile_text):
    profile = yaml.safe_load(profile_text) or {}
    facts = load_facts(profile)
    years = profile.get("years_of_experience") or {}
    answers, unknown = {}, []
    for f in fields:
        words = set(re.findall(r"\w+", f["question"].lower()))
        if "years" in words or "años" in words:
            if facts:
                matched = match_skills(facts, f["question"])
                best = max(matched, key=lambda m: m.years or 0, default=None)
                answers[f["id"]] = ({"value": str(int(best.years or 0)), "facts": [best.id]} if best else "0")
            else:
                answers[f["id"]] = str(next((v for k, v in years.items() if set(k.split("_")) & words), 0))
        elif f["type"] == "textarea":
            summary = profile.get("summary", "").strip()
            answers[f["id"]] = {"value": summary, "facts": list(facts)[:3]} if facts else summary
        elif f["type"] == "checkbox":
            answers[f["id"]] = "true"
        else:
            unknown.append(f["id"])
    return {"answers": answers, "unknown": unknown}
