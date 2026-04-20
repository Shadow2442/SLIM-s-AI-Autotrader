import json
from pathlib import Path

from autotrade.brokers.base import BrokerAdapter
from autotrade.config import AppConfig, EventRiskConfig, InvestmentPlanConfig, RiskConfig, RuntimeConfig, StrategyConfig
from autotrade.models import AccountSnapshot, MarketBar, OrderSnapshot, PositionSnapshot
from autotrade.risk.manager import RiskManager
from autotrade.services.operator_overrides import OperatorOverrideStore
from autotrade.services.trading_loop import TradingLoop


class FakeBroker(BrokerAdapter):
    def __init__(self) -> None:
        self.submitted_orders = []
        self.cancelled_orders = []

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(equity=1000.0, buying_power=1000.0, cash=1000.0)

    def list_positions(self) -> list[PositionSnapshot]:
        return []

    def list_open_orders(self) -> list[OrderSnapshot]:
        return []

    def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
        return {
            symbol: MarketBar(
                symbol=symbol,
                open=124.1,
                high=125.1,
                low=123.7,
                close=124.65,
                volume=1000.0,
                timestamp="2026-04-16T06:00:00Z",
            )
            for symbol in symbols
        }

    def get_historical_bars(
        self,
        symbols: list[str],
        *,
        timeframe: str,
        limit: int,
        feed: str,
    ) -> dict[str, list[MarketBar]]:
        return {
            symbol: [
                MarketBar(
                    symbol=symbol,
                    open=95.0 + idx,
                    high=96.0 + idx,
                    low=94.0 + idx,
                    close=95.5 + idx,
                    volume=1000.0,
                    timestamp=f"2026-04-{(idx // 24) + 15:02d}T{idx % 24:02d}:00:00Z",
                )
                for idx in range(limit)
            ]
            for symbol in symbols
        }

    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        return []

    def submit_order(self, order):  # type: ignore[override]
        self.submitted_orders.append(order)
        return {"id": "paper-order-1"}

    def cancel_order(self, order_id: str) -> dict:
        self.cancelled_orders.append(order_id)
        return {"id": order_id, "status": "canceled"}


def make_app_config(*, dry_run: bool) -> AppConfig:
    return AppConfig(
        runtime=RuntimeConfig(
            mode="dry_run" if dry_run else "paper",
            asset_class="us_equity",
            crypto_location="us",
            crypto_streaming_enabled=True,
            crypto_stream_cooldown_seconds=5,
            strategy_name="moving_average_momentum",
            bar_timeframe="5Min",
            market_data_feed="iex",
            poll_interval_seconds=300,
            max_cycles=1,
            session_duration_minutes=15,
            dry_run=dry_run,
        ),
        risk=RiskConfig(
            max_notional_per_trade=25.0,
            max_open_positions=2,
            max_trades_per_session=3,
            max_daily_loss=50.0,
            allow_fractional=True,
            allowed_order_types=["market", "limit"],
        ),
        strategy=StrategyConfig(
            name="moving_average_momentum",
            fast_window=5,
            slow_window=20,
            momentum_window=6,
            history_limit=30,
            breakout_lookback=10,
            pullback_window=5,
            pullback_tolerance_percent=1.0,
            trend_strength_threshold_percent=0.2,
            entry_threshold_percent=0.4,
            exit_threshold_percent=-0.3,
            default_notional=10.0,
            stop_loss_percent=3.0,
            trailing_stop_percent=2.0,
            take_profit_percent=6.0,
            allow_sell_signals=True,
        ),
        event_risk=EventRiskConfig(
            enabled=False,
            rss_urls=[],
            symbol_aliases={},
            severity_keywords={"critical": [], "high": [], "medium": [], "low": []},
            recommendation_overrides={},
        ),
        investment_plan=InvestmentPlanConfig(
            starting_budget=250.0,
            cash_reserve_percent=20.0,
            crypto_allocation_percent=50.0,
            equity_allocation_percent=50.0,
            max_symbol_allocation_percent=40.0,
            allowed_symbols=["SPY", "QQQ", "AAPL", "MSFT"],
            preferred_symbols=["SPY", "QQQ"],
            avoided_symbols=[],
            notes="test plan",
        ),
        account_base_url="https://paper-api.alpaca.markets",
        market_data_url="https://data.alpaca.markets",
        api_key="key",
        api_secret="secret",
        watchlist=["SPY"],
        kill_switch=False,
    )


