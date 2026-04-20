# Strategy Categories For Future Bot Design

## Purpose

This document organizes common investment and trading strategy families so we have a structured menu to choose from when designing our own strategy later.

This is not personalized investment advice. There is no single "best" strategy for all investors or all market regimes. As FINRA and the SEC both emphasize, suitability depends on risk tolerance, time horizon, goals, and operational discipline.

## How To Read This Document

The categories below are rated in four practical ways:

- `Risk`
  How much capital and behavioral risk the strategy usually carries.

- `Consistency`
  How predictable the strategy behavior tends to be over time.

- `Return potential`
  The rough upside potential if the strategy is executed well.

- `Fit for v1 bot`
  Whether this strategy family is a good match for the first Alpaca paper prototype.

## Quick Summary

### Lower-risk / more consistent families

- diversified long-term investing
- periodic investing and rebalancing
- defensive or quality-tilted equity investing

### Moderate-risk / systematic families

- value investing
- momentum investing
- trend following

### Higher-risk / more fragile families

- short-term mean reversion
- market timing
- leveraged or inverse ETF trading
- highly leveraged or derivative-heavy speculation

## How To Access The Most Successful Strategies

There is no official leaderboard of "best strategy ever." The practical way to access the most successful and durable strategy families is to use sources that publish repeatable investment logic instead of relying on screenshots, influencers, or one lucky backtest.

The best source categories are:

### 1. Academic And Institutional Factor Research

This is the best place to find durable strategy families with long evidence windows.

Examples:

- `Momentum`
- `Trend following`
- `Value`
- `Quality / defensive`
- `Multi-factor combinations`

Why it is useful:

- the ideas are documented publicly
- they can be tested systematically
- they often generalize across periods better than ad hoc social-media strategies

### 2. Regulator And Investor-Education Sources

These do not usually hand you alpha, but they are essential because they explain:

- which strategies are structurally lower risk
- where investors usually get hurt
- what risk, diversification, and rebalancing really mean

Why it is useful:

- helps us avoid strategies that look profitable but are operationally reckless
- keeps our project grounded in suitability and risk control

### 3. Fund And ETF Methodologies

Many systematic funds publish their style definitions and portfolio methodology at a high level.

Why it is useful:

- shows how real managers package value, momentum, quality, and defensive styles
- helps us identify implementable signals and rebalancing logic
- gives us ideas for combining styles instead of betting everything on one signal

### 4. Public Strategy Libraries And Open Repositories

These can be useful for implementation ideas, but they must be treated carefully.

Why it is useful:

- may provide coding patterns, indicators, or backtest structure
- can accelerate prototyping

Main warning:

- open repositories often contain overfit logic, missing cost assumptions, or weak risk control

## How To Adopt Successful Strategies For Our Project

We should adopt strategies in layers, not by copying them wholesale.

### Step 1: Choose A Proven Strategy Family

Prefer a family with:

- published evidence
- intuitive logic
- compatibility with liquid assets
- easy translation into code

Best fits for us:

- `Trend following`
- `Momentum`
- `Momentum plus defensive filter`

### Step 2: Reduce The Idea To Simple Rules

Turn the published concept into clear implementation logic.

Examples:

- buy when price is above a moving average
- buy top-ranked symbols by relative strength
- trade only when higher-timeframe trend agrees
- skip symbols with extreme volatility

This is where "adoption" becomes real. If we cannot explain a strategy in a few lines of rules, we probably do not understand it well enough to automate it.

### Step 3: Add Risk Controls Before Optimization

A good strategy without risk controls is just an interesting way to lose money faster.

Minimum controls:

- position size cap
- max open positions
- max trades per session
- kill switch
- max daily loss
- cooldown after losses

### Step 4: Test In Paper Before Trying To Improve

Use Alpaca paper to answer:

- does the bot behave as expected?
- does it overtrade?
- are the logs good enough to reconstruct decisions?
- do controls actually fire?

Paper trading should validate behavior before it validates returns.

### Step 5: Compare Families, Not Parameter Noise

Do not immediately optimize:

- moving average 19 vs 20
- RSI 29 vs 30
- tiny threshold differences

Compare strategy families first:

- momentum vs trend following
- momentum vs mean reversion
- pure momentum vs momentum plus defensive filter

That gives more robust learning than polishing one fragile setup until it sparkles suspiciously.

## What "Most Successful" Usually Means In Practice

The answer depends on the metric:

### Highest long-term simplicity and reliability

- diversified passive investing
- periodic investing
- rebalancing

### Strongest evidence for systematic active styles

- momentum
- trend following
- value
- quality / defensive

### Best fit for our first bot

