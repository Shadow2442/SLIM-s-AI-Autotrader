import json
from pathlib import Path

from autotrade.brokers.base import BrokerAdapter
from autotrade.config import AppConfig, EventRiskConfig, InvestmentPlanConfig, RiskConfig, RuntimeConfig, StrategyConfig
from autotrade.models import AccountSnapshot, MarketBar, OrderRequest, OrderSnapshot, PositionSnapshot, RunEvent
from autotrade.services.dashboard import DashboardService


class FakeDashboardBroker(BrokerAdapter):
    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(equity=1200.0, buying_power=700.0, cash=500.0)

    def list_positions(self) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                symbol="AAPL",
                quantity=2.0,
                market_value=200.0,
                average_entry_price=95.0,
                unrealized_pl=10.0,
                unrealized_pl_percent=0.05,
            )
        ]

    def list_open_orders(self) -> list[OrderSnapshot]:
        return [OrderSnapshot(order_id="1", symbol="AAPL", side="buy", status="open", notional=10.0)]

    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        return [
            OrderSnapshot(
                order_id="2",
                symbol="AAPL",
                side="buy",
                status="filled",
                quantity=1.0,
                raw={"filled_at": "2026-04-15T01:00:00Z", "filled_avg_price": "100.0"},
            )
        ]

    def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
        return {
            "AAPL": MarketBar(
                symbol="AAPL",
                open=100.1,
                high=101.1,
                low=99.7,
                close=100.5,
                volume=1000.0,
                timestamp="2026-04-15T03:00:00Z",
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
        return {
            "AAPL": [
                MarketBar(
                    symbol="AAPL",
                    open=98.0 + idx,
                    high=99.0 + idx,
                    low=97.0 + idx,
                    close=98.5 + idx,
                    volume=1000.0 + idx,
                    timestamp=f"2026-04-15T{idx:02d}:00:00Z",
                )
                for idx in range(3)
            ]
        }

    def submit_order(self, order: OrderRequest) -> dict:
        return {}

    def cancel_order(self, order_id: str) -> dict:
        return {"id": order_id, "status": "canceled"}


class FakeMixedRecentOrdersBroker(FakeDashboardBroker):
    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        orders: list[OrderSnapshot] = []
        for idx in range(8):
            orders.append(
                OrderSnapshot(
                    order_id=f"crypto-{idx}",
                    symbol="BTC/USD" if idx % 2 == 0 else "SOL/USD",
                    side="buy" if idx % 2 == 0 else "sell",
                    status="filled",
                    quantity=0.1,
                    notional=10.0 + idx,
                    raw={
                        "filled_at": f"2026-04-17T01:{50 - idx:02d}:00Z",
                        "filled_avg_price": str(70000 + idx),
                    },
                )
            )
        orders.extend(
            [
                OrderSnapshot(
                    order_id="equity-1",
                    symbol="AAPL",
                    side="buy",
                    status="filled",
                    quantity=1.0,
                    raw={"filled_at": "2026-04-17T01:10:00Z", "filled_avg_price": "200.0"},
                ),
                OrderSnapshot(
                    order_id="equity-2",
                    symbol="QQQ",
                    side="sell",
                    status="filled",
                    quantity=1.0,
                    raw={"filled_at": "2026-04-17T01:05:00Z", "filled_avg_price": "500.0"},
                ),
            ]
        )
        return orders


def make_app_config() -> AppConfig:
    return AppConfig(
        runtime=RuntimeConfig(
            mode="dry_run",
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
            dry_run=True,
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
            enabled=True,
            rss_urls=[],
            symbol_aliases={"AAPL": ["apple"]},
            severity_keywords={"critical": [], "high": [], "medium": [], "low": []},
            recommendation_overrides={
                "critical": "EXIT_NOW",
                "high": "SELL_OR_HEDGE",
                "medium": "WATCH_CLOSELY",
                "low": "WATCH",
            },
        ),
        investment_plan=InvestmentPlanConfig(
            starting_budget=250.0,
            cash_reserve_percent=20.0,
            crypto_allocation_percent=50.0,
            equity_allocation_percent=50.0,
            max_symbol_allocation_percent=40.0,
            allowed_symbols=["AAPL"],
            preferred_symbols=["AAPL"],
            avoided_symbols=[],
            notes="test plan",
        ),
        account_base_url="https://paper-api.alpaca.markets",
        market_data_url="https://data.alpaca.markets",
        api_key="key",
        api_secret="secret",
        watchlist=["AAPL"],
        kill_switch=False,
    )


def test_dashboard_service_writes_json_and_html(tmp_path: Path) -> None:
    service = DashboardService(broker=FakeDashboardBroker(), config=make_app_config(), output_dir=tmp_path)
    snapshot = service.build_snapshot(alerts=[RunEvent(event_type="test_alert", message="watch", details={})])

    json_path, html_path = service.write_reports(snapshot)
    operator_path = tmp_path / "operator_window.html"

    assert json_path.exists()
    assert html_path.exists()
    assert operator_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["recommendations"][0]["symbol"] == "AAPL"
    assert payload["recommendations"][0]["asset_class"] == "us_equity"
    assert payload["asset_charts"][0]["symbol"] == "AAPL"
    assert payload["filled_position_cost_basis"] == 190.0
    assert payload["pending_open_order_value"] == 10.0
    assert payload["open_order_status_summary"] == "1 open"
    assert payload["open_order_fill_hint"] == "Open orders are pending broker execution."
    assert payload["open_order_details"][0]["symbol"] == "AAPL"
    assert payload["recommendations"][0]["recommendation"]
    assert "signal_confidence" in payload["recommendations"][0]
    assert "signal_reason" in payload["recommendations"][0]
    assert "symbol_performance" in payload
    assert "strategy_performance" in payload
    assert "Autotrade Portfolio Dashboard" in html_path.read_text(encoding="utf-8")
    operator_html = operator_path.read_text(encoding="utf-8")
    assert "Slim's AI Autotrader" in operator_html
    assert 'rel="icon"' in operator_html
    assert "data:image/svg+xml" in operator_html
    assert "AI Trading" in operator_html
    assert "runner-badge" in operator_html
    assert "runtime-detail" in operator_html
    assert "Master Session" in operator_html
    assert "Equities desk follows the timer" in operator_html
    assert "Crypto desk can jump early" in operator_html
    assert "Start Bot" in operator_html
    assert "Start Run Now" in operator_html
    assert "Investment Plan" in operator_html
    assert "Broker cash is shared across the Alpaca account." in operator_html
    assert "Move USD between wallets" in operator_html
    assert "Bot Cash Buffer" in operator_html
    assert "Run (min)" in operator_html
    assert "Process / Lock Status" in operator_html
    assert "Live Activity" in operator_html
    assert "bot-pid" in operator_html
    assert "session-lock-pid" in operator_html
    assert "renderProcessStatus" in operator_html
    assert "renderLiveActivity" in operator_html
    assert "Open Order Queue" in operator_html
    assert "Total Spent" in operator_html
    assert "Current Value" in operator_html
    assert "Order Status" in operator_html
    assert "Tracking 1 assets" in operator_html
    assert "Equities 1" in operator_html
    assert "Equities Desk" in operator_html
    assert "Crypto Desk" in operator_html
    assert "All Markets" in operator_html
    assert "Open orders are pending broker execution." in operator_html
    assert "10.00" in operator_html
    assert "Suggested Buy Zone" in operator_html
    assert "Fast / Slow MA" in operator_html
    assert "Signal Basis" in operator_html
    assert "pollForDashboardRefresh" in operator_html
    assert "pollRuntimeState" in operator_html
    assert "playTransactionTone" in operator_html
    assert "syncTransactionNotification" in operator_html
    assert "--bg:#08111a" in operator_html


def test_dashboard_event_alert_overrides_recommendation(tmp_path: Path) -> None:
    service = DashboardService(broker=FakeDashboardBroker(), config=make_app_config(), output_dir=tmp_path)
    snapshot = service.build_snapshot(
        alerts=[
            RunEvent(
                event_type="event_risk_alert",
                message="Security breach",
                details={
                    "symbol": "AAPL",
                    "severity": "critical",
                    "summary": "Apple suffers a major security breach.",
                    "recommendation_override": "EXIT_NOW",
                },
            )
        ]
    )

    recommendation = snapshot.recommendations[0]

    assert recommendation.symbol == "AAPL"
    assert recommendation.recommendation == "EXIT_NOW"
    assert recommendation.risk_level == "critical"
    assert "security breach" in recommendation.rationale.lower()


def test_recent_order_activity_keeps_crypto_and_equity_visible(tmp_path: Path) -> None:
    service = DashboardService(broker=FakeMixedRecentOrdersBroker(), config=make_app_config(), output_dir=tmp_path)

    snapshot = service.build_snapshot()

    asset_classes = {item.asset_class for item in snapshot.recent_order_activity}
    symbols = {item.symbol for item in snapshot.recent_order_activity}

    assert "crypto" in asset_classes
    assert "us_equity" in asset_classes
    assert {"AAPL", "QQQ"} & symbols
    assert {"BTC/USD", "SOL/USD"} & symbols


def test_dashboard_operator_override_adjusts_recommendation(tmp_path: Path) -> None:
    service = DashboardService(broker=FakeDashboardBroker(), config=make_app_config(), output_dir=tmp_path)
    (tmp_path / "operator_overrides.json").write_text(
        json.dumps({"AAPL": {"action": "pause_auto", "updated_at": "2026-04-16T20:00:00Z"}}),
        encoding="utf-8",
    )

    snapshot = service.build_snapshot()
    recommendation = snapshot.recommendations[0]

    assert recommendation.recommendation == "AUTO_PAUSED"
    assert "paused automated trading" in recommendation.rationale.lower()


def test_dashboard_sell_recommendation_explains_bearish_break(tmp_path: Path) -> None:
    class BearishBroker(FakeDashboardBroker):
        def list_positions(self) -> list[PositionSnapshot]:
            return [
                PositionSnapshot(
                    symbol="AAPL",
                    quantity=2.0,
                    market_value=180.0,
                    average_entry_price=105.0,
                    unrealized_pl=-20.0,
                    unrealized_pl_percent=-0.10,
                )
            ]

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
                "AAPL": [
                    MarketBar(
                        symbol="AAPL",
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

    service = DashboardService(broker=BearishBroker(), config=make_app_config(), output_dir=tmp_path)
    service._config.strategy.fast_window = 3  # type: ignore[attr-defined]
    service._config.strategy.slow_window = 5  # type: ignore[attr-defined]
    service._config.strategy.momentum_window = 3  # type: ignore[attr-defined]
    snapshot = service.build_snapshot()

    recommendation = snapshot.recommendations[0]

    assert recommendation.signal_action == "SELL"
    assert recommendation.recommendation == "SELL_OR_REDUCE"
    assert "fell below the slow moving average" in recommendation.rationale.lower()


def test_dashboard_records_fractional_quantity_from_dry_run_notional(tmp_path: Path) -> None:
    service = DashboardService(broker=FakeDashboardBroker(), config=make_app_config(), output_dir=tmp_path)

    service.record_trade_markers_from_events(
        [
            RunEvent(
                event_type="dry_run_order",
                message="Order skipped due to dry-run mode.",
                details={
                    "symbol": "AAPL",
                    "side": "buy",
                    "notional": 10.0,
                    "price": 100.0,
                    "timestamp": "2026-04-16T20:00:00Z",
                },
            )
        ]
    )

    records = service._history_store.load_trade_records(symbol="AAPL")  # type: ignore[attr-defined]

    assert records[-1].quantity == 0.1


def test_operator_window_buy_zone_stays_below_current_price(tmp_path: Path) -> None:
    service = DashboardService(broker=FakeDashboardBroker(), config=make_app_config(), output_dir=tmp_path)
    snapshot = service.build_snapshot()

    operator_html = service._render_operator_window(snapshot)  # type: ignore[attr-defined]

    assert "Suggested Buy Zone</span><strong>$98.70" in operator_html


def test_crypto_open_orders_show_24_7_fill_hint(tmp_path: Path) -> None:
    class CryptoDashboardBroker(FakeDashboardBroker):
        def list_open_orders(self) -> list[OrderSnapshot]:
            return [
                OrderSnapshot(
                    order_id="btc-open-1",
                    symbol="BTC/USD",
                    side="buy",
                    status="accepted",
                    notional=25.0,
                    raw={"submitted_at": "2026-04-16T21:52:01.309947863Z", "type": "market"},
                )
            ]

        def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
            return {
                "BTC/USD": MarketBar(
                    symbol="BTC/USD",
                    open=64000.0,
                    high=64200.0,
                    low=63800.0,
                    close=64100.0,
                    volume=250.0,
                    timestamp="2026-04-16T21:55:00Z",
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
            return {
                "BTC/USD": [
                    MarketBar(
                        symbol="BTC/USD",
                        open=63900.0 + idx,
                        high=64000.0 + idx,
                        low=63800.0 + idx,
                        close=63950.0 + idx,
                        volume=200.0 + idx,
                        timestamp=f"2026-04-16T{idx:02d}:00:00Z",
                    )
                    for idx in range(limit)
                ]
            }

    config = make_app_config()
    config.runtime.asset_class = "crypto"  # type: ignore[attr-defined]
    config.runtime.crypto_location = "us"  # type: ignore[attr-defined]
    config.watchlist = ["BTC/USD"]
    config.investment_plan.allowed_symbols = ["BTC/USD"]  # type: ignore[attr-defined]
    config.investment_plan.preferred_symbols = ["BTC/USD"]  # type: ignore[attr-defined]
    service = DashboardService(broker=CryptoDashboardBroker(), config=config, output_dir=tmp_path)

    snapshot = service.build_snapshot()

    assert snapshot.open_order_fill_hint == "Crypto trades 24/7; accepted orders can fill anytime if marketable."
