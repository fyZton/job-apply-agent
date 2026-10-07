# job-apply-agent

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
- **No API key:** it calls Claude through the Claude Code CLI (`claude -p`) with tools disabled.

| Board | Status |
|---|---|
| LinkedIn (Easy Apply) | Working |
| Computrabajo Venezuela | Working |

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

## Use it responsibly

Automating applications can break a job board's terms of service and can get your account restricted. This
project does not try to hide that it is automated. Keep the daily limits low, check the dry run first, and use it
at your own risk.

Known limitation: job postings and form labels are written by third parties, and they go into the LLM prompt
together with your profile. A malicious form could try to make the LLM paste profile data into a field. The LLM
runs with no tools, so it can't execute anything, but until the prompt-injection phase on the roadmap is done,
only put in `profile.yaml` what you'd be fine sharing with an employer. Screenshots and diagnostics in `data/`
can contain your filled-in data; they stay local and are git-ignored.

## Roadmap

- [ ] Tests with local HTML fixtures and a fake LLM, CI on Windows and Linux, secret scanning
- [ ] Profile setup from your existing CV (`--setup`)
- [ ] ATS-friendly CV generator (PDF/DOCX, English/Spanish), tailored per offer without adding facts
- [ ] Demo mode with a fake local job board, runnable without accounts
- [ ] Prompt-injection defense and LLM evals for honesty
- [ ] SQLite state machine, funnel report and human-approval dashboard
- [ ] Docker image

## License

MIT