- trend following
- momentum
- multi-factor lite: momentum plus a defensive or quality filter

### Most dangerous relative to beginner confidence

- leveraged and inverse ETF strategies
- discretionary market timing
- high-turnover speculation without transaction-cost modeling

## Proposed Access Pipeline For Autotrade

We should collect strategy ideas using this pipeline:

1. `Source`
   Official or primary research source.

2. `Claim`
   What the strategy is supposed to exploit.

3. `Mechanics`
   The exact rule family we can code.

4. `Risk`
   The main failure mode.

5. `Fit`
   Whether it belongs in v1, later, or never.

6. `Paper Test`
   A simple evaluation plan.

This gives us a repeatable strategy-intake process instead of random idea shopping.

## Category 1: Diversified Passive Investing

Description:

- broad diversification across assets or broad-market funds
- infrequent trading
- long holding periods
- often paired with periodic rebalancing

Risk: `Low to medium`

Consistency: `High` for process discipline, lower for short-term returns

Return potential: `Moderate`

Fit for v1 bot: `Low` as a trading bot, `High` as a long-term auto-investing module

Why it matters:

The SEC's investor guidance emphasizes diversification and rebalancing as core ways to manage portfolio risk. This is the most stable category conceptually, but it is closer to portfolio automation than short-term trading.

Project takeaway:

- great reference model for future capital preservation logic
- not the best first target for a 24-hour trading experiment

## Category 2: Dollar-Cost Averaging

Description:

- invest equal amounts at regular intervals
- ignore short-term price swings when scheduling purchases

Risk: `Low to medium`

Consistency: `High` in process, lower in absolute returns

Return potential: `Moderate`, but often below immediate lump-sum investing in rising markets

Fit for v1 bot: `Low` for short-term trading, `High` for future auto-invest features

Why it matters:

FINRA notes that dollar-cost averaging can help limit regret and short-term downside timing risk, but it can also sacrifice upside if markets rise while cash waits on the sidelines.

Project takeaway:

- useful as a low-stress baseline system
- not a strong candidate for our first active trading bot

## Category 3: Value Investing

Description:

- buy assets that appear cheap relative to fundamentals
- usually requires patience and longer holding periods
- often underperforms for long stretches before recovering

Risk: `Medium`

Consistency: `Medium to low` over short windows, stronger over long cycles

Return potential: `High` over long horizons, but lumpy

Fit for v1 bot: `Low to medium`

Why it matters:

Value is one of the most studied factor premia. AQR's research continues to treat value as a foundational style, but it is not ideal for a 24-hour proof-of-concept because the edge typically plays out over longer periods.

Project takeaway:

- important category for future research
- poor fit for a one-day autonomous paper experiment

## Category 4: Momentum Investing

Description:

- buy relative winners and avoid or sell relative losers
- usually implemented through recent price strength
- often rebalanced systematically

Risk: `Medium`

Consistency: `Medium`

Return potential: `High`

Fit for v1 bot: `High`

Why it matters:

AQR describes momentum as one of the most widely studied and persistent factors across markets. It is simple enough to prototype with moving averages or relative strength, which makes it one of the best starting points for our bot.

Project takeaway:

- strong candidate for the first strategy family
- easy to explain
- easy to backtest later
- must be combined with risk controls because momentum can reverse sharply

## Category 5: Trend Following

Description:

- follow persistent market direction
- often uses breakouts, moving averages, or time-series momentum
- usually cuts losers and lets winners run

Risk: `Medium`

Consistency: `Medium`

Return potential: `High`

Fit for v1 bot: `High`

Why it matters:

AQR's long-horizon trend-following research reports strong historical evidence for time-series momentum across asset classes. For our purposes, trend following is one of the most practical systematic approaches because it maps cleanly onto rules, watchlists, and hard risk limits.

Project takeaway:

- probably the best overall family for `v1`
- simple enough to implement without fake sophistication
- good match for liquid equities and 5-minute or longer bars

## Category 6: Mean Reversion

Description:

- bet that price moves will snap back toward an average
- often buys weakness and sells strength
- can be intraday or multi-day

Risk: `Medium to high`

Consistency: `Low to medium`

Return potential: `Moderate to high`

Fit for v1 bot: `Medium`

Why it matters:

Mean reversion can work well in range-bound conditions, but it is more fragile when markets trend aggressively. It also tends to punish premature entries, which means poor risk controls can turn a clever idea into a very efficient money-shredder.

Project takeaway:

- interesting for later experiments
- not my first recommendation for the initial unattended bot

## Category 7: Defensive / Quality Investing

Description:

- favor lower-volatility or higher-quality companies
- emphasize stability over maximum upside
- often used to improve risk-adjusted returns

