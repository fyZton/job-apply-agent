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
cp profile.example.yaml profile.yaml   # your data; the LLM answers only from here (or run --setup)
python -m jobagent --login             # log in once; sessions are kept in ~/.jobagent/browser
python -m jobagent --dry-run           # does everything except submitting
python -m jobagent
```

`config.yaml`, `profile.yaml`, `cv/` and `data/` are git-ignored, so personal data stays on your machine.

## Profile and facts

`profile.yaml` has flat fields (name, email, links, salary, work mode, the rules for scoring and the fixed
answers) and a list of **facts**: the things the agent is allowed to claim. Every fact has an id that is written
once and never changes.

```yaml
version: 2
first_name: Alex
last_name: Example
email: alex@example.com
facts:
  - {id: skill.python, kind: skill, name: Python, years: 3}
  - {id: cert.aws-ccp, kind: cert, name: AWS Cloud Practitioner, year: 2024}
  - id: exp.acme-2023
    kind: experience
    title: Backend Developer
    org: Acme
    start: 2023-01
    end: present
    bullets:
      - {id: exp.acme-2023.b1, text: Built REST integrations}
  - {id: edu.bsc-computer-science, kind: education, name: B.Sc. Computer Science, year: 2023}
  - {id: lang.english, kind: language, name: English, level: B1}
