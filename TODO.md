# pesa-tracker roadmap

Small personal expense tracker for the command line, amounts in KES.

- [x] Project skeleton: README, .gitignore, package layout
- [x] Expense model + JSON storage (add / load / save)
- [ ] `add` command (amount, category, note, date)
- [ ] `list` command with date filter
- [ ] Unit tests for storage and model
- [ ] `summary` command: totals per category for a month
- [ ] `delete` and `edit` by id
- [ ] Monthly budgets per category + over-budget warnings
- [ ] CSV export
- [ ] Import M-Pesa statement CSV
- [ ] Tests for summary, budgets, import
- [ ] Polish README with usage examples

## Phase 2 — full money tracker

- [ ] Track income as well as expenses (transaction type field + migration of old data)
- [ ] Accounts / wallets (M-Pesa, bank, cash) with running balances
- [ ] Transfers between accounts
- [ ] Move storage to SQLite (stdlib sqlite3) with a schema version table
- [ ] Recurring transactions (rent, subscriptions) generated automatically
- [ ] Parse M-Pesa confirmation SMS text into transactions
- [ ] Savings goals with progress tracking
- [ ] Reports: monthly cash flow, top categories, month-over-month change
- [ ] Tests for accounts, transfers, recurring, SMS parsing, reports

## Phase 3 — web dashboard

- [ ] Local web server (stdlib http.server) with a JSON API
- [ ] Dashboard page: balances, this month's spending, budget bars
- [ ] Add / edit / delete transactions from the browser
- [ ] Charts (spending by category, cash flow over time) with plain SVG
- [ ] Filters and search on the transactions page
- [ ] API tests
- [ ] Final README: screenshots, features, setup