Risk: `Low to medium`

Consistency: `Medium to high`

Return potential: `Moderate`

Fit for v1 bot: `Medium`

Why it matters:

AQR's defensive-investing material frames this family as seeking market-like returns with lower volatility over a full cycle. That makes it attractive as a portfolio-construction overlay, though less naturally suited than momentum or trend following for a first short-horizon trading prototype.

Project takeaway:

- useful as a future watchlist filter
- especially valuable if we later optimize for smoother equity curves instead of raw upside

## Category 8: Market Timing

Description:

- active attempts to jump in and out based on short-term moves
- often driven by macro news, sentiment, or strong directional beliefs

Risk: `High`

Consistency: `Low`

Return potential: `Potentially high, but highly variable`

Fit for v1 bot: `Low`

Why it matters:

FINRA notes that market timing is an active effort to exploit short-term price fluctuations. In practice, it is behaviorally hard, tax-inefficient in taxable accounts, and easy to confuse with disciplined systematic trading when it is actually just guesswork wearing a tie.

Project takeaway:

- avoid building a discretionary market timer as v1
- only approach this space through explicit, testable rules

## Category 9: Leveraged / Inverse ETF Trading

Description:

- use products designed to magnify or invert short-term moves
- often resets daily
- can deviate materially from intuitive long-term expectations

Risk: `Very high`

Consistency: `Low`

Return potential: `Very high short-term, poor risk-adjusted behavior for inexperienced use`

Fit for v1 bot: `Very low`

Why it matters:

The SEC has explicitly warned that single-stock levered and inverse ETFs are riskier than holding the underlying stock or a traditional ETF. These are not beginner tools, and they are not the kind of thing I want our first robot touching while still learning to tie its shoes.

Project takeaway:

- exclude from early bot versions
- only revisit if we later build product-specific controls and education

## Suggested Ranking For This Project

### Best first candidates

1. `Trend following`
2. `Momentum`
3. `Defensive/quality filter combined with momentum`

### Good later candidates

1. `Mean reversion`
2. `Value-informed swing strategies`
3. `Periodic investing or DCA modules for long-term automation`

### Avoid in early versions

1. `Leveraged or inverse ETF strategies`
2. `Discretionary market timing`
3. `Anything dependent on leverage, options complexity, or weak liquidity`

## Proposed Strategy Path For Autotrade

### Phase A

Use a simple `trend-following / momentum` strategy on liquid US equities:

- `SPY`
- `QQQ`
- `AAPL`
- `MSFT`

Why:

- easy to explain
- easy to audit
- easy to throttle with risk rules
- aligns well with Alpaca paper and our current architecture

### Phase B

Add one stabilizer:

- defensive filter
- higher-timeframe trend filter
- cooldown after losses

### Phase C

Compare alternative families:

- momentum vs mean reversion
- plain momentum vs momentum plus defensive filter
- fixed watchlist vs rotating watchlist

## Final Recommendation

If the goal is to access the most successful strategies and adopt them intelligently, we should do this:

1. Use published factor research and regulator guidance as the source of truth.
2. Start with `trend following` and `momentum`, because they have strong published support and fit our bot architecture.
3. Add a `defensive or quality filter` before exploring riskier families.
4. Exclude leveraged and inverse products from early versions.
5. Treat strategy adoption as a rules-engineering problem, not a hype-discovery problem.

## References

- SEC: Beginners' Guide to Asset Allocation, Diversification, and Rebalancing - https://www.sec.gov/about/reports-publications/investorpubsassetallocationhtm
- Investor.gov: Tips for 2026 - Investor Bulletin - https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/investorgov-tips-2026-investor-bulletin
- FINRA: The Pros and Cons of Dollar-Cost Averaging - https://www.finra.org/investors/insights/dollar-cost-averaging
- FINRA: What Is Market Timing? - https://www.finra.org/investors/insights/market-timing
- FINRA: Risk - https://www.finra.org/investors/investing/investing-basics/risk
- AQR: Momentum Factor Strategies - https://funds.aqr.com/Insights/Strategies/Momentum-Factor
- AQR: A Century of Evidence on Trend-Following Investing - https://www.aqr.com/insights/research/journal-article/a-century-of-evidence-on-trend-following-investing
- AQR: Investing with Style - https://www.aqr.com/Insights/Research/Journal-Article/Investing-With-Style
- AQR: Defensive Factor Strategies - https://funds.aqr.com/Insights/Strategies/Defensive-Factor
- SEC: Statement on Single-Stock Levered and/or Inverse ETFs - https://www.sec.gov/newsroom/speeches-statements/schock-statement-single-stock-levered-or-inverse-etfs-071122