```

Kinds are `skill` (with `years`), `cert`, `experience` (with `start`, `end` as `YYYY-MM` or `present`, and
`bullets`), `education` and `language`. Ids look like `skill.python` or `exp.acme-2023.b1` and must be unique.
`profile.example.yaml` is a full example.

Why ids:

- **Grounding.** The form prompt lists every fact as `[skill.python] Python, 3 years`. Only an answer that claims
  experience has to cite: a years question in a number, text or text area field must come back with the ids it
  relies on, as `{"value": "3", "facts": ["skill.python"]}`. A years question is one of three kinds. If it
  names a profile skill, the cited facts must include that skill and the answer cannot be above its years (the
  best of them if it names several). If it names something that is not a profile skill (`Rust`, `Kubernetes`,
  also in `years of Rust experience` or `worked with Rust`), only `0` is accepted. If it names nothing (`years of
  experience`, `¿cuántos años de experiencia tienes?`), any cited skill fact will do and the limit is the
  largest years among the cited skill facts. A plain `0` needs no citation. Salary, notice period, city and similar fields need no citation (the
  fixed answers and the profile values cover them), and a free-text answer may cite nothing when it uses no fact.
  Any cited id that doesn't exist rejects the answer, and a rejected field goes to manual review. A version 2
  profile with no skill facts sends every years question to manual review and logs one warning. The years check
  described under [Prompt-injection defense](#prompt-injection-defense) reads the same facts. A profile without
  facts keeps the old behavior. Select, radio and checkbox fields need no citation, but a yes to them is checked: a years
  threshold in the question (`at least 5 years`, `3+`, `más de 5 años`) must be within the same years limit, and a claim of
  experience with something (`experience with X`, `familiar with X`, `experiencia con X`) must name a profile skill. A no always passes.
- **CV generation.** The planned CV generator will pick and reorder facts by id, so a tailored CV can only
  contain what is in the profile.

`python -m jobagent` validates the profile on start and prints every problem at once, then exits with code 2,
for example `profile.yaml: facts[2].years must be a number >= 0 (got 'three')`. A profile with no `version` is
version 1 (`years_of_experience`, `degree`, `english`...). It is converted to facts in memory on every run and the
file is never rewritten; `--setup` upgrades it for good.

## Set up from your CV

```bash
pip install -e ".[cv]"                      # PDF and DOCX readers; .txt needs nothing extra
python -m jobagent --setup                  # questions, one field at a time
python -m jobagent --from-cv my_cv.pdf      # same, starting from what the CV says
```

`--setup` asks for each field with the current value in brackets (Enter keeps it, `-` clears it), then loops over
skills, certificates, jobs with their bullets, education and languages. Invalid answers such as a bad email,
negative years or a date that isn't `YYYY-MM` are asked again. If a `profile.yaml` already exists (version 1 or 2)
it is the starting point, so this is also how you upgrade a v1 file. At the end it prints the YAML and asks
`Write profile.yaml? [y/N]` (or `Overwrite the existing profile.yaml?` if there is one). That is the only
confirmation. Nothing is written without that `y`. The new file is written to a temporary file and swapped in, and
the old one is kept as `profile.yaml.bak-YYYYMMDD-HHMMSS`; earlier backups are never overwritten. If the disk
refuses the write (a file locked by OneDrive, for example) your answers are saved to `profile.yaml.new`. Ctrl+C
cancels with nothing written. If a draft fact fails validation at the end it is dropped and listed, and the rest
is kept. Old `degree`, `english` and `spanish` keys are removed from the new file once they are facts.

`--setup` rewrites the file from the answers, so comments in an existing `profile.yaml` are not preserved.
`profile.yaml` and its backups contain personal data: keep them out of synced or shared folders, or restrict who
can read them. `.gitignore` already covers `profile.yaml`, `*.bak*` and `profile.yaml.new`.

`--from-cv` reads a `.pdf`, `.docx` or `.txt`. Email, phone, LinkedIn and GitHub come from regular expressions.
Limits: files over 5 MB are refused, a `.docx` is refused if it is over 50 MB once unzipped, and a PDF may have at
most 30 pages. Only the first 20000 characters go to the model, and the log says when the text was cut. Scanned
PDFs are not supported (there is no OCR): a file with no text stops with "no text found". Encrypted or damaged
files stop with a one-line message.

The CV text is also sent to the configured LLM backend (using `llm.form_model`) to propose facts. Before that,
emails, phone numbers and lines about IDs, bank data or birth dates are replaced with placeholders, and you are
asked `Send CV text to the LLM backend <name>? ... [y/N]`; the question says that your name and links are still
sent. `--yes` skips the question and
`--no-llm` skips the LLM step; both options need `--from-cv`. The CV is merged into your existing
`profile.yaml`: your values, fixed answers, screening rules and facts are kept, and the CV only fills what is
missing and adds new facts. The model must give each fact with a quote from the
CV. A fact is kept only if the quote is in the CV text and contains the fact's name (whole words, so `C` does not
match `chemistry` or `C++`). Every number or date the model claims, such as years, a year, start and end dates or a
language level, must also be in the quote; one that is not is left out, logged as `unverified`, and the rest of the
fact is kept. A years value must be a number from 0 to 60 written next to `year`, `years`, `yr`, `yrs` or `años`
in the quote (`5 years`, `5+ años`, `years: 5`); calendar years and counts such as `12 projects` are not years.
Quotes must match at word boundaries, so `Java 5 years` is not backed by `RxJava 5 years`. Bullets are stored as the CV's own words, not the model's paraphrase. Facts dropped are counted in the
log by reason (not backed by the CV, or invalid).

CV text is untrusted like a job posting: if it looks like a prompt injection the LLM step is skipped and you are
told. The text extractors read everything in the file, including white text on a white background and other hidden
text, so anyone who can edit your CV can plant words in the draft. The result is only a draft for the questions:
check every field. A quote proves the CV says something, not that the model read the number right.

## Tests

```bash
pip install -e ".[dev,cv]"
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
`llm.prices_usd_per_mtok` (aliases go through `llm.api_models` first, and with the `api` backend a model
without a price is a configuration error, not a free call; with `claude` the CLI reports the cost, and a model
without a price counts as $0 with one warning, but still counts toward `max_calls_per_run`). The budget is checked before every call and after it: the run stops when the
estimate passes `llm.max_cost_usd_per_run` (default 1.0) or the number of calls reaches `llm.max_calls_per_run`
(default 300). Set either one to `null` to turn that limit off. With the `claude` backend the cost comes from the
CLI's own report, or from the prompt size if the CLI prints plain text. Nested settings such as `api_models` are
merged with the defaults, so you only list what you change. Update the model IDs and prices when they change.

