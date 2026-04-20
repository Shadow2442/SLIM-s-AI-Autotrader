# Alpaca Paper Research And Build Plan

## Purpose

This document is the main research paper for the first phase of the project: building an AI-assisted automated trading system on top of `Alpaca Paper`.

The target outcome is a controlled proof of concept that can run autonomously for a fixed window, such as `24 hours`, while preserving safety, traceability, and reproducibility.

## Executive Summary

`Alpaca Paper` is the recommended first environment for this project because it allows realistic trading simulation with fake money while preserving a migration path toward `Alpaca Live`.

The research conclusion is:

- use `Alpaca Paper` before any live trading
- design the system so paper and live are separated by configuration, not architecture
- prioritize risk controls and observability before strategy complexity
- treat autonomous trading as a systems engineering problem, not just a prediction problem

## Project Goals

- build a reusable trading bot framework
- support paper trading first
- support later migration to live trading with minimal code changes
- document every operational and security control
- create a structure suitable for GitHub publication later

## Non-Goals For Phase One

- maximizing returns
- high-frequency trading
- options strategies
- leverage
- social trading features
- multi-broker production support

## Why Alpaca Paper Is Priority One

Alpaca Paper is the best first target for this project because it provides:

- a low-risk environment using simulated capital
- API parity in broad structure with live trading
- suitable support for small-account logic testing
- a straightforward developer workflow

For the initial experiment, we care more about:

- safe order flow
- controlled automation
- correct accounting
- failure handling
- usable logs

than about raw strategy performance.

Published support for this direction exists in Alpaca's own documentation:

- paper trading is free and available to all Alpaca users
- paper and live use separate credentials and domains
- the same general API shape can be used for both environments
- paper is a simulation and does not fully reflect live execution quality

See `docs/research/published-resources.md` for source-backed notes and references.

## Core Assumptions

- the project begins with US equities only
- the first strategy will be intentionally simple
- a single-user operator model is acceptable for phase one
- the system will run from a local machine or small server
- all real-money migration decisions happen only after paper validation

## High-Level Build Plan

### Phase 1: Foundation

Set up repository structure, documentation, and environment configuration.

Deliverables:

- repository layout
- core docs
- implementation plan
- risk and security baseline

### Phase 2: Broker Connectivity

Implement the minimum Alpaca paper adapter.

Deliverables:

- account authentication
- account info retrieval
- position retrieval
- order submission interface
- cancel order interface
- market data retrieval

### Phase 3: Trading Core

Build the system that turns market data into controlled trade actions.

Deliverables:

- strategy engine
- signal model
- broker abstraction
- risk manager
- position sizing rules
- audit logger

### Phase 4: Operational Controls

Add the controls required for safe unattended operation.

Deliverables:

- dry-run mode
- emergency stop
- max daily loss limit
- max trades per interval
- stale-data detection
- duplicate-order prevention

### Phase 5: Experiment Execution

Run fixed paper experiments and produce clear reporting.

Deliverables:

- experiment configuration
- run report
- PnL summary
- trade log
- incident log
- post-run review template

### Phase 6: Live Readiness Review

Determine whether the system is mature enough for a tiny live deployment.

Deliverables:

- readiness checklist
- unresolved risks list
- live migration plan

## Proposed Initial Strategy

The first strategy should be intentionally narrow and boring.

Recommended initial approach:

- asset universe: `SPY`, `QQQ`, `AAPL`, `MSFT`
- timeframe: `5-minute bars`
- position style: one open position per symbol
- trade frequency: low
- order types: market or simple limit only
- sizing: small notional sizing rules

Possible simple models:

- moving-average momentum
- breakout confirmation with trend filter
- mean-reversion around a simple intraday band

The system should begin with the easiest strategy to explain and audit.

## Recommended System Architecture

The system should be split into six practical layers:

1. `Market Data Layer`
   Retrieves quotes, bars, and account-adjacent data needed by the strategy.

2. `Strategy Layer`
   Produces human-readable signals such as `BUY`, `SELL`, `EXIT`, or `HOLD`.

3. `Risk Layer`
   Approves or blocks strategy actions based on hard rules.

4. `Execution Layer`
   Submits orders to Alpaca paper and verifies acknowledgments and fills.

5. `State And Persistence Layer`
   Stores positions, open orders, run metadata, and audit history.

6. `Reporting And Operations Layer`
   Produces summaries, incident flags, and operator-facing diagnostics.

## Step-By-Step Setup Plan

### Step 1: Create Alpaca Accounts

- create an Alpaca user account
- open a paper trading account
- generate paper API credentials
- record the paper API base URL
- confirm whether a paper-only account is sufficient for the current phase

