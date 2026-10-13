# pesa-tracker

A small command-line expense tracker for everyday spending in Kenyan shillings (KES).
Pure Python, no dependencies.

## Features

- Record, list, edit and delete expenses
- Monthly summary per category with percentage share
- Monthly budgets per category, with a heads-up at 80% and a warning when you go over
- Import spending straight from an M-Pesa statement CSV (duplicates are skipped)
- Export to CSV for Excel / Google Sheets

## Requirements

- Python 3.10+

## Usage

Run commands from the project folder with `python -m pesa`.

```bash
# record spending (date defaults to today)
python -m pesa add 350 transport -n "matatu to town"
python -m pesa add 1200 food -d 2026-10-01

# see what you spent
python -m pesa list
python -m pesa list --since 2026-10-01 -c food
python -m pesa summary              # this month
python -m pesa summary -m 2026-09   # a past month

# fix mistakes
python -m pesa edit 3 -a 650 -n "supper"
python -m pesa delete 1
```

Example summary:

```
Spending for 2026-10

  cash             KES 2,000.00   43.0%
  shopping         KES 1,250.00   26.9%   budget KES 1,000.00 (125%)  OVER
  transfers          KES 800.00   17.2%
  bills              KES 500.00   10.7%

  total            KES 4,550.00
```

### Budgets

```bash
python -m pesa budget set food 8000
python -m pesa budget            # spent vs limit for this month
python -m pesa budget remove food
```

### M-Pesa statements

Export your statement as CSV with the usual columns
(`Receipt No.`, `Completion Time`, `Details`, `Transaction Status`, `Withdrawn`), then:

```bash
python -m pesa import statement.csv --dry-run   # preview
python -m pesa import statement.csv
```

Only completed money-out transactions are imported. Categories (airtime, bills, shopping,
cash, transfers, fees) are guessed from the details text, and importing the same
statement twice adds nothing new.

### Export

```bash
python -m pesa export -o october.csv -m 2026-10
```

## Where data is stored

By default in `~/.pesa/expenses.json` (budgets in `expenses.budgets.json` next to it).
Use `--file path/to/file.json` or the `PESA_FILE` environment variable to change it.

## Running the tests

```bash
python -m unittest discover -s tests -t .
```

## Roadmap

See [TODO.md](TODO.md): income and accounts, SQLite storage, recurring payments,
M-Pesa SMS parsing, savings goals and a local web dashboard are next.