Errors are not all treated the same:

| Error | What happens |
|---|---|
| Bad or missing credentials (401, 403), unknown model (404), missing SDK or `claude` command, unpriced model | `ConfigError`: the whole run stops, with the reason in the log |
| Over budget or over the call cap | The whole run stops |
| Rate limit, 5xx, network failure, timeout | Logged with the status code. The offer counts as an LLM failure, and three in a row stop the run |
| Bad request (400) | Logged, not retried, counted as an LLM failure |
| The model refuses, or its reply is not valid JSON | Logged, the offer is skipped |

The optional test `JOBAGENT_LIVE_API=1 pytest tests/test_live_api.py` makes one tiny real call per model alias to
check the SDK parameter names. It never runs in CI.

## Prompt-injection defense

Job postings and form labels are written by third parties and end up in the prompt. Three layers limit the damage:

1. **Detector.** Before any LLM call, the posting goes through `looks_injected` (`jobagent/safety.py`). It looks
   for phrases like "ignore previous instructions" (English and Spanish), "system prompt", "you are now", role
   markers (`assistant:`, `### system`, or `system:` followed by an instruction), requests to score the candidate 10,
   `"fit": 10`, fake `<job_posting>` tags and zero-width characters. Text is normalised first (NFKC, format
   characters removed), so fullwidth letters and invisible characters in the middle of a word don't hide a phrase.
   A hit skips the offer, adds a "To apply" row with the reasons in Notes, and makes no LLM call. The same check
   runs on every form field's label, context and options: one hit sends the whole form to manual review with no
   LLM call. It is a tripwire for obvious attacks and will miss a careful one.
2. **Data framing.** The posting is wrapped in `<job_posting>` and the form fields in `<form_fields>` and CV text in `<cv>`, and the
   prompt says that text inside those tags is data, never instructions. Any tag of that name inside the
   text (opening or closing, any case, spaces, fullwidth brackets) is rewritten so it can't end the block early.
   The offer URL and board name go inside the wrapped block too.
