# Personal Finance Tool

A local-first, open source long-term financial planner, in the spirit of
[ProjectionLab](https://projectionlab.com/) and [Boldin](https://www.boldin.com/).
Your data lives in a SQLite file on your own machine.

## Features

- **Accounts & net worth** — cash, brokerage, retirement (taxable / tax-deferred / tax-free),
  property, and debts. Record balances over time and see net worth history and asset allocation.
- **Bank sync (optional)** — link institutions through [Plaid](https://plaid.com/) to pull
  balances, investment holdings (with cost basis), and loan/credit-card rates automatically.
- **CSV import/export** — import balance history from a spreadsheet (`date, account, balance`,
  optionally `kind, tax_treatment`); new account names are created. Export everything the same way.
- **Backup & restore** — download every account, balance, and plan as one JSON file, and restore
  it on another computer (Plaid links aren't included; reconnect after restoring).
- **Lifetime plan** — enter income and one-time goals by age (salary until retirement, a pension,
  a house down payment at 38…). The plan projects every year to your life expectancy using your
  real account balances.
- **Spending your way** — one "General spending" bucket, or break it into categories (housing,
  home maintenance, utilities, cars, healthcare, travel, hobbies…). Items can repeat every N years
  (a car every 8 years) and grow faster than inflation (healthcare). A stacked chart shows
  spending by category over your lifetime.
- **Kids** — each child's yearly cost changes by life stage (0–5 with childcare, 6–12, 13–17),
  then optional college years. Future children work too.
- **Taxes** — 2026 federal brackets and standard deduction (single or married filing jointly),
  payroll tax on wages, Social Security benefit taxation, long-term capital gains (0/15/20%) and
  the 3.8% net investment income tax, a flat state rate, the 10% penalty on 401k/IRA withdrawals
  before 59½, and required minimum distributions. A single flat rate is available instead.
- **Roth conversions** — convert 401k/IRA money up to the top of a chosen bracket each year
  (by default from retirement until RMDs start). **Explore strategies** compares no conversions
  with filling the 12/22/24/32% brackets on lifetime taxes and after-tax money left.
- **Social Security** — enter your benefit at full retirement age from your ssa.gov statement
  (and your spouse's); benefits are adjusted for claiming age 62–70. A lower-earning spouse gets
  the spousal benefit (up to half the partner's) when larger. **Compare claiming ages** reruns the
  whole plan for each age to find the one that best supports your plan.
- **Couples and survivors** — each spouse has their own retirement age. Income and spending items
  belong to you, your spouse, or the household: a spouse's items use the spouse's ages and
  retirement, and personal items stop at that person's death. Account contributions stop when the
  account owner retires. The plan runs until the second death; after the first, the survivor keeps
  the larger Social Security benefit, files as single, and spending drops to a share you set.
- **Healthcare in retirement** — per-person costs for private insurance from retirement until
  Medicare at 65, then Medicare-era costs, rising faster than inflation. Medicare IRMAA
  surcharges are added automatically from your income two years earlier.
- **When can you retire?** — reruns the plan for retirement ages around your choice and finds the
  earliest age that reaches an 85% chance of success.
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
  then tax-deferred (grossed up so the after-tax amount covers the gap), then tax-free. If
  everything is empty, the plan fails.
- Tax brackets and the standard deduction rise with inflation. Taxable accounts track cost
  basis (set it per account, or Plaid fills it from holdings): selling realizes the gain share
  of each withdrawal, taxed at long-term rates stacked on top of ordinary income. Account
  contributions (set per account) stop at retirement; tax-deferred contributions reduce taxable
  wages.
- "After tax" ending wealth counts 401k/IRA money net of a 22% tax your heirs would owe and
  unrealized gains net of 15%, so strategies that pay tax earlier compare fairly.
- Kids' stage costs default to rough US averages; edit them to match your situation.
- Simplifications for couples: accounts are pooled; after a death, RMDs use the survivor's age;
  the survivor benefit is the deceased's benefit as claimed (no reduction for the survivor
  claiming early); joint items continue for the survivor. Investment returns switch to the
  retirement return when the first of you retires.
- Investments follow a stock/bond mix that glides in a straight line from today's allocation to
  your retirement allocation, reached when the first of you retires. Monte Carlo draws correlated
  yearly stock and bond returns from normal distributions. A simpler model with one return
  before and one after retirement is available under Assumptions. It is a planning aid, not a
  prediction.
- Homes: your home now (optionally linked to its property and mortgage accounts, so they are not
  counted twice), one you plan to buy (down payment and closing costs from savings, then a
  mortgage), and sales or downsizing. Values grow at inflation plus your appreciation rate.
  Carrying costs are added to housing spending. Sale proceeds go to savings, and gains above the
  $250k/$500k home-sale exclusion are taxed as capital gains.
- Choosing a state applies its 2026 brackets, standard deduction, and personal exemptions (from
  the [Tax Foundation](https://taxfoundation.org/data/all/state/state-income-tax-rates-2026/)). It
  also applies Social Security taxation in the eight states that still tax benefits, full or
  partial 401k/IRA exclusions (IL, IA, MS, PA, GA, NY), and the special cases of Washington
  (capital gains only) and Missouri (no capital gains tax). Local taxes, phaseouts, and other
  partial pension exclusions are not modeled. Without a state, a flat rate applies to federal
  taxable income.
- Before Medicare, ACA marketplace premium tax credits are applied each year from household
  income (AGI plus all Social Security) and a benchmark silver premium you set, under the 2026
  rules: IRS Rev. Proc. 2025-25 percentages and no credit above 400% of the poverty line. Below
  100% of the poverty line the model assumes the cheapest band rather than Medicaid.
- Optional Guyton-Klinger spending guardrails: once everyone is retired, flexible spending is cut
  10% when the withdrawal rate rises 20% above where it started (except in the final 15 years) and
  raised 10% when it falls 20% below, never below a floor you choose. Housing, utilities,
  insurance, healthcare, kids, and education are never cut.
- The historical backtest replays the plan through every complete stretch of actual US returns
  since 1928 (S&P 500 and 10-year Treasuries, from
  [Damodaran, NYU Stern](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html)).
  Each year's real return is kept, while spending still grows at your assumed inflation rate.
  Refresh the data with `scripts/update_historical_returns.py`.

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

State tax brackets, ACA premium subsidies before Medicare, historical-returns backtesting,
transaction-based budgeting, and encrypting the local database.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). CI runs tests and lint on every push and pull request.

## License

To be decided.
