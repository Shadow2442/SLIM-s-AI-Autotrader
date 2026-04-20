from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_local_env(root_dir: Path) -> None:
    env_path = root_dir / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class RuntimeConfig:
    mode: str
    asset_class: str
    crypto_location: str
    crypto_streaming_enabled: bool
    crypto_stream_cooldown_seconds: int
    strategy_name: str
    bar_timeframe: str
    market_data_feed: str
    poll_interval_seconds: int
    max_cycles: int
    session_duration_minutes: int
    dry_run: bool


@dataclass(slots=True)
class StrategyConfig:
    name: str
    fast_window: int
    slow_window: int
    momentum_window: int
    history_limit: int
    breakout_lookback: int
    pullback_window: int
    pullback_tolerance_percent: float
    trend_strength_threshold_percent: float
    entry_threshold_percent: float
    exit_threshold_percent: float
    default_notional: float
    stop_loss_percent: float
    trailing_stop_percent: float
    take_profit_percent: float
    allow_sell_signals: bool


@dataclass(slots=True)
class RiskConfig:
    max_notional_per_trade: float
    max_open_positions: int
    max_trades_per_session: int
    max_daily_loss: float
    allow_fractional: bool
    allowed_order_types: list[str]


@dataclass(slots=True)
class EventRiskConfig:
    enabled: bool
    rss_urls: list[str]
    symbol_aliases: dict[str, list[str]]
    severity_keywords: dict[str, list[str]]
    recommendation_overrides: dict[str, str]


@dataclass(slots=True)
class InvestmentPlanConfig:
    starting_budget: float
    cash_reserve_percent: float
    crypto_allocation_percent: float
    equity_allocation_percent: float
    max_symbol_allocation_percent: float
    allowed_symbols: list[str]
    preferred_symbols: list[str]
    avoided_symbols: list[str]
    notes: str


@dataclass(slots=True)
class AppConfig:
    runtime: RuntimeConfig
    strategy: StrategyConfig
    risk: RiskConfig
    event_risk: EventRiskConfig
    investment_plan: InvestmentPlanConfig
    account_base_url: str
    market_data_url: str
    api_key: str
    api_secret: str
    watchlist: list[str]
    kill_switch: bool


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def load_app_config(root: Path | None = None) -> AppConfig:
    root_dir = root or Path.cwd()
    _load_local_env(root_dir)

    runtime_path = root_dir / os.getenv("AUTOTRADE_CONFIG_PATH", "config/runtime.paper.example.json")
    risk_path = root_dir / os.getenv("AUTOTRADE_RISK_PATH", "config/risk.paper.example.json")
    strategy_path = root_dir / os.getenv("AUTOTRADE_STRATEGY_PATH", "config/strategy.paper.example.json")
    watchlist_path = root_dir / os.getenv("AUTOTRADE_WATCHLIST_PATH", "config/watchlist.paper.example.json")
    event_risk_path = root_dir / os.getenv("AUTOTRADE_EVENT_RISK_PATH", "config/event-risk.example.json")
    investment_plan_path = root_dir / os.getenv(
        "AUTOTRADE_INVESTMENT_PLAN_PATH",
        "config/investment-plan.paper.example.json",
    )

    runtime_data = _read_json(runtime_path)
    risk_data = _read_json(risk_path)
    strategy_data = _read_json(strategy_path)
    watchlist_data = _read_json(watchlist_path)
    event_risk_data = _read_json(event_risk_path)
    investment_plan_data = _read_json(investment_plan_path)

    runtime = RuntimeConfig(
        mode=os.getenv("AUTOTRADE_MODE", runtime_data["mode"]),
        asset_class=os.getenv("AUTOTRADE_ASSET_CLASS", runtime_data.get("asset_class", "us_equity")),
        crypto_location=os.getenv("AUTOTRADE_CRYPTO_LOCATION", runtime_data.get("crypto_location", "us")),
        crypto_streaming_enabled=_env_bool(
            "AUTOTRADE_CRYPTO_STREAMING_ENABLED",
            runtime_data.get("crypto_streaming_enabled", True),
        ),
        crypto_stream_cooldown_seconds=_env_int(
            "AUTOTRADE_CRYPTO_STREAM_COOLDOWN_SECONDS",
            runtime_data.get("crypto_stream_cooldown_seconds", 5),
        ),
        strategy_name=os.getenv("AUTOTRADE_STRATEGY_NAME", runtime_data["strategy_name"]),
        bar_timeframe=os.getenv("AUTOTRADE_BAR_TIMEFRAME", runtime_data["bar_timeframe"]),
        market_data_feed=os.getenv("AUTOTRADE_MARKET_DATA_FEED", runtime_data["market_data_feed"]),
        poll_interval_seconds=_env_int(
            "AUTOTRADE_POLL_INTERVAL_SECONDS", runtime_data["poll_interval_seconds"]
        ),
        max_cycles=_env_int("AUTOTRADE_MAX_CYCLES", runtime_data["max_cycles"]),
        session_duration_minutes=_env_int(
            "AUTOTRADE_SESSION_DURATION_MINUTES",
            runtime_data.get("session_duration_minutes", 15),
        ),
        dry_run=_env_bool("AUTOTRADE_DRY_RUN", runtime_data["dry_run"]),
    )
    risk = RiskConfig(**risk_data)
    strategy = StrategyConfig(**strategy_data)
    event_risk = EventRiskConfig(**event_risk_data)
    investment_plan_defaults = {
        "crypto_allocation_percent": 50.0,
        "equity_allocation_percent": 50.0,
    }
    investment_plan = InvestmentPlanConfig(
        **(investment_plan_defaults | investment_plan_data)
    )

    return AppConfig(
        runtime=runtime,
        strategy=strategy,
        risk=risk,
        event_risk=event_risk,
        investment_plan=investment_plan,
        account_base_url=os.getenv("AUTOTRADE_ACCOUNT_BASE_URL", "https://paper-api.alpaca.markets"),
        market_data_url=os.getenv("AUTOTRADE_MARKET_DATA_URL", "https://data.alpaca.markets"),
        api_key=os.getenv("ALPACA_API_KEY", ""),
        api_secret=os.getenv("ALPACA_API_SECRET", ""),
        watchlist=watchlist_data.get("symbols", []),
        kill_switch=_env_bool("AUTOTRADE_KILL_SWITCH", False),
    )


def validate_runtime_mode(mode: str) -> None:
    allowed_modes = {"dry_run", "paper"}
    if mode not in allowed_modes:
        raise ValueError(f"Unsupported mode '{mode}'. Allowed modes: {sorted(allowed_modes)}")


def validate_asset_class(asset_class: str) -> None:
    allowed_asset_classes = {"us_equity", "crypto", "mixed"}
    if asset_class not in allowed_asset_classes:
        raise ValueError(
            f"Unsupported asset class '{asset_class}'. Allowed asset classes: {sorted(allowed_asset_classes)}"
        )


def normalize_symbol(symbol: str, asset_class: str | None = None) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return normalized

    if asset_class == "crypto" or "/" in normalized:
        if "/" in normalized:
            return normalized
        for quote in ("USDT", "USDC", "USD"):
            if normalized.endswith(quote) and len(normalized) > len(quote):
                base = normalized[: -len(quote)]
                return f"{base}/{quote}"
        return normalized

    return normalized


def infer_symbol_asset_class(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if "/" in normalized:
        return "crypto"
    for quote in ("USDT", "USDC", "USD"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return "crypto"
    return "us_equity"
