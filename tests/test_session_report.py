from datetime import datetime, timezone
from pathlib import Path

from autotrade.models import DashboardSnapshot, RunEvent, StrategyPerformance, SymbolPerformance
from autotrade.services.session_report import SessionReportService


def test_session_report_service_writes_json_and_html(tmp_path: Path) -> None:
    service = SessionReportService(output_dir=tmp_path)
    snapshot = DashboardSnapshot(
        generated_at=datetime(2026, 4, 16, 21, 0, tzinfo=timezone.utc),
        total_equity=101234.5,
        cash=90000.0,
        buying_power=180000.0,
        filled_position_cost_basis=11100.0,
        invested_value=11234.5,
        open_orders_count=1,
        pending_open_order_value=10.0,
        open_order_status_summary="1 open",
        open_order_fill_hint="Open orders are pending broker execution.",
        open_order_details=[],
        recent_order_activity=[],
        recommendations=[],
        alerts=[],
        portfolio_history=[],
        asset_charts=[],
        symbol_performance=[
            SymbolPerformance(
                symbol="AAPL",
                realized_pl=50.0,
                realized_trades=2,
                open_quantity=0.0,
                average_cost=0.0,
                last_strategy="moving_average_momentum",
            ),
            SymbolPerformance(
                symbol="MSFT",
                realized_pl=-10.0,
                realized_trades=1,
                open_quantity=0.0,
                average_cost=0.0,
                last_strategy="moving_average_momentum",
            ),
        ],
        strategy_performance=[
            StrategyPerformance(
                strategy_name="moving_average_momentum",
                realized_pl=40.0,
                realized_trades=3,
            )
        ],
    )
    events = [
        RunEvent(event_type="order_submitted", message="buy", details={"symbol": "AAPL"}),
        RunEvent(event_type="ai_trading_cycle_blocked", message="blocked", details={}),
    ]

    json_path, html_path = service.write_report(
        session_minutes=15,
        completed_cycles=2,
        alerts=events,
        final_snapshot=snapshot,
    )

    assert json_path.exists()
    assert html_path.exists()
    assert "Session Report" in html_path.read_text(encoding="utf-8")
    assert '"trade_count": 1' in json_path.read_text(encoding="utf-8")
