from pathlib import Path

from autotrade.models import ChartPoint, DashboardSnapshot, TradeMarker, TradeRecord, utc_now
from autotrade.services.history import HistoryStore


def test_history_store_appends_and_reads_back_data(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    snapshot = DashboardSnapshot(
        generated_at=utc_now(),
        total_equity=1000.0,
        cash=400.0,
        buying_power=600.0,
        filled_position_cost_basis=550.0,
        invested_value=600.0,
        open_orders_count=0,
        pending_open_order_value=0.0,
        open_order_status_summary="No open orders",
        open_order_fill_hint="No pending fills.",
        open_order_details=[],
        recent_order_activity=[],
        recommendations=[],
        alerts=[],
        portfolio_history=[],
        asset_charts=[],
        symbol_performance=[],
        strategy_performance=[],
    )

    store.append_dashboard_snapshot(snapshot)
    store.append_trade_marker(
        TradeMarker(
            symbol="AAPL",
            side="buy",
            timestamp="2026-04-15T01:00:00Z",
            price=101.0,
            note="dry run",
        )
    )

    portfolio = store.load_portfolio_history()
    markers = store.load_trade_markers(symbol="AAPL")

    assert isinstance(portfolio[0], ChartPoint)
    assert markers[0].symbol == "AAPL"


def test_history_store_summarizes_realized_performance(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.append_trade_record(
        TradeRecord(
            symbol="AAPL",
            side="buy",
            timestamp="2026-04-15T01:00:00Z",
            price=100.0,
            quantity=2.0,
            strategy_name="moving_average_momentum",
            source="test",
            note="entry",
        )
    )
    store.append_trade_record(
        TradeRecord(
            symbol="AAPL",
            side="sell",
            timestamp="2026-04-15T02:00:00Z",
            price=110.0,
            quantity=1.0,
            strategy_name="moving_average_momentum",
            source="test",
            note="partial exit",
        )
    )

    symbol_perf, strategy_perf = store.summarize_performance()

    assert symbol_perf[0].realized_pl == 10.0
    assert strategy_perf[0].realized_pl == 10.0
