from __future__ import annotations

from autotrade.config import StrategyConfig
from autotrade.models import MarketBar, Signal


def analyze_bars(
    *,
    bars: list[MarketBar],
    has_position: bool,
    strategy: StrategyConfig,
    average_entry_price: float | None = None,
) -> dict[str, float | str]:
    closes = [bar.close for bar in bars]
    minimum_history = max(
        strategy.slow_window,
        strategy.momentum_window + 1,
        strategy.breakout_lookback + 1,
        strategy.pullback_window,
    )
    if len(closes) < minimum_history:
        return {
            "action": "HOLD",
            "confidence": 0.2,
            "reason": "not_enough_history",
            "setup": "NO_DATA",
            "price": closes[-1] if closes else 0.0,
            "fast_ma": 0.0,
            "slow_ma": 0.0,
            "momentum_percent": 0.0,
            "ma_gap_percent": 0.0,
            "breakout_level": 0.0,
            "pullback_level": 0.0,
            "suggested_buy_price": 0.0,
            "suggested_sell_price": 0.0,
            "stop_price": 0.0,
            "trailing_stop_price": 0.0,
            "target_price": 0.0,
        }

    price = closes[-1]
    fast_ma = _average(closes[-strategy.fast_window :])
    slow_ma = _average(closes[-strategy.slow_window :])
    momentum_anchor = closes[-(strategy.momentum_window + 1)]
    momentum_percent = 0.0 if momentum_anchor == 0 else ((price - momentum_anchor) / momentum_anchor) * 100
    ma_gap_percent = 0.0 if slow_ma == 0 else ((fast_ma - slow_ma) / slow_ma) * 100
    breakout_source = closes[-(strategy.breakout_lookback + 1) : -1]
    breakout_level = max(breakout_source) if breakout_source else price
    recent_pullback_source = closes[-strategy.pullback_window :]
    pullback_level = min(recent_pullback_source) if recent_pullback_source else price
    recent_high = max(recent_pullback_source) if recent_pullback_source else price

    trend_ready = (
        fast_ma > slow_ma
        and momentum_percent >= strategy.entry_threshold_percent
        and ma_gap_percent >= strategy.trend_strength_threshold_percent
    )
    breakout_ready = trend_ready and price >= breakout_level
    pullback_band_low = fast_ma * (1 - strategy.pullback_tolerance_percent / 100)
    pullback_band_high = fast_ma * (1 + strategy.pullback_tolerance_percent / 100)
    pullback_ready = trend_ready and pullback_band_low <= price <= pullback_band_high and price > pullback_level

    entry_reference = average_entry_price if average_entry_price is not None else price
    stop_price = entry_reference * (1 - strategy.stop_loss_percent / 100)
    trailing_stop_price = recent_high * (1 - strategy.trailing_stop_percent / 100)
    target_price = entry_reference * (1 + strategy.take_profit_percent / 100)
    suggested_buy_price = min(price, max(pullback_band_low, pullback_level))
    suggested_sell_price = max(trailing_stop_price, target_price if has_position else breakout_level)

    action = "HOLD"
    setup = "TREND_WAIT"

    if not has_position:
        if breakout_ready:
            action = "BUY"
            setup = "BREAKOUT_BUY"
        elif pullback_ready:
            action = "BUY"
            setup = "PULLBACK_BUY"
        elif trend_ready:
            setup = "TREND_WATCH"
        else:
            setup = "AVOID"
    else:
        if price <= stop_price:
            action = "SELL"
            setup = "EXIT_STOP_LOSS"
        elif price <= trailing_stop_price and momentum_percent <= 0:
            action = "SELL"
            setup = "EXIT_TRAILING_STOP"
        elif strategy.allow_sell_signals and fast_ma < slow_ma:
            action = "SELL"
            setup = "EXIT_TREND_BREAK"
        elif strategy.allow_sell_signals and momentum_percent <= strategy.exit_threshold_percent:
            action = "SELL"
            setup = "EXIT_MOMENTUM_BREAK"
        elif price >= target_price and momentum_percent < strategy.entry_threshold_percent:
            action = "SELL"
            setup = "EXIT_TAKE_PROFIT"
        else:
            setup = "TREND_HOLD"

    confidence = _confidence_for_setup(
        setup=setup,
        ma_gap_percent=ma_gap_percent,
        momentum_percent=momentum_percent,
    )
    reason = _reason_for_setup(
        setup=setup,
        price=price,
        fast_ma=fast_ma,
        slow_ma=slow_ma,
        momentum_percent=momentum_percent,
        ma_gap_percent=ma_gap_percent,
        breakout_level=breakout_level,
        pullback_level=pullback_level,
        stop_price=stop_price,
        trailing_stop_price=trailing_stop_price,
        target_price=target_price,
    )

    return {
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "setup": setup,
        "price": price,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "momentum_percent": momentum_percent,
        "ma_gap_percent": ma_gap_percent,
        "breakout_level": breakout_level,
        "pullback_level": pullback_level,
        "suggested_buy_price": suggested_buy_price,
        "suggested_sell_price": suggested_sell_price,
        "stop_price": stop_price,
        "trailing_stop_price": trailing_stop_price,
        "target_price": target_price,
    }


