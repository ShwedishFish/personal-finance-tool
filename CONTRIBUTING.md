# Contributing

Thanks for helping. This is a local-first planner: your financial data never leaves your machine,
and changes should keep it that way (no telemetry, no hosted services beyond optional Plaid).

## Setup

```bash
./scripts/dev.sh            # creates .venv, installs dependencies, serves http://127.0.0.1:8020
.venv/bin/python -m pytest  # tests
.venv/bin/python -m ruff check .
```

CI runs the same tests and lint on Python 3.11–3.13 for every pull request.

## Where things live

- `backend/app/finance/` — pure calculations (projection, taxes, Social Security, Medicare). No
  database or web code here, so it is easy to test. Put new math here with unit tests.
- `backend/app/services.py` — turns database rows into projection inputs.
- `backend/app/routers/` — FastAPI endpoints.
- `frontend/` — plain HTML/JS/CSS, no build step.

## Guidelines

- **Cite the source for tax and benefit numbers** (IRS, SSA, CMS) in the pull request, and say which
  year they are for. Thresholds live as named constants at the top of each module.
- **Inputs are in today's dollars**; the simulation inflates them. Keep that convention.
- **Add a test** for any behavior change in `finance/`; prefer small hand-checkable examples.
- **Schema changes**: add the column to `models.py` with a scalar default. `upgrade_schema` adds
  missing columns to existing databases automatically; anything more (renames, data moves) needs an
  explicit step there and a test in `tests/test_migrations.py`.
- Never commit `.env`, `data/`, or real financial data in fixtures.

## Reporting bugs

Open an issue with the plan settings needed to reproduce it (a backup file from **Accounts → Backup
& restore** with made-up numbers is ideal). Please remove anything real before sharing.
