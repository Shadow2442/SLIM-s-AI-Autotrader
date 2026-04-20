# Security Controls

## Purpose

This document defines the minimum security baseline for the automated trading project.

Even though `Alpaca Paper` uses simulated money, paper credentials should still be treated as sensitive because they control the system behavior and often coexist with future live-trading infrastructure.

## Security Objectives

- protect credentials
- prevent unauthorized trading actions
- preserve trustworthy logs
- reduce accidental promotion from paper to live
- minimize blast radius when something goes wrong

## Required Controls

### 1. Secret Management

- keep API keys in environment variables or a trusted secret store
- never hardcode secrets in source files
- never commit secrets to Git
- rotate keys immediately if exposure is suspected

### 2. Environment Separation

- keep `paper` and `live` credentials separate
- use distinct config files for each runtime mode
- require an explicit mode flag before startup
- block `live` mode by default during phase one

### 3. Principle Of Least Privilege

- use only the credentials necessary for the current environment
- limit operator access to machines that can run the bot
- do not share credentials across unrelated tools or people

### 4. Startup Validation

At startup, the system should verify:

- required env vars are present
- runtime mode is allowed
- base URL matches the selected environment
- the kill switch is not engaged unexpectedly

If validation fails, the process should stop before any trade logic runs.

### 5. Logging Discipline

- log decisions, not secrets
- redact tokens, keys, and authorization headers
- store logs in structured form
- timestamp all events consistently

### 6. Change Safety

- all live-mode enabling changes should be reviewed explicitly
- critical risk settings should be centralized in config
- strategy changes should be traceable through documentation or version control

## Threat Scenarios

### Accidental Live Trading

Risk:
The bot may point to live endpoints with real credentials unintentionally.

Mitigations:

- explicit `MODE` setting
- startup environment check
- hard block on live mode until phase one is complete

### Key Exposure

Risk:
API keys leak through commits, screenshots, logs, or copied config files.

Mitigations:

- `.gitignore` for env files
- secret redaction in logs
- no secrets in docs examples
- key rotation plan

### Runaway Trading Logic

Risk:
A loop bug or state bug causes rapid repeated orders.

Mitigations:

- max trades per interval
- duplicate order detection
- circuit breaker
- manual kill switch

### State Divergence

Risk:
Local state disagrees with broker state after restart or network failure.

Mitigations:

- broker reconciliation on startup
- polling of open orders and positions
- fail-safe pause when reconciliation is ambiguous

## Operational Security Recommendations

- use a dedicated machine or isolated runtime for unattended runs
- keep system time synchronized
- monitor logs during early runs
- avoid remote desktop sessions left open on unsecured networks
- separate future live credentials from development machines when possible

## Minimum Pre-Live Security Checklist

- no hardcoded secrets anywhere in repository
- env files ignored by Git
- startup checks implemented and tested
- live mode blocked unless manually enabled
- logs verified to exclude raw secrets
- kill switch tested
