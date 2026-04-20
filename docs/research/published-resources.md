# Published Resources And External Research

## Purpose

This document records published information that is relevant to the project and notes how each source may help the implementation.

The priority is:

1. official Alpaca documentation
2. official Alpaca educational material
3. third-party tools that may help workflow or research

## Summary Of Findings

### 1. Alpaca Paper Is The Correct First Environment

Alpaca's official docs state that:

- paper trading is free and available to all Alpaca users
- a paper-only account is available
- paper uses a different domain and different credentials from live
- the API shape is broadly the same between paper and live
- paper trading is only a simulation and may differ materially from live trading

Why this matters for our project:

- it confirms the decision to build on `Alpaca Paper` first
- it supports a clean `paper -> live` promotion path
- it reinforces that paper performance cannot be treated as live proof

Useful sources:

- Paper Trading - https://docs.alpaca.markets/docs/trading/paper-trading/
- Authentication - https://docs.alpaca.markets/docs/authentication-1
- About Trading API - https://docs.alpaca.markets/docs/trading-api

### 2. The Core Trading API Is Sufficient For A Proof Of Concept

Alpaca's Trading API documentation shows that we can:

- authenticate with paper credentials
- place, monitor, and cancel orders
- query positions and account data
- receive trade and order updates through streaming

Why this matters for our project:

- no browser automation is required for execution
- we can build a broker adapter directly against documented endpoints
- order-state streaming should be part of the design from early versions

Useful sources:

- Placing Orders - https://docs.alpaca.markets/docs/trading/orders/
- Working with /positions - https://docs.alpaca.markets/docs/working-with-positions
- Websocket Streaming - https://docs.alpaca.markets/v1.4.2/docs/websocket-streaming

### 3. Small-Budget Logic Is Feasible With Fractional Trading

Alpaca documents fractional trading support and notes that users can buy as little as `$1` worth of over 2,000 US equities.

Why this matters for our project:

- it supports tiny-account strategy logic
- it helps us simulate a later transition from paper to small live capital
- it reduces the need to start with expensive whole-share positions

Important note:

Fractional trading details may vary by order type, asset, and session rules. We should verify exact constraints in code and config before depending on any specific order mode.

Useful source:

- Fractional Trading - https://docs.alpaca.markets/v1.3/docs/fractional-trading

### 4. Market Data And Streaming Are First-Class Inputs

Alpaca's Market Data API documentation states that market data is available through both HTTP and WebSocket protocols, and that historical data can be used for backtesting and trading strategies.

Why this matters for our project:

- we can support both polling and streaming
- historical and live data can live under one provider family
- our architecture should separate market data retrieval from strategy logic

Useful sources:

- About Market Data API - https://docs.alpaca.markets/docs/about-market-data-api
- Historical API - https://docs.alpaca.markets/docs/historical-api

### 5. TradingView MCP Jackson Is Interesting, But Optional

The repository you linked, `LewisWJackson/tradingview-mcp-jackson`, is a public GitHub fork intended for AI-assisted TradingView Desktop workflows. According to its README:

- it is not affiliated with TradingView
- it requires a valid TradingView subscription
- it operates locally through the TradingView Desktop app using Chrome DevTools Protocol
- it adds a `morning_brief` workflow, reusable `rules.json`, chart analysis tools, alerts, screenshots, replay tools, and a CLI

Potential value to our project:

- useful as an optional `signal-research` layer
- could help generate a pre-market or pre-session bias report
- could help compare Alpaca-driven signals against visual TradingView indicators
- could support manual research, screenshots, and replay-based analysis

Why it is not part of the core execution path:

- it is a third-party project, not an official Alpaca or TradingView execution API
- it depends on local desktop automation and a paid TradingView setup
- it is better suited to chart analysis and workflow assistance than to broker execution
- it would add another moving part before we have the broker adapter stable

Recommended project position:

- `do not use it in v1 execution`
- `consider it later as an optional research or signal-ingestion companion`

Useful source:

- GitHub repository - https://github.com/LewisWJackson/tradingview-mcp-jackson

### 6. The Claude "One-Shot Setup" Pattern Is Reusable

The linked TradingView MCP repository includes a one-shot setup prompt that tells Claude Code to:

- clone the repository
- run dependency installation
- add the MCP server to Claude configuration
- copy a template rules file
- restart and verify with a health check

This exact setup flow is useful as a pattern, but not as-is.

What is good about it:

- it turns setup into a repeatable onboarding script
- it includes a verification step instead of assuming success
- it uses a template config file for user-editable rules
- it reduces friction for non-technical users

What should be improved for our use:

- prefer official `claude mcp add` commands or a project-scoped `.mcp.json`
- avoid relying on manual edits to `~/.claude/.mcp.json` for a shared project
- use environment variable expansion for machine-specific paths and secrets
- document Windows-specific command wrapping where required

