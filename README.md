# Personal Finance Tool

A local-first, open source long-term financial planner, in the spirit of
[ProjectionLab](https://projectionlab.com/) and [Boldin](https://www.boldin.com/).
It runs entirely on your own computer: there is no account to create, no server to sign up for,
and nothing about you is sent anywhere unless you choose to connect a bank (see
[Privacy](#security-and-privacy)).

## Features

- **Accounts & net worth** — cash, brokerage, retirement (taxable / tax-deferred / tax-free),
  property, and debts. Record balances over time and see net worth history and asset allocation.
- **Bank sync (optional)** — link institutions through [Plaid](https://plaid.com/) to pull
  balances, transactions, investment holdings (with cost basis), and loan/credit-card rates automatically.
- **CSV import/export** — import balance history from a spreadsheet (`date, account, balance`,
  optionally `kind, tax_treatment`); new account names are created. Export everything the same way.
- **Actual vs. planned spending** — transactions from Plaid, or a bank's CSV export (`date,
  description, amount`, optionally `account, category`), are categorized and averaged over complete
  months, then shown per year beside this year of your plan. Recategorize a transaction and the app
  can remember it for that merchant. Transfers, debt payments, income, and taxes are left out
  because the plan models them separately. Re-importing a file skips rows already imported.
- **Backup & restore** — download every account, balance, plan, and transaction as one JSON file, and restore
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

## Download and run

1. Install [Python 3.11 or newer](https://www.python.org/downloads/) if you don't have it.
2. Download the latest release (**Code → Download ZIP**, or a zip under **Releases**) and unzip it.
3. Double-click **Start Personal Finance.command** (macOS) or **Start Personal Finance.bat**
   (Windows). The first start takes a minute to install; then your browser opens the app at
   <http://127.0.0.1:8020/>. Close the window to stop it.

On macOS, if you see "cannot be opened because it is from an unidentified developer",
right-click the file, choose **Open**, then **Open** again (only needed once).

## Quick start for developers

Requires Python 3.11+ (the script uses [uv](https://docs.astral.sh/uv/) if installed).

```bash
./scripts/dev.sh
```

Then open <http://127.0.0.1:8020/>. In Cursor/VS Code, **Run Build Task** (⇧⌘B) runs
**Personal Finance: Dev Server + Simple Browser**.

Run tests with `.venv/bin/python -m pytest`.

### Keep it running (macOS)

```bash
./scripts/launch-agent.sh install     # start now and at every login; restarts if it stops
./scripts/launch-agent.sh status
./scripts/launch-agent.sh uninstall
```

The app then stays at <http://127.0.0.1:8020/> without a terminal (log in `data/logs/server.log`).
Because background processes can't read folders like Documents on their own, the script adds a
small hidden app, **Personal Finance Tool Server**, to `~/Applications`; the first time it starts,
macOS asks whether it may access the folder this repo is in, so click **Allow**. Stop the dev
server before installing. Afterwards ⇧⌘B just opens the browser, since the app is already
running. It serves the code as of its last start, so after pulling changes run `install` again.

## Connecting banks with Plaid

1. Create a free account at <https://dashboard.plaid.com/> and copy your sandbox keys.
2. `cp .env.example .env` and fill in `PLAID_CLIENT_ID` and `PLAID_SECRET`.
3. Restart the server, go to **Accounts → Connect institution**. In sandbox, log in with
   `user_good` / `pass_good`.

For real accounts, request Production access in the Plaid dashboard and set `PLAID_ENV=production`.
Plaid access tokens are encrypted in the local database (see below).

## Security and privacy

**What leaves your computer:** nothing, unless you connect a bank. There is no analytics,
tracking, telemetry, or cloud sync, and every script the app uses (including the chart library)
ships in this repo. The app sets a Content Security Policy that tells the browser it may only contact the app
itself and Plaid, so even a bug couldn't quietly send your data to another site.

**If you connect a bank:** Plaid is used with *your own* Plaid keys, so the connection is between
you, your bank, and Plaid; this project's author never sees it. You log in to your bank inside
Plaid's window, and the app downloads balances, holdings, and transactions from Plaid to your
computer. See [Plaid's privacy policy](https://plaid.com/legal/#end-user-privacy-policy). CSV
import and manual entry work without any of this.

- Everything stays on your computer in `data/finance.db` (gitignored, readable only by your user).
  Turn on FileVault (or your OS's disk encryption) so the database is encrypted on disk.
- Plaid access tokens are encrypted with a key kept outside the database: in the macOS Keychain
  (or Windows Credential Manager / Linux Secret Service), else `~/.config/personal-finance-tool/secret.key`,
  or the `PFT_SECRET_KEY` environment variable if set. If the key is lost, only the bank links are
  affected: remove and reconnect those institutions.
- **Optional password** (Accounts → Security): require signing in before the browser can read
  anything. It protects against someone using your unlocked computer; it doesn't encrypt the data,
  so forgetting it loses nothing: double-click `scripts/reset-password.command` (macOS) or
  `scripts/reset-password.bat` (Windows).
- The server listens only on 127.0.0.1 and rejects requests whose `Host` isn't `127.0.0.1` or
  `localhost`, so web pages can't read it through DNS rebinding. To reach it under another name
  (for example behind your own reverse proxy), list it in `PFT_ALLOWED_HOSTS`.

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
  transactions.py  transaction categorizing, CSV import, and actual-vs-plan summary
  auth.py, crypto.py  optional app password; encryption of stored secrets
frontend/       static HTML/JS/CSS (no build step)
tests/
```

## Roadmap ideas

Budgets and alerts from transactions, local tax-lot tracking, and more state-specific rules
(local income taxes, state estate taxes).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). CI runs tests and lint on every push and pull request.

## License

[MIT](LICENSE). Chart.js (`frontend/vendor/chart.umd.min.js`) is also MIT licensed.
