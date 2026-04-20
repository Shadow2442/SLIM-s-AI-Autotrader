# System Design

## Objective

This document defines the proposed technical architecture for the `Alpaca Paper` implementation.

The design goal is to support:

- controlled autonomous trading
- broker portability later
- strong auditability
- straightforward migration from paper to live

## Design Principles

- keep the first version simple
- isolate broker-specific code
- make all decisions inspectable
- prefer explicit state over hidden magic
- fail closed when safety checks cannot run

## Component Overview

### 1. Strategy Engine

Responsibility:

- convert market inputs into candidate trade actions
- attach a reason string or structured rationale

Examples of outputs:

- `BUY SPY`
- `SELL QQQ`
- `EXIT AAPL`
- `HOLD`

### 2. Risk Manager

Responsibility:

- accept or reject candidate actions
- enforce hard limits
- provide an explicit rejection reason

Sample checks:

- position size limit
- trade count limit
- drawdown limit
- market-hours check
- stale-data check

### 3. Broker Adapter

Responsibility:

- translate internal order requests into Alpaca API calls
- normalize broker responses into project-native models

This layer should hide provider details from the rest of the system.

### 4. Market Data Service

Responsibility:

- fetch bars, quotes, and trading calendar details
- normalize data shape
- expose a stable interface to strategies

### 5. Portfolio State Service

Responsibility:

- maintain current positions
- track open orders
- reconcile local state with broker state
- support restart safety

### 6. Audit Logger

Responsibility:

- log every strategy decision
- log every risk decision
- log every order submission and broker response
- log equity and account snapshots

### 7. Run Coordinator

Responsibility:

- orchestrate the trading loop
- initialize services
- manage start and stop behavior
- enforce the kill switch and run mode

## Proposed Folder Ownership

- `src/core/`
  Shared models, enums, and service contracts.

- `src/brokers/`
  Alpaca-specific integration and future broker adapters.

- `src/strategies/`
  Signal generation logic.

- `src/risk/`
  Risk policies and approval pipeline.

- `src/services/`
  Data ingestion, reconciliation, reporting, and runtime orchestration.

- `config/`
  Strategy and runtime configuration templates.

- `scripts/`
  Utility scripts for experiments and reporting.

## Runtime Modes

The system should support three modes:

- `dry_run`
  Strategy runs, but no order is submitted.

- `paper`
  Orders are submitted to Alpaca paper.

- `live`
  Reserved for later and blocked by default in phase one.

## Execution Flow

1. load config
2. validate environment
3. fetch account state
4. fetch fresh market data
5. generate candidate actions
6. pass candidates through risk checks
7. submit approved orders
8. record all outcomes
9. sleep until next cycle

## State Requirements

Persist enough data to answer:

- what did the bot know at decision time?
- why did it trade?
- what risk checks were applied?
- what did the broker return?
- what was the account state before and after?

## Suggested First Data Models

- `Signal`
- `RiskDecision`
- `OrderRequest`
- `OrderResult`
- `PositionSnapshot`
- `AccountSnapshot`
- `RunEvent`

## Migration Strategy

To move from paper to live later, the project should change:

- API credentials
- base URL
- runtime mode
- tighter risk thresholds

It should not require a redesign of the internal architecture.
