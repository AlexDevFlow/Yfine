# Yfine (v2)

A private, local personal-finance app — rebuilt as a small **native desktop app**
(Tauri 2 + React + TypeScript) talking directly to **SQLite**. No cloud, no accounts,
no telemetry, no Python runtime to ship.

This is the ground-up rewrite of the original FastAPI/Jinja Yfine. It keeps the
**exact same SQLite schema**, so an existing `yfine.db` (or an encrypted `yfine.db.enc`)
migrates unchanged.

## What's inside

- **Dashboard** — net worth per currency (+ optional consolidated total), this-month
  in/out/saved, monthly-flow chart, recent movements, and a **90-day cashflow forecast**.
- **Sources** — multi-currency accounts with derived balances, savings funds, periodic yield.
- **Movements** — in/out, cross-currency transfers, **split transactions**, filters,
  grouped by day, **bulk edit** (delete/move).
- **Recurring** — auto/confirm schedules with a background reconciliation on launch.
- **Budgets / Goals / Whims** — tag budgets with rollover, savings goals (allocate/refund),
  prioritised wishlist with save-for-this.
- **Portfolios** — holdings, manual prices, FX-correct valuation.
- **Data** — `.yfine`/JSON backup & restore, CSV bank import (Revolut/N26/YNAB/PayPal/Firefly),
  CSV export.
- **Security** — optional password with AES-256-GCM at-rest encryption (PBKDF2; reads
  legacy Fernet archives) — opens an existing encrypted DB.
- Light/dark themes, four languages (en/it/es/uk), ⌘K command palette.

## Develop

```bash
cd yfine2
pnpm install
pnpm dev            # runs in the browser at http://localhost:1420 (seeded in-memory sql.js DB)
pnpm tauri dev      # the real native window (SQLite on disk); first run compiles Rust
pnpm test           # vitest (domain + repositories, run against in-memory SQLite)
pnpm typecheck
```

The browser preview uses an in-memory **sql.js** database seeded with sample data so the
whole UI is explorable without the native runtime. The packaged app uses native SQLite.

## Build installers

```bash
cd yfine2
pnpm tauri build    # .AppImage/.deb (Linux), .dmg (macOS), .msi (Windows) in src-tauri/target/release/bundle
```

CI (`.github/workflows/release.yml`) builds all three on `v*` tag push. No code signing
(local-use builds — see project notes).

## Migrating an existing database

Point the app at your existing `yfine.db`/`yfine.db.enc` (the app's data dir). The
drift-tolerant migrator creates any missing tables/columns additively and never drops
data; unknown/plugin tables are preserved. Encrypted DBs prompt for the password on launch.
