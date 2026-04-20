# Autotrade

Autotrade is a research-first project for building an AI-assisted automated trading system with `Alpaca Paper` as the initial execution environment.

The goal of the first phase is not to maximize profit. It is to build a controlled, auditable, and reusable proof of concept that can:

- connect to Alpaca paper trading safely
- ingest market data
- generate trade decisions with explicit rules
- place simulated orders
- log every important action
- enforce strong risk and security controls

This repository starts with documentation so the implementation can follow a clear plan and later be shared publicly.

## Current Focus

Priority one is `Alpaca Paper`.

Why:

- no real-money exposure during early testing
- same general API shape as Alpaca live
- good fit for a 24-hour autonomous experiment
- easier to validate control logic before touching live capital

## Repository Layout

- `docs/research/` research papers, setup plans, and decision records
- `docs/setup/` onboarding guides and optional local-tool integration notes
- `docs/architecture/` technical design and component boundaries
- `docs/operations/` operational runbooks and security controls
- `src/` future implementation code
- `config/` environment examples and strategy configuration
- `config/investment-plan.paper.example.json` budget, reserve, and symbol preferences for paper runs
- `scripts/` future helper scripts for setup, reporting, and runs
- `tests/` automated tests

## Recommended Reading Order

1. `docs/research/alpaca-paper-build-plan.md`
2. `docs/research/published-resources.md`
3. `docs/research/strategy-categories.md`
4. `docs/setup/mcp-onboarding.md`
5. `docs/architecture/system-design.md`
6. `docs/operations/security-controls.md`
7. `docs/operations/runbook.md`

## Planned Phases

1. Research and structure
2. Broker connectivity in paper mode
3. Strategy engine and risk manager
4. Audit logging and reporting
5. End-to-end paper experiment
6. Readiness review for Alpaca live

## Status

This repository currently contains the foundational research and project structure for the `Alpaca Paper` phase.

## Local Setup

The repository now includes a basic Python scaffold for the first implementation pass.

Suggested local workflow:

1. Create or activate a virtual environment.
2. Install the project with `pip install -e .`
3. Copy `.env.example` into your local environment setup.
4. Replace Alpaca paper credentials before any live API calls.
5. Run tests with `pytest`

Note:

- `dry_run` mode can use the built-in null broker when Alpaca credentials are not configured yet.
- use `config/investment-plan.paper.example.json` to define the paper budget, reserve cash, preferred symbols, and exclusions before longer runs.
- `paper` mode now stops early with a clear readiness blocker if Alpaca paper credentials are missing.
- `config/runtime.crypto.example.json` plus `config/watchlist.crypto.example.json` can be used to switch the bot into a `crypto` 24/7 paper-trading setup with faster polling and live stream-triggered cycle wakeups.
- `config/runtime.mixed.example.json` plus `config/watchlist.mixed.example.json` enable a mixed paper session where equities and crypto are tracked and traded together in one operator view, with the crypto side able to accelerate the next cycle when live prices move.

## GitHub Automation

The repository now includes a small GitHub automation path:

- `.github/workflows/ci.yml` runs `pytest` on pushes and pull requests
- `.github/workflows/pages.yml` builds and deploys a static GitHub Pages site
- `scripts/build_github_pages.py` generates the static site into `site/`
- `docs/setup/github-automation-and-pages.md` explains the GitHub setup and deployment flow

Local Pages preview:

```powershell
.\.venv\Scripts\python.exe scripts\build_github_pages.py --output site --repo Shadow2442/Autotrade
```
