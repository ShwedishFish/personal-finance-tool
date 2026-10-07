# Personal Finance Tool

A local-first, open source long-term financial planner, in the spirit of
[ProjectionLab](https://projectionlab.com/) and [Boldin](https://www.boldin.com/).
Your data lives in a SQLite file on your own machine.

## Features

- **Accounts & net worth** — cash, brokerage, retirement (taxable / tax-deferred / tax-free),
  property, and debts. Record balances over time and see net worth history and asset allocation.
- **Bank sync (optional)** — link institutions through [Plaid](https://plaid.com/) to pull
  balances, investment holdings, and loan/credit-card rates automatically.
- **Lifetime plan** — enter income, expenses, and one-time goals by age (salary until retirement,
  Social Security from 67, a house down payment at 38…). The plan projects every year to your
  life expectancy using your real account balances.
- **Chance of success** — Monte Carlo simulation of market returns gives the probability your
  money lasts, with percentile bands.
- **FI number & FI age** — when investable assets reach retirement spending ÷ safe withdrawal rate.
- **Scenarios** — duplicate a plan, change assumptions (retire at 55? spend more?), and compare.
- **Debt payoff** — avalanche vs. snowball with extra monthly payments.

## Quick start

Requires Python 3.11+ (the script uses [uv](https://docs.astral.sh/uv/) if installed).

```bash
./scripts/dev.sh
```

Then open <http://127.0.0.1:8020/>. In Cursor/VS Code, **Run Build Task** (⇧⌘B) runs
**Personal Finance: Dev Server + Simple Browser**.

Run tests with `.venv/bin/python -m pytest`.

## Connecting banks with Plaid

1. Create a free account at <https://dashboard.plaid.com/> and copy your sandbox keys.
2. `cp .env.example .env` and fill in `PLAID_CLIENT_ID` and `PLAID_SECRET`.
3. Restart the server, go to **Accounts → Connect institution**. In sandbox, log in with
   `user_good` / `pass_good`.

For real accounts, request Production access in the Plaid dashboard and set `PLAID_ENV=production`.
Plaid access tokens are stored in your local database (`data/finance.db`), which is gitignored —
treat that file as sensitive.

## How the projection works

- All inputs are in **today's dollars**. Each year, flows are inflated, then:
  income − taxes − expenses − goals − debt payments − planned contributions = net cash flow.
- Surpluses are invested in the taxable bucket. Shortfalls are withdrawn from cash, then taxable,
  then tax-deferred (grossed up for taxes), then tax-free. If everything is empty, the plan fails.
- Taxes use a single effective rate. Account contributions (set per account) stop at retirement.
- Monte Carlo draws yearly returns from a normal distribution (mean = your expected return,
  std. dev. = volatility). It is a planning aid, not a prediction.

## Project layout

```
backend/app/
  finance/      pure calculation code (projection, Monte Carlo, debt, net worth)
  routers/      FastAPI endpoints
  plaid_*.py    Plaid client wrapper and account sync
frontend/       static HTML/JS/CSS (no build step)
tests/
```

## Roadmap ideas

Progressive tax brackets, Social Security claiming-age optimizer, Roth conversion explorer,
required minimum distributions, historical-returns backtesting, CSV import, transaction-based
budgeting, and encrypting the local database.

## License

To be decided.
