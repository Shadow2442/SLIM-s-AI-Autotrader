# Operator Dashboard And Automation Design

## Purpose

This document describes the operating model for turning the trading bot into a monitored system with:

- portfolio dashboard output
- per-asset recommendations
- risk warnings and alert states
- recurring market surveillance
- future automated sell or reallocation decisions

## Product Goal

When the operator asks for a trading update, the system should produce a dashboard that answers:

- how much total equity do we have?
- how much cash is left?
- how much is currently invested?
- what is the unrealized profit or loss per asset?
- what signals or warnings are active?
- what should we do next per asset?

## Dashboard Requirements

The dashboard should eventually show:

- account summary cards
- allocation overview
- open orders count
- per-asset P/L
- recommendation and risk level per asset
- buy and sell markers on charts
- recent warning events
- strategy attribution over time

## Recommendation Model

Every tracked asset should end each run with:

- `risk_level`
  `low`, `medium`, `high`, or `critical`

- `recommendation`
  `buy_more`, `hold`, `watch`, `reduce`, `sell`, or `exit_now`

- `rationale`
  a short human-readable reason tied to strategy and risk evidence

## Risk Signals To Add Over Time

### Market Structure Risk

- strong trend breakdown
- sudden volatility spike
- gap risk
- liquidity deterioration

### Position Risk

- unrealized loss beyond threshold
- multiple conflicting open orders
- oversized concentration in one asset

### Event Risk

- major product failure
- leadership crisis
- regulatory action
- litigation shock
- cyberattack
- earnings surprise

### System Risk

- stale data
- reconciliation failure
- missing logs
- broker API instability

## Automation Loop

The recurring monitor should run several times per day and later potentially every few minutes during trading hours.

Initial automation responsibilities:

1. pull account, position, and order state
2. fetch latest market data for tracked assets
3. run reconciliation
4. update dashboard artifacts
5. assign risk levels and recommendations
6. surface warnings

Later automation responsibilities:

1. ingest relevant news or event data
2. raise red-light alerts on critical signals
3. recommend reallocation targets
4. auto-sell only when rules explicitly allow it

## Red-Light Design

The system should support a simple severity ladder:

- `green`
  normal monitoring

- `yellow`
  watch closely

- `orange`
  reduce or pause new buying

- `red`
  likely sell or urgently review

- `critical`
  eligible for automatic exit only if the operator has explicitly enabled that rule

## Safety Rule

Event-driven automatic selling should never be enabled casually.

Before auto-exit logic is allowed, the system must have:

- verified news/event sources
- explainable rules
- paper-test evidence
- operator approval

## Current Implementation Status

The current codebase now includes:

- structured JSONL logs
- startup reconciliation
- HTML and JSON dashboard reports
- per-position recommendation output

Still missing for the full vision:

- real historical chart rendering
- buy/sell markers from trade history
- news/event ingestion
- multi-strategy attribution
- portfolio history curves
- automatic reallocations

## Recommended Next Build Steps

1. add historical bars and plot-ready portfolio history
2. persist submitted trades and fills for chart markers
3. add recommendation config thresholds
4. ingest trusted event and news sources
5. gate any auto-sell logic behind explicit safety rules
