from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    side: str
    quantity: float | None = None
    notional: float | None = None
    order_type: str = "market"
    time_in_force: str = "day"


@dataclass(slots=True)
class Signal:
    symbol: str
    action: str
    confidence: float
    reason: str
    notional: float
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: str
    signal: Signal


@dataclass(slots=True)
class PositionSnapshot:
    symbol: str
    quantity: float
    market_value: float
    average_entry_price: float | None = None
    unrealized_pl: float | None = None
    unrealized_pl_percent: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AccountSnapshot:
    equity: float
    buying_power: float
    cash: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderSnapshot:
    order_id: str
    symbol: str
    side: str
    status: str
    notional: float | None = None
    quantity: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MarketBar:
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: str


@dataclass(slots=True)
class RunEvent:
    event_type: str
    message: str
    created_at: datetime = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AssetRecommendation:
    symbol: str
    asset_class: str
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_percent: float
    risk_level: str
    recommendation: str
    rationale: str
    signal_action: str = "HOLD"
    signal_confidence: float = 0.0
    fast_moving_average: float = 0.0
    slow_moving_average: float = 0.0
    momentum_percent: float = 0.0
    moving_average_gap_percent: float = 0.0
    signal_reason: str = ""
    strategy_setup: str = ""
    breakout_level: float = 0.0
    pullback_level: float = 0.0
    suggested_buy_price: float = 0.0
    suggested_sell_price: float = 0.0
    stop_price: float = 0.0
    trailing_stop_price: float = 0.0
    target_price: float = 0.0


@dataclass(slots=True)
class ChartPoint:
    timestamp: str
    value: float


@dataclass(slots=True)
class TradeMarker:
    symbol: str
    side: str
    timestamp: str
    price: float
    note: str


@dataclass(slots=True)
class AssetChart:
    symbol: str
    points: list[ChartPoint]
    markers: list[TradeMarker]


@dataclass(slots=True)
class TradeRecord:
    symbol: str
    side: str
    timestamp: str
    price: float
    quantity: float
    strategy_name: str
    source: str
    note: str


@dataclass(slots=True)
class SymbolPerformance:
    symbol: str
    realized_pl: float
    realized_trades: int
    open_quantity: float
    average_cost: float
    last_strategy: str


@dataclass(slots=True)
class StrategyPerformance:
    strategy_name: str
    realized_pl: float
    realized_trades: int


@dataclass(slots=True)
class OpenOrderInfo:
    symbol: str
    asset_class: str
    side: str
    status: str
    notional_value: float


@dataclass(slots=True)
class RecentOrderInfo:
    symbol: str
    asset_class: str
    side: str
    status: str
    amount_label: str
    price_label: str
    submitted_at: str


@dataclass(slots=True)
class DashboardSnapshot:
    generated_at: datetime
    total_equity: float
    cash: float
    buying_power: float
    filled_position_cost_basis: float
    invested_value: float
    open_orders_count: int
    pending_open_order_value: float
    open_order_status_summary: str
    open_order_fill_hint: str
    open_order_details: list[OpenOrderInfo]
    recent_order_activity: list[RecentOrderInfo]
    recommendations: list[AssetRecommendation]
    alerts: list[RunEvent]
    portfolio_history: list[ChartPoint]
    asset_charts: list[AssetChart]
    symbol_performance: list[SymbolPerformance]
    strategy_performance: list[StrategyPerformance]
