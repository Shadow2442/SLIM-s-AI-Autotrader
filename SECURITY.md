# Security Policy

## Scope

This repository is an **AI-assisted paper-trading platform** for equities and crypto. It is designed for experimentation, auditability, and operator review before anything approaches real-money deployment.

Security matters here because the project touches:

- broker credentials
- operator controls
- trading decisions
- generated reports
- automation workflows

## Supported Usage

The current supported operating model is:

- local development
- Alpaca paper trading
- GitHub-hosted source control and documentation

Real-money trading should be treated as **out of scope** unless the project is explicitly hardened for that purpose.

## Reporting A Vulnerability

If you find a security issue, please report it privately first instead of opening a public issue with exploit details.

Good reports include:

- affected file or feature
- how the issue can be reproduced
- likely impact
- whether secrets, operator actions, or broker behavior are involved

## Sensitive Data Rules

Never commit:

- Alpaca API keys
- GitHub tokens
- `.env` contents
- screenshots containing secrets
- ad hoc key dump files

Keep `.env` local and ignored. If credentials were ever exposed, rotate them instead of pretending the internet forgot.

## Operational Security Expectations

- use paper trading by default
- review operator controls before long unattended runs
- confirm dashboards are showing current data, not stale snapshots
- keep GitHub workflows least-privilege where possible
- avoid storing generated reports with secrets or personally identifying data

## Automation And GitHub

This repo uses GitHub Actions for CI and GitHub Pages deployment.

Please treat workflow changes carefully because they affect:

- test trustworthiness
- deployment behavior
- repo automation permissions

Any workflow update should be reviewed as a security-relevant change, not just a convenience tweak.

## Broker And Trading Risk Note

Paper trading is safer than real-money trading, but it still deserves discipline.

Problems that matter here include:

- stale state causing wrong operator conclusions
- duplicate orders
- broken stop logic
- misreported fills
- exposed credentials
- misleading UI signals

If a change could influence any of those, document it and call it out clearly in the pull request.