According to Anthropic's official Claude Code MCP documentation:

- MCP servers can be added with `claude mcp add`
- project-scoped servers are stored in a repo-level `.mcp.json`
- project scope is intended for team-shared tool configuration
- local/user scopes are available for private or cross-project setups
- environment variables can be expanded inside `.mcp.json`
- on native Windows, `npx`-based MCP servers typically require `cmd /c`

Why this matters for our project:

- if we later add an MCP companion for research or chart review, we should make setup reproducible
- we should store shared MCP config in the project, not only in a user's home directory
- verification commands should be part of setup instructions
- any future optional TradingView integration should use the official Claude Code configuration pattern, not an ad hoc one

Recommended project position:

- reuse the `one-shot onboarding` idea
- do not copy the exact global-config approach blindly
- if we adopt MCP later, create a repo-level setup doc and optionally a project `.mcp.json`

This repository now includes a project onboarding note and a starter example config for that purpose:

- `docs/setup/mcp-onboarding.md`
- `.mcp.example.json`

Useful sources:

- Anthropic: Connect Claude Code to tools via MCP - https://docs.anthropic.com/en/docs/claude-code/mcp
- Anthropic: Claude Code settings - https://docs.anthropic.com/en/docs/claude-code/settings
- Anthropic: MCP in the SDK - https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-mcp

## Specific Ideas We Can Reuse Later

### Optional Idea A: Daily Session Brief

Borrow the concept, not the implementation commitment.

We can add a future internal feature that creates a daily session brief with:

- tracked symbols
- overnight gap summary
- trend state
- key levels
- risk flags
- trading allowed or blocked

This idea is directly useful and does not require us to adopt the third-party MCP server immediately.

### Optional Idea B: Rules File

The TradingView MCP project uses a `rules.json` concept for bias criteria, risk rules, and watchlists.

We can adapt that idea to our own system later as:

- `config/strategy.paper.json`
- `config/risk.paper.json`
- `config/watchlist.json`

This is useful because it keeps strategy and risk settings explicit and reviewable.

It also pairs well with a future one-shot setup flow where a template config is copied and then customized by the operator.

### Optional Idea C: Replay And Review Workflow

The linked TradingView tool includes replay support and chart capture. Even if we never adopt the tool, the workflow itself is helpful:

- replay a market period
- compare strategy decision vs chart context
- store review notes

That idea fits well with our future experiment reporting.

## Source Reliability Notes

### High confidence

- Alpaca official documentation
- Alpaca official learn pages when used for background, not hard requirements

### Medium confidence

- public GitHub repositories with active maintenance and clear documentation
- official vendor docs describing MCP configuration patterns for their own tools

### Lower confidence for direct system design decisions

- YouTube promotions
- affiliate-linked products
- unverified trading-performance claims

The links in the video description may be interesting, but they should not drive core architecture decisions without independent validation.

## Recommendation

Use official Alpaca docs as the source of truth for:

- account setup
- authentication
- market data access
- order execution
- paper-versus-live separation

Treat the TradingView MCP repository as a future enhancement candidate for:

- signal research
- session briefing
- chart-based review

Do not make it a dependency of the first Alpaca Paper implementation.

## References

- Alpaca Docs: Welcome - https://docs.alpaca.markets/docs
- Alpaca Docs: About Trading API - https://docs.alpaca.markets/docs/trading-api
- Alpaca Docs: Paper Trading - https://docs.alpaca.markets/docs/trading/paper-trading/
- Alpaca Docs: Authentication - https://docs.alpaca.markets/docs/authentication-1
- Alpaca Docs: Placing Orders - https://docs.alpaca.markets/docs/trading/orders/
- Alpaca Docs: Working with /positions - https://docs.alpaca.markets/docs/working-with-positions
- Alpaca Docs: About Market Data API - https://docs.alpaca.markets/docs/about-market-data-api
- Alpaca Docs: Historical API - https://docs.alpaca.markets/docs/historical-api
- Alpaca Docs: Websocket Streaming - https://docs.alpaca.markets/v1.4.2/docs/websocket-streaming
- Alpaca Docs: Fractional Trading - https://docs.alpaca.markets/v1.3/docs/fractional-trading
- Alpaca Learn: Algorithmic Trading - https://alpaca.markets/learn/tag/algorithmic-trading
- Anthropic: Connect Claude Code to tools via MCP - https://docs.anthropic.com/en/docs/claude-code/mcp
- Anthropic: Claude Code settings - https://docs.anthropic.com/en/docs/claude-code/settings
- Anthropic: MCP in the SDK - https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-mcp
- GitHub: tradingview-mcp-jackson - https://github.com/LewisWJackson/tradingview-mcp-jackson
