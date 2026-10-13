# pesa-tracker

A personal money tracker for everyday life in Kenya: amounts in KES, M-Pesa built in.
Use it from the command line or through a local web dashboard.
Pure Python standard library, no dependencies to install.

## Features

- **Expenses, income and transfers** across several accounts (M-Pesa, bank, cash, savings)
  with running balances
- **Monthly budgets** per category, with a heads-up at 80% and a warning when you go over
- **Recurring items** such as rent and salary, added automatically when they fall due
  (missed months are caught up)
- **M-Pesa support**: paste confirmation SMS messages or import a statement CSV;
  categories are guessed, transaction fees are recorded, and nothing is imported twice
- **Savings goals** with progress and how much to save per month to hit a deadline
- **Reports**: cash flow over several months, top categories, month-over-month change
- **Web dashboard**: balances, budget bars, SVG charts, and a transactions page with
  search, filters, add, edit, delete and an M-Pesa paste box. Works on phones and in dark mode
- **Runs online and links to M-Pesa**: host it free on PythonAnywhere behind a password,
  and an SMS-forwarding app on your Android phone sends every M-Pesa message to it.
  See **[DEPLOY.md](DEPLOY.md)**
- **CSV export** for Excel or Google Sheets
- Data lives in a single SQLite file on your machine

## Requirements

- Python 3.10+

## Quick start

Run commands from the project folder:

```bash
python -m pesa add 350 transport -n "matatu to town"
python -m pesa income 42000 salary
python -m pesa summary
python -m pesa serve          # opens the dashboard at http://127.0.0.1:8765/
```

## Command reference

### Recording money

```bash
python -m pesa add 1200 food -d 2026-10-01 -n "Naivas"     # expense (date defaults to today)
python -m pesa income 5000 freelance -a mpesa                # money in
python -m pesa transfer 2000 equity mpesa -n "top up"        # between your own accounts
python -m pesa edit 3 --amount 650 -n "supper"
python -m pesa delete 3
```

`-a/--account` picks the account; the default is `mpesa`.

### Looking at it

```bash
python -m pesa list                                  # everything
python -m pesa list --since 2026-10-01 -k expense -c food
python -m pesa list -a equity -s rent                # by account, search notes
python -m pesa summary -m 2026-09                    # income, spending, net, categories
python -m pesa report --months 6                     # cash flow + changes vs last month
```

### Accounts

```bash
python -m pesa account add equity --kind bank --opening 18000
python -m pesa account                               # balances
```

### Budgets

```bash
python -m pesa budget set food 8000
python -m pesa budget                                # spent vs limit this month
python -m pesa budget remove food
```

### Recurring items

```bash
python -m pesa recurring add expense 14000 rent --day 5 -a equity
python -m pesa recurring add income 42000 salary --day 28 -a equity
python -m pesa recurring                             # list, with next dates
python -m pesa recurring remove 1
```

Due items are added the next time you run any command (or start the dashboard).
A day of 31 means "the last day" in shorter months.

### Savings goals

```bash
python -m pesa goal add laptop 65000 --deadline 2027-04-01
python -m pesa goal save laptop 5000                 # negative amounts take money out
python -m pesa goal                                  # progress bars
```

### M-Pesa

Paste confirmation messages straight in (several at once is fine), or put them in a file:

```bash
python -m pesa sms "SJA1B2C3D5 Confirmed. Ksh1,250.00 paid to NAIVAS SUPERMARKET. on 1/10/26 at 12:40 PM ..."
python -m pesa sms --file messages.txt
```

Recognised: buy goods / till, send money, pay bill, airtime, agent withdrawal and money
received (recorded as income). The transaction cost becomes a separate `fees` expense.

Or import a statement exported as CSV (columns `Receipt No.`, `Completion Time`,
`Details`, `Transaction Status`, `Withdrawn`):

```bash
python -m pesa import statement.csv --dry-run        # preview
python -m pesa import statement.csv
```

Receipt numbers are stored, so the same message or statement row is never counted twice.

### Export

```bash
python -m pesa export -o october.csv -m 2026-10
```

## Web dashboard

```bash
python -m pesa serve                  # add --port 9000 or --no-browser if you like
```

- **Dashboard**: income, spending and net for the chosen month, account balances,
  budget bars (amber from 80%, red when over), spending by category, six-month cash flow
  and savings goals
- **Transactions**: add, edit and delete expenses, income and transfers; search notes and
  filter by type, category, account and date range

By default the server only listens on `127.0.0.1`, so other machines can't reach it.
Set `PESA_PASSWORD` to require a login, and `PESA_SMS_TOKEN` to turn on the SMS webhook.
To host it online, see [DEPLOY.md](DEPLOY.md).

### JSON API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/summary?month=YYYY-MM` | totals, categories with budgets, balances, goals |
| GET | `/api/cashflow?month=YYYY-MM&months=6` | income / spending / net per month |
| GET | `/api/transactions?q=&kind=&category=&account=&since=&until=` | newest first |
| POST | `/api/transactions` | `{kind, amount, category, account, to_account, date, note}` |
| GET / PUT / DELETE | `/api/transactions/<id>` | PUT accepts any subset of the fields |
| GET | `/api/accounts` | balances |
| GET | `/api/categories` | used categories plus budgeted ones |
| POST | `/api/sms/paste` | `{text}`: record pasted M-Pesa messages |
| POST | `/api/sms?token=…` | webhook for the phone; token auth, takes JSON `{text}`, a form, or plain text |

With a password set, every `/api/*` call except the webhook needs the login cookie.
POST and PUT bodies must be JSON. Errors come back as `{"error": "..."}` with status
400, 401, 404 or 415.

## Where data is stored

`~/.pesa/pesa.db` by default. Use `--db path/to/file.db` or the `PESA_DB` environment
variable to change it. If you used version 0.1 (JSON files), your expenses and budgets
are moved into the database automatically the first time you run the new version.

## Project layout

```
pesa/
  cli.py       command-line interface
  db.py        SQLite ledger: transactions, accounts, budgets, recurring, goals
  models.py    Transaction model and validation
  mpesa.py     M-Pesa statement CSV import
  sms.py       M-Pesa SMS parsing
  reports.py   cash flow and comparisons
  web.py       web app: dashboard, JSON API, login, SMS webhook, local server
  wsgi.py      entry point for hosting (PythonAnywhere, gunicorn)
  static/      dashboard and login pages (HTML, CSS, vanilla JS)
tests/         unittest suite (91 tests)
```

## Running the tests

```bash
python -m unittest discover -s tests -t .
```