def generate_signal(
    symbol: str,
    *,
    bars: list[MarketBar],
    has_position: bool,
    strategy: StrategyConfig,
    average_entry_price: float | None = None,
) -> Signal:
    analysis = analyze_bars(
        bars=bars,
        has_position=has_position,
        strategy=strategy,
        average_entry_price=average_entry_price,
    )
    return Signal(
        symbol=symbol,
        action=str(analysis["action"]),
        confidence=float(analysis["confidence"]),
        reason=str(analysis["reason"]),
        notional=strategy.default_notional,
    )


def _average(values: list[float]) -> float:
    return sum(values) / len(values)


def _confidence_for_setup(*, setup: str, ma_gap_percent: float, momentum_percent: float) -> float:
    base = min(0.95, 0.45 + abs(ma_gap_percent) / 4 + abs(momentum_percent) / 6)
    if setup.startswith("EXIT_"):
        return min(0.98, base + 0.1)
    if setup in {"BREAKOUT_BUY", "PULLBACK_BUY"}:
        return min(0.96, base + 0.08)
    if setup == "TREND_HOLD":
        return min(0.9, base)
    return max(0.2, min(0.75, base - 0.12))


def _reason_for_setup(
    *,
    setup: str,
    price: float,
    fast_ma: float,
    slow_ma: float,
    momentum_percent: float,
    ma_gap_percent: float,
    breakout_level: float,
    pullback_level: float,
    stop_price: float,
    trailing_stop_price: float,
    target_price: float,
) -> str:
    prefix_map = {
        "BREAKOUT_BUY": "Bullish breakout confirmed above prior resistance.",
        "PULLBACK_BUY": "Trend is intact and price is pulling back into the fast moving average zone.",
        "TREND_WATCH": "Trend is positive but the entry is not clean enough yet.",
        "TREND_HOLD": "Trend remains healthy and the position still fits the strategy.",
        "EXIT_STOP_LOSS": "Price breached the configured stop-loss level.",
        "EXIT_TRAILING_STOP": "Price rolled over through the trailing stop while momentum weakened.",
        "EXIT_TREND_BREAK": "Fast moving average crossed below the slow trend line.",
        "EXIT_MOMENTUM_BREAK": "Momentum fell through the configured exit threshold.",
        "EXIT_TAKE_PROFIT": "Price reached the target area and momentum cooled off.",
        "AVOID": "Trend conditions are not strong enough for a new long entry.",
        "TREND_WAIT": "Waiting for stronger confirmation before acting.",
        "NO_DATA": "Not enough history to evaluate Strategy A yet.",
    }
    prefix = prefix_map.get(setup, "Strategy state updated.")
    return (
        f"{prefix} "
        f"price={price:.2f} fast_ma={fast_ma:.2f} slow_ma={slow_ma:.2f} "
        f"momentum={momentum_percent:.2f}% gap={ma_gap_percent:.2f}% "
        f"breakout={breakout_level:.2f} pullback={pullback_level:.2f} "
        f"stop={stop_price:.2f} trail={trailing_stop_price:.2f} target={target_price:.2f}"
    )