def test_dry_run_skips_order_submission(tmp_path: Path) -> None:
    broker = FakeBroker()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    loop = TradingLoop(
        config=make_app_config(dry_run=True),
        broker=broker,
        risk_manager=RiskManager(make_app_config(dry_run=True).risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert broker.submitted_orders == []
    assert any(event.event_type == "dry_run_order" for event in events)


def test_pause_override_blocks_trade(tmp_path: Path) -> None:
    broker = FakeBroker()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("SPY", "pause_auto")
    loop = TradingLoop(
        config=make_app_config(dry_run=True),
        broker=broker,
        risk_manager=RiskManager(make_app_config(dry_run=True).risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert broker.submitted_orders == []
    assert any(event.event_type == "operator_override_blocked_trade" for event in events)
    assert not any(event.event_type == "dry_run_order" for event in events if event.details.get("symbol") == "SPY")


def test_transient_buy_override_clears_after_cycle(tmp_path: Path) -> None:
    broker = FakeBroker()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("SPY", "buy")
    loop = TradingLoop(
        config=make_app_config(dry_run=True),
        broker=broker,
        risk_manager=RiskManager(make_app_config(dry_run=True).risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert any(event.event_type == "operator_override_forced_buy" for event in events)
    assert "SPY" not in override_store.load()


def test_transient_buy_override_clears_after_risk_block(tmp_path: Path) -> None:
    class BrokerWithPosition(FakeBroker):
        def list_positions(self) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="QQQ",
                    quantity=1.0,
                    market_value=10.0,
                    average_entry_price=10.0,
                )
            ]

    broker = BrokerWithPosition()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("SPY", "buy")
    config = make_app_config(dry_run=True)
    config.risk.max_open_positions = 1
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert any(event.event_type == "risk_decision" and event.message == "Max open positions reached." for event in events)
    assert "SPY" not in override_store.load()


def test_transient_buy_override_clears_after_duplicate_order_block(tmp_path: Path) -> None:
    class BrokerWithOpenOrder(FakeBroker):
        def list_open_orders(self) -> list[OrderSnapshot]:
            return [
                OrderSnapshot(
                    order_id="open-buy-1",
                    symbol="SPY",
                    side="buy",
                    status="accepted",
                    notional=10.0,
                )
            ]

    broker = BrokerWithOpenOrder()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("SPY", "buy")
    loop = TradingLoop(
        config=make_app_config(dry_run=False),
        broker=broker,
        risk_manager=RiskManager(make_app_config(dry_run=False).risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert any(event.event_type == "duplicate_order_block" for event in events)
    assert "SPY" not in override_store.load()


def test_ai_trading_master_off_blocks_entire_loop(tmp_path: Path) -> None:
    broker = FakeBroker()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_ai_trading_enabled(False)
    loop = TradingLoop(
        config=make_app_config(dry_run=True),
        broker=broker,
        risk_manager=RiskManager(make_app_config(dry_run=True).risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert broker.submitted_orders == []
    assert any(event.event_type == "ai_trading_disabled" for event in events)
    assert not any(event.event_type == "signal_generated" for event in events)


def test_sell_override_emits_dry_run_sell(tmp_path: Path) -> None:
    class BrokerWithPosition(FakeBroker):
        def list_positions(self) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="SPY",
                    quantity=3.0,
                    market_value=303.0,
                    average_entry_price=100.0,
                )
            ]

    broker = BrokerWithPosition()
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("SPY", "sell")
    loop = TradingLoop(
        config=make_app_config(dry_run=True),
        broker=broker,
        risk_manager=RiskManager(make_app_config(dry_run=True).risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert any(event.event_type == "operator_override_forced_sell" for event in events)
    sell_events = [event for event in events if event.event_type == "dry_run_order" and event.details.get("side") == "sell"]
    assert sell_events


def test_projected_positions_enforce_max_open_positions(tmp_path: Path) -> None:
    broker = FakeBroker()
    config = make_app_config(dry_run=True)
    config.risk.max_open_positions = 1
    config.watchlist = ["SPY", "QQQ"]
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    events = loop.run_once()

    buy_dry_runs = [event for event in events if event.event_type == "dry_run_order" and event.details.get("side") == "buy"]
    blocked = [event for event in events if event.event_type == "risk_decision" and event.message == "Max open positions reached."]

    assert len(buy_dry_runs) == 1
    assert blocked


def test_open_buy_order_blocks_duplicate_submission(tmp_path: Path) -> None:
    class BrokerWithOpenBuy(FakeBroker):
        def list_open_orders(self) -> list[OrderSnapshot]:
            return [
                OrderSnapshot(order_id="open-1", symbol="SPY", side="buy", status="open")
            ]

    broker = BrokerWithOpenBuy()
    config = make_app_config(dry_run=True)
    config.watchlist = ["SPY"]
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    events = loop.run_once()

    assert not any(event.event_type == "dry_run_order" for event in events)
    assert any(event.event_type == "duplicate_order_block" for event in events)


def test_investment_plan_budget_blocks_trade_after_budget_used(tmp_path: Path) -> None:
    broker = FakeBroker()
    config = make_app_config(dry_run=True)
    config.investment_plan.starting_budget = 20.0
    config.investment_plan.cash_reserve_percent = 0.0
    config.investment_plan.crypto_allocation_percent = 0.0
    config.investment_plan.equity_allocation_percent = 100.0
    config.investment_plan.max_symbol_allocation_percent = 100.0
    config.risk.max_open_positions = 10
    config.watchlist = ["SPY", "QQQ", "AAPL"]
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    events = loop.run_once()

    buy_dry_runs = [event for event in events if event.event_type == "dry_run_order" and event.details.get("side") == "buy"]
    plan_blocks = [event for event in events if event.event_type == "investment_plan_block"]

    assert len(buy_dry_runs) == 2
    assert any("budget cap" in event.message.lower() for event in plan_blocks)


def test_crypto_stash_budget_blocks_when_crypto_bucket_is_full(tmp_path: Path) -> None:
    class BrokerWithCryptoPosition(FakeBroker):
        def list_positions(self) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="SOL/USD",
                    quantity=10.0,
                    market_value=95.0,
                    average_entry_price=9.5,
                )
            ]

    broker = BrokerWithCryptoPosition()
    config = make_app_config(dry_run=True)
    config.runtime.asset_class = "mixed"
    config.watchlist = ["BTC/USD"]
    config.investment_plan.allowed_symbols = ["BTC/USD", "SOL/USD"]
    config.investment_plan.preferred_symbols = ["BTC/USD"]
    config.investment_plan.starting_budget = 130.0
    config.investment_plan.cash_reserve_percent = 0.0
    config.investment_plan.crypto_allocation_percent = 75.0
    config.investment_plan.equity_allocation_percent = 25.0

    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("BTC/USD", "buy")
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert any(
        event.event_type == "investment_plan_block" and "crypto stash" in event.message.lower()
        for event in events
    )


def test_investment_plan_preferred_symbols_run_first(tmp_path: Path) -> None:
    broker = FakeBroker()
    config = make_app_config(dry_run=True)
    config.watchlist = ["SPY", "QQQ"]
    config.investment_plan.preferred_symbols = ["QQQ"]
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    events = loop.run_once()

    signal_symbols = [event.details.get("symbol") for event in events if event.event_type == "signal_generated"]

    assert signal_symbols[:2] == ["QQQ", "SPY"]


def test_strategy_breakout_buy_emits_setup_details(tmp_path: Path) -> None:
    broker = FakeBroker()
    config = make_app_config(dry_run=True)
    config.strategy.fast_window = 3
    config.strategy.slow_window = 5
    config.strategy.momentum_window = 3
    config.strategy.breakout_lookback = 5
    config.strategy.pullback_window = 3
    config.strategy.history_limit = 12
    config.watchlist = ["SPY"]
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    events = loop.run_once()

    signal_event = next(event for event in events if event.event_type == "signal_generated")
    assert signal_event.details["setup"] in {"BREAKOUT_BUY", "PULLBACK_BUY", "TREND_WATCH"}
    assert "breakout_level" in signal_event.details
    assert "target_price" in signal_event.details


def test_strategy_sell_signal_submits_dry_run_sell_when_trend_breaks(tmp_path: Path) -> None:
    class BrokerWithLosingPosition(FakeBroker):
        def list_positions(self) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="SPY",
                    quantity=2.0,
                    market_value=190.0,
                    average_entry_price=100.0,
                )
            ]

        def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
            return {
                "SPY": MarketBar(
                    symbol="SPY",
                    open=94.0,
                    high=95.0,
                    low=92.0,
                    close=93.0,
                    volume=1000.0,
                    timestamp="2026-04-15T12:00:00Z",
                )
            }

        def get_historical_bars(
            self,
            symbols: list[str],
            *,
            timeframe: str,
            limit: int,
            feed: str,
        ) -> dict[str, list[MarketBar]]:
            closes = [110, 109, 108, 107, 106, 104, 102, 100, 97, 95, 93]
            return {
                "SPY": [
                    MarketBar(
                        symbol="SPY",
                        open=value + 0.5,
                        high=value + 1.0,
                        low=value - 1.0,
                        close=value,
                        volume=1000.0,
                        timestamp=f"2026-04-15T{idx:02d}:00:00Z",
                    )
                    for idx, value in enumerate(closes)
                ]
            }

    broker = BrokerWithLosingPosition()
    config = make_app_config(dry_run=True)
    config.strategy.fast_window = 3
    config.strategy.slow_window = 5
    config.strategy.momentum_window = 3
    config.strategy.history_limit = 11
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    events = loop.run_once()

    sell_events = [event for event in events if event.event_type == "dry_run_order" and event.details.get("side") == "sell"]
    assert sell_events


def test_crypto_orders_use_gtc_time_in_force(tmp_path: Path) -> None:
    broker = FakeBroker()
    config = make_app_config(dry_run=False)
    config.runtime.asset_class = "crypto"  # type: ignore[attr-defined]
    config.watchlist = ["BTC/USD"]
    config.investment_plan.allowed_symbols = ["BTC/USD"]  # type: ignore[attr-defined]
    config.investment_plan.preferred_symbols = ["BTC/USD"]  # type: ignore[attr-defined]
    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("BTC/USD", "buy")
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=override_store,
    )

    loop.run_once()

    assert broker.submitted_orders
    assert broker.submitted_orders[0].time_in_force == "gtc"


def test_mixed_mode_routes_crypto_symbols_to_gtc(tmp_path: Path) -> None:
    broker = FakeBroker()
    config = make_app_config(dry_run=False)
    config.runtime.asset_class = "mixed"
    config.watchlist = ["BTC/USD"]
    config.investment_plan.allowed_symbols = ["BTC/USD"]
    config.investment_plan.preferred_symbols = ["BTC/USD"]

    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("BTC/USD", "buy")
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=override_store,
    )

    loop.run_once()

    assert broker.submitted_orders[0].symbol == "BTC/USD"
    assert broker.submitted_orders[0].time_in_force == "gtc"


def test_mixed_mode_position_cap_is_checked_per_asset_class(tmp_path: Path) -> None:
    class BrokerWithEquityPosition(FakeBroker):
        def list_positions(self) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="AAPL",
                    quantity=1.0,
                    market_value=100.0,
                    average_entry_price=100.0,
                )
            ]

    broker = BrokerWithEquityPosition()
    config = make_app_config(dry_run=False)
    config.runtime.asset_class = "mixed"
    config.risk.max_open_positions = 1
    config.watchlist = ["BTC/USD"]
    config.investment_plan.allowed_symbols = ["AAPL", "BTC/USD"]
    config.investment_plan.preferred_symbols = ["BTC/USD"]

    override_store = OperatorOverrideStore(tmp_path / "operator_overrides.json")
    override_store.set_override("BTC/USD", "buy")
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=RiskManager(config.risk),
        override_store=override_store,
    )

    events = loop.run_once()

    assert broker.submitted_orders
    assert not any(
        event.event_type == "risk_decision" and event.message == "Max open positions reached."
        for event in events
        if event.details.get("symbol") == "BTC/USD"
    )