### Step 2: Establish Local Secrets Handling

- store credentials in environment variables
- do not hardcode keys in code
- do not commit `.env` files
- separate paper keys from any future live keys

### Step 3: Verify API Connectivity

- call account endpoint
- confirm paper buying power and account status
- retrieve positions and open orders
- validate that auth failures are logged clearly
- subscribe to order updates via WebSocket or document why polling is temporarily used

### Step 4: Build Data Ingestion

- retrieve recent bars for a small list of symbols
- normalize timestamps and symbol identifiers
- handle API rate and retry logic

### Step 5: Build Order Execution Wrapper

- define a broker interface
- implement `submit_order`
- implement `cancel_order`
- implement `list_positions`
- implement `list_orders`
- standardize error handling

### Step 6: Add Risk Controls Before Strategy Complexity

- max position size
- max total exposure
- cooldown after closing a trade
- max trades per symbol per session
- max daily drawdown
- stale-data guardrail

### Step 7: Add Strategy Logic

- compute indicators
- generate a signal with a machine-readable reason
- pass all signals through the risk layer
- log both approved and rejected signals

### Step 8: Build Logging And Reporting

- structured trade logs
- decision logs
- account equity snapshots
- run summaries
- incident records

### Step 9: Run Controlled Experiments

- start in dry-run mode
- move to paper trading with minimal size assumptions
- run a fixed 24-hour session
- review outputs before changing any settings

## Security Requirements

The project must assume that API keys are sensitive production credentials even in paper mode.

Minimum requirements:

- use environment variables or a secrets manager
- never store keys in the repository
- rotate keys if exposed
- keep paper and live keys completely separate
- restrict who can run the bot with valid credentials
- log trade behavior, never raw secrets

This separation is explicitly supported by Alpaca's authentication model, which uses different domains and credentials for paper and live environments.

## Risk Controls

Risk controls are mandatory and should be implemented as hard gates.

Required controls for phase one:

- `Kill switch`
  Immediately prevent new order submissions.

- `Max daily loss`
  Halt trading if session drawdown exceeds a configured threshold.

- `Max position size`
  Prevent any single trade from exceeding a fixed notional or quantity cap.

- `Max open positions`
  Limit concurrency.

- `Max trade frequency`
  Prevent runaway loops and rapid-fire order bursts.

- `Duplicate order suppression`
  Avoid repeated submissions caused by retries or state drift.

- `Cooldown periods`
  Require a pause after exits or losses.

- `Stale data detection`
  Do not trade on delayed or missing data.

- `Trading hours gate`
  Restrict operation to intended market windows unless explicitly configured otherwise.

## Operational Risks

These risks are more important than the trading idea itself during phase one:

- data gaps
- clock drift
- duplicate orders
- partial fills
- reconnect behavior
- stale positions after restart
- incorrect PnL calculation
- overtrading due to noisy signals
- silent failures in unattended mode
- overconfidence due to paper-trading assumptions differing from live fills

## Readiness Criteria For Alpaca Live

Do not consider live deployment until all of the following are true:

- paper trading runs complete without order-control failures
- logs are sufficient to reconstruct every trade decision
- emergency stop is tested
- strategy behavior matches expectation over multiple sessions
- account and order reconciliation are stable after restarts
- the system can tolerate API errors gracefully

## Suggested Documentation To Add Later

- implementation decision log
- API contract reference
- environment setup guide with exact commands
- test strategy results notebook
- incident response checklist

## Final Recommendation

Build the smallest credible automated trading system first.

That means:

- start with `Alpaca Paper`
- use a simple strategy
- invest heavily in controls and auditability
- treat paper trading results as engineering validation, not proof of profitability

The real milestone is not "did the bot make money in one day?"

The real milestone is "did the bot behave safely, predictably, and transparently for one day?"

## References

- Alpaca Docs: Paper Trading - https://docs.alpaca.markets/docs/trading/paper-trading/
- Alpaca Docs: Authentication - https://docs.alpaca.markets/docs/authentication-1
- Alpaca Docs: About Trading API - https://docs.alpaca.markets/docs/trading-api
- Alpaca Docs: Placing Orders - https://docs.alpaca.markets/docs/trading/orders/
- Alpaca Docs: Websocket Streaming - https://docs.alpaca.markets/v1.4.2/docs/websocket-streaming
- Alpaca Docs: About Market Data API - https://docs.alpaca.markets/docs/about-market-data-api
- Alpaca Docs: Fractional Trading - https://docs.alpaca.markets/v1.3/docs/fractional-trading
- Alpaca Docs: Working with /positions - https://docs.alpaca.markets/docs/working-with-positions
