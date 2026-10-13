# pesa-tracker roadmap

Personal money tracker in KES: command line plus a local web dashboard.

## Phase 1 - command-line expense tracker

- [x] Project skeleton: README, .gitignore, package layout
- [x] Expense model + JSON storage (add / load / save)
- [x] `add` command (amount, category, note, date)
- [x] `list` command with date filter
- [x] Unit tests for storage and model
- [x] `summary` command: totals per category for a month
- [x] `delete` and `edit` by id
- [x] Monthly budgets per category + over-budget warnings
- [x] CSV export
- [x] Import M-Pesa statement CSV
- [x] Tests for summary, budgets, import
- [x] Polish README with usage examples

## Phase 2 - full money tracker

- [x] Track income as well as expenses (transaction type field + migration of old data)
- [x] Accounts / wallets (M-Pesa, bank, cash) with running balances
- [x] Transfers between accounts
- [x] Move storage to SQLite (stdlib sqlite3) with a schema version table
- [x] Recurring transactions (rent, subscriptions) generated automatically
- [x] Parse M-Pesa confirmation SMS text into transactions
- [x] Savings goals with progress tracking
- [x] Reports: monthly cash flow, top categories, month-over-month change
- [x] Tests for accounts, transfers, recurring, SMS parsing, reports

## Phase 3 - web dashboard

- [x] Local web server (stdlib http.server) with a JSON API
- [x] Dashboard page: balances, this month's spending, budget bars
- [x] Add / edit / delete transactions from the browser
- [x] Charts (spending by category, cash flow over time) with plain SVG
- [x] Filters and search on the transactions page
- [x] API tests
- [x] Final README: features, setup, API

## Ideas for later

- [ ] Screenshots of the dashboard in the README
- [ ] Manage budgets, goals and recurring items from the browser (CLI only for now)
- [ ] Package for `pip install` with a `pesa` console command