3. **Output validation.** Whatever the model returns is checked before use. A score must be an integer from 1 to
   10, and the CV name must be one of the configured files. Form answers are kept only for field ids that
   exist, values must be plain strings, numbers or booleans, and text is capped at 200 characters (2000 for
   text areas). For a select or radio, the model's value is first
   resolved to the exact option that will be filled (the option must equal it, start with it or contain it as whole
   words; two candidates, such as `Yes` against `Yes, 5+ years` and `Yes, less than 2 years`, count as no match), and
   every check below runs on that option. A years-of-experience answer (also one read from the cache, and also in
   select, radio and checkbox fields) is rejected if it is above the limit of the question: the profile's years for
   the skill it names, 0 when it names something that is not in the profile, or the profile's best skill when it
   names nothing. For a number or text answer the largest number counts ("5+" is 5, "5-7" is 7); for an option its
   own lower bound counts ("3-5" is 3, "Less than 1" is 0, "Más de 3" is 3). A rejected field is left for you to
   fill in by hand. A select counts as a years question when its options contain years (`5+ years`). An option
   is a yes when its first word is yes/y/sí/si/true (or a checked checkbox) and a no when it is no/none/ninguno/
   ninguna/false. A yes, or an option that is neither, claims the number in its own text (`Yes, 5+ years`) or,
   if it has none, the question's threshold (`at least 5 years`, "more than N" needs N+1), and is rejected above
   the limit. If the question names technologies (`2+ years with Python and Kubernetes`) or asks for experience
   with something, every one must be a profile skill with at least those years. A no is accepted only when its
   text has no number. A cached answer with no number is dropped.
   With facts in the profile,
   a years-of-experience answer must also cite the skill fact it relies on (see
   [Profile and facts](#profile-and-facts)). A score whose CV name isn't one of the configured files is rejected too.

**Sensitive fields.** A field asking for a government or national ID, passport, SSN, IBAN or bank account,
routing number, credit card, password or date of birth is never answered by the model and never read from the
learned-answers cache. It gets an answer only from an explicit rule in `fixed_answers`; otherwise a required one
sends the application to manual review and an optional one is left empty. Keys of that kind are also removed from
the profile text sent in the form prompt, so put such a value in `fixed_answers` only if you want it filled in.

The model also runs with no tools, so a successful injection can change a score or a form answer but can't run
anything. Only put in `profile.yaml` what you would be fine sharing with an employer, since form answers are
built from it. Screenshots and diagnostics in `data/` can contain your filled-in data; they stay local and are
git-ignored.

## Stopping a run (data/STOP)

Create an empty file named `STOP` in the data folder (`data/STOP` by default) and the run stops. It is checked
when the run starts, before every offer, about once a second during the pauses between steps, and right before
each final submit, so a run that is waiting or filling a form stops without sending. If the file can't be checked
(permissions, disk error) the run also stops. The log says `STOP file found; delete it to run again`. The agent
never deletes the file, so it keeps blocking runs until you remove it.

```bash
touch data/STOP     # stop
rm data/STOP        # allow runs again
```

## Evals

```bash
python -m jobagent --eval           # offline, fake backend, exit code 1 if any case fails
python -m jobagent --eval --live    # sends the cases to the configured backend and measures the model
```

`--eval` reads the cases from the `evals/` folder, so it runs from a source checkout (`pip install -e .`), not from
an installed wheel. If the folder is missing or empty it stops with an error.

The cases are YAML files in `evals/`: `fit.yaml` (offers the candidate should score high or low on, and which
CV to pick), `honesty.yaml` (form answers must come from the profile and cite its facts, not from the model's imagination) and
`injection.yaml` (postings that try to steer the scorer, in English and Spanish, with zero-width characters).
Injection cases marked `bypass_detector: true` skip the detector and go straight to the scorer, which has to
keep its score in range anyway.

The offline pass rates below test the pipeline around the model (the detector, validation, length caps and the
years check) with a deterministic fake. The fake behaves like an honest model, so passing offline says nothing
about how a real model behaves. `--live` is the run that measures the model, and it costs tokens. It skips the
cases that force a model reply (they only make sense offline) and says how many. It exits with 1 if the overall
pass rate is under `evals.live_min_pass_rate` (default 0.9), if nothing ran, or if the budget ran out; in that last
case the report still lists what was measured. Each run writes `data/evals/report-YYYYMMDD-HHMMSS.json` and `.md`:

| Suite | Passed | Total | Pass rate |
|---|---|---|---|
| fit | 7 | 7 | 100% |
| honesty | 38 | 38 | 100% |
| injection | 10 | 10 | 100% |

The tests check that the evals can fail: with a fake that always answers fit 10, the fit and injection suites
report failures.

## Use it responsibly

Automating applications can break a job board's terms of service and can get your account restricted. This
project does not try to hide that it is automated. Keep the daily limits low, check the dry run first, and use it
at your own risk.

## Roadmap

- [x] Tests with local HTML fixtures and a fake LLM, CI on Windows and Linux, secret scanning
- [x] Profile v2 with citable facts, and profile setup from your existing CV (`--setup`, `--from-cv`)
- [ ] ATS-friendly CV generator (PDF/DOCX, English/Spanish), tailored per offer without adding facts
- [x] Demo mode with a fake local job board, runnable without accounts
- [x] Prompt-injection defense, STOP switch, API backend with cost budget, and LLM evals for honesty
- [ ] SQLite state machine, funnel report and human-approval dashboard
- [ ] Docker image

## License

MIT
