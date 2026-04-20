# Runbook

## Purpose

This runbook defines how to operate the system safely during the `Alpaca Paper` phase.

## Standard Run Sequence

1. confirm runtime mode is `paper` or `dry_run`
2. confirm expected Alpaca base URL
3. confirm API credentials are loaded from environment
4. confirm kill switch is disabled
5. start the trading process
6. monitor logs during startup
7. verify account state sync succeeded
8. verify first market data pull succeeded
9. verify first strategy cycle completed cleanly

## During The Run

Watch for:

- repeated order failures
- repeated identical trade signals
- stale market data
- missing account snapshots
- reconciliation errors
- max loss trigger activation

## Emergency Stop Procedure

Use the kill switch when:

- the bot is submitting unexpected orders
- market data appears broken
- logs stop updating normally
- strategy behavior is unexplained
- reconciliation fails repeatedly

Emergency stop expectations:

- no new orders are submitted
- open order cancellation behavior follows configured policy
- the stop event is logged clearly

## Post-Run Review

After each experiment, review:

- total trades
- win/loss distribution
- net PnL
- max drawdown
- rejected signals count
- order errors count
- any incident notes

## Incident Categories

- `auth_error`
- `data_error`
- `order_error`
- `risk_block`
- `reconciliation_error`
- `operator_stop`
- `unexpected_behavior`

## Criteria To Continue Testing

Continue to the next experiment only if:

- no unexplained orders occurred
- logs are complete
- strategy actions can be reconstructed
- no critical incidents remain unresolved
