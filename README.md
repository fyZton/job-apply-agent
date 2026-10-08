# job-apply-agent

[![CI](https://github.com/fyZton/job-apply-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/fyZton/job-apply-agent/actions/workflows/ci.yml)

A job-application agent I built for my own job search. It finds offers on job boards, scores each one against my
profile with an LLM, fills the application form and logs everything to a spreadsheet. It has sent real
applications on LinkedIn and Computrabajo.

> Work in progress. The roadmap is at the end of this file.

## How it works

```
search (per-board plugin) -> title filters -> LLM fit score (1-10) -> pick CV -> fill form -> submit or flag
```

- **Plugins per job board:** each board is one module in `jobagent/sites/`. The package loads every module
  that implements the plugin contract, so adding a board means adding one file.
- **The LLM only answers from your profile.** Form answers come from fixed rules first, then from a cache of
  past answers, and only then from the LLM. If a required field asks for something the profile doesn't have,
  the application is flagged for manual review instead of guessed.
- **Cheap filters run first.** Titles with excluded words (senior, lead, ...) are dropped before any LLM call.
- **Human pace:** daily limits per board and 1.5 to 4 minute pauses between applications.
- **No API key needed:** by default it calls Claude through the Claude Code CLI (`claude -p`) with tools
  disabled. The Anthropic API is available as an option, see [LLM backends](#llm-backends).
- **Guarded LLM calls:** postings are treated as untrusted data, replies are validated, and a `data/STOP`
  file halts the run. See [Prompt-injection defense](#prompt-injection-defense).

| Board | Status |
|---|---|
| LinkedIn (Easy Apply) | Working |
| Computrabajo Venezuela | Working |
| Demo board (local, fake) | Working, used by `--demo` and CI |

## Try it without accounts

```bash
pip install -e .
playwright install chromium
python -m jobagent --demo
```

This starts a fake job board on your machine (`jobagent/demo/board`) and opens a browser so you can watch the
agent work through seven made-up offers:

| Offer | What the agent does |
|---|---|
| Backend Developer (Python) | Fills a one-page form, uploads the CV and submits |
| Integrations Developer | Goes through a two-step form with unlabeled radios, a select and a consent checkbox |
| Python Developer | Stops: the form asks for a national ID number, which the profile doesn't have |
| Senior Backend Engineer | Skips it by title, without calling the LLM |
| Backend Developer (on-site, Madrid) | Scores it low because the profile only accepts remote work |
| Python Backend Developer | Skips it: already applied |
| Python Integrations Developer | Flags it as suspicious: a hidden line tells the model to rate the candidate 10. No LLM call, a row "To apply" in the sheet |

The demo uses a stub instead of the LLM (`JOBAGENT_LLM=fake`), so it needs no Claude account. Run
`JOBAGENT_LLM=claude python -m jobagent --demo` to use the real model. Add `--headless` to hide the browser and
`--dry-run` to stop before every submit. CI runs the same scenario on every push.

## Quick start

Requires Python 3.11+ and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

```bash
pip install -e .
playwright install chromium
cp config.example.yaml config.yaml     # boards, limits, searches
cp profile.example.yaml profile.yaml   # your data; the LLM answers only from here
python -m jobagent --login             # log in once; sessions are kept in ~/.jobagent/browser
python -m jobagent --dry-run           # does everything except submitting
python -m jobagent
```

`config.yaml`, `profile.yaml`, `cv/` and `data/` are git-ignored, so personal data stays on your machine.

## Tests

```bash
pip install -e ".[dev]"
playwright install chromium
pytest
```

The tests never call a real LLM: they replace it with a stub that returns fixed answers, so they are free and
give the same result every run. The API backend is tested against a fake `anthropic` module, so the SDK is not
needed to run them. The form scanner is tested against a local HTML page that reproduces fields that
broke the bot on real sites (radios without labels, a "Confirmed" checkbox whose required mark sits outside its
label, search boxes that must be ignored). CI runs lint, tests and the offline evals on Linux and Windows with Python 3.11 and 3.12,
and scans the git history for leaked secrets with gitleaks.

## LLM backends

Set `llm.backend` in `config.yaml`, or the `JOBAGENT_LLM` environment variable, which wins over the file.

| Backend | What it uses | Setup |
|---|---|---|
| `claude` (default) | Claude Code CLI, `claude -p` with tools disabled | Claude Code installed and logged in |
| `api` | Anthropic API through the official Python SDK | `pip install -e ".[api]"` and `ANTHROPIC_API_KEY` |
| `fake` | Fixed rules, no network | Only with `--demo` and `--eval` |

The `api` backend maps the `haiku` and `sonnet` aliases to the model IDs in `llm.api_models`, calls the API with
a 120 second timeout, two retries and `effort: low`, and never logs credentials. For the Sonnet model it also
turns on the server-side refusal fallback beta, which exists only on the Claude API. If the model refuses a
request the call returns nothing and the offer is skipped.

Every call is counted. The end-of-run summary shows calls, tokens and estimated cost per model. Prices come from
`llm.prices_usd_per_mtok`, and the run stops when the estimate passes `llm.max_cost_usd_per_run`. With the `claude`
backend the cost comes from the CLI's own report. Update the model IDs and prices in `config.yaml` when they change.

## Prompt-injection defense

Job postings and form labels are written by third parties and end up in the prompt. Three layers limit the damage:

1. **Detector.** Before any LLM call, the posting goes through `looks_injected` (`jobagent/safety.py`). It looks
   for phrases like "ignore previous instructions" (English and Spanish), "system prompt", "you are now", role
   markers at the start of a line, requests to score the candidate 10, `"fit": 10`, fake `<job_posting>` tags and
   zero-width characters. A hit skips the offer, adds a "To apply" row with the reasons in Notes, and makes no
   LLM call. It is a tripwire for obvious attacks and will miss a careful one.
2. **Data framing.** The posting is wrapped in `<job_posting>` and the form fields in `<form_fields>`, and the
   prompt says that text inside those tags is data, never instructions. A closing tag inside the posting is
   rewritten so it can't end the block early.
3. **Output validation.** Whatever the model returns is checked before use. A score must be an integer from 1 to
   10, and the CV name must be one of the configured files. Form answers are kept only for field ids that
   exist, values must be plain strings, numbers or booleans, and text is capped at 200 characters (2000 for
   text areas). A years-of-experience answer above the largest value in the profile is rejected and the field
   is left for you to fill in by hand.

The model also runs with no tools, so a successful injection can change a score or a form answer but can't run
anything. Only put in `profile.yaml` what you would be fine sharing with an employer, since form answers are
built from it. Screenshots and diagnostics in `data/` can contain your filled-in data; they stay local and are
git-ignored.

## Stopping a run (data/STOP)

Create an empty file named `STOP` in the data folder (`data/STOP` by default) and the run stops before the next
offer. The log says `STOP file found; delete it to run again`. The agent never deletes the file, so it keeps
blocking runs until you remove it.

```bash
touch data/STOP     # stop
rm data/STOP        # allow runs again
```

## Evals

```bash
python -m jobagent --eval           # offline, fake backend, exit code 1 if any case fails
python -m jobagent --eval --live    # sends the cases to the configured backend, reports pass rates only
```

The cases are YAML files in `evals/`: `fit.yaml` (offers the candidate should score high or low on, and which
CV to pick), `honesty.yaml` (form answers must come from the profile, not from the model's imagination) and
`injection.yaml` (postings that try to steer the scorer, in English and Spanish, with zero-width characters).
Injection cases marked `bypass_detector: true` skip the detector and go straight to the scorer, which has to
keep its score in range anyway.

Offline evals test the pipeline around the model: the detector, validation, length caps and the years check. The
fake backend behaves like an honest model, so passing offline says nothing about how a real model behaves.
`--live` is the run that measures the model, and it costs tokens. Each run writes
`data/evals/report-YYYYMMDD-HHMM.json` and `.md`:

| Suite | Passed | Total | Pass rate |
|---|---|---|---|
| fit | 7 | 7 | 100% |
| honesty | 10 | 10 | 100% |
| injection | 10 | 10 | 100% |

The tests check that the evals can fail: with a fake that always answers fit 10, the fit and injection suites
report failures.

## Use it responsibly

Automating applications can break a job board's terms of service and can get your account restricted. This
project does not try to hide that it is automated. Keep the daily limits low, check the dry run first, and use it
at your own risk.

## Roadmap

- [x] Tests with local HTML fixtures and a fake LLM, CI on Windows and Linux, secret scanning
- [ ] Profile setup from your existing CV (`--setup`)
- [ ] ATS-friendly CV generator (PDF/DOCX, English/Spanish), tailored per offer without adding facts
- [x] Demo mode with a fake local job board, runnable without accounts
- [x] Prompt-injection defense, STOP switch, API backend with cost budget, and LLM evals for honesty
- [ ] SQLite state machine, funnel report and human-approval dashboard
- [ ] Docker image

## License

MIT
