# Investment Plan UI Patterns

## Goal

Design an operator-facing investment settings panel that feels familiar to normal broker and trading software users.

## Patterns Worth Reusing

1. Separate `cash`, `buying power`, and `portfolio buckets`.
2. Make strategy buckets explicit and auditable.
3. Show available funds and committed funds side by side.
4. Treat transfers as intentional actions with logs and confirmations.
5. Keep allocation controls close to the wallet summary, not hidden in a different screen.

## Why This Fits Autotrade

- We already have one broker cash balance.
- We need bot-side planning wallets for `cash reserve`, `equities stash`, and `crypto stash`.
- We want to move money between these buckets without pretending the broker created real subaccounts.

## Source Notes

- Coinbase Advanced Trade portfolios emphasize separate trading environments and fast internal transfers between portfolios.
- Alpaca’s account model emphasizes `cash` and `buying power` as the top-level source of truth.
- Robinhood’s help center emphasizes distinct account buckets and asset-specific buying power.

## UI Decision

Use a top-level `Investment Plan` button that opens a modal with:

- broker cash
- cash wallet
- equity stash
- crypto stash
- committed vs free amounts
- editable budget and stash percentages
- explicit USD transfer controls

The first version should save cleanly, log the change, and apply on the next fresh bot start.
