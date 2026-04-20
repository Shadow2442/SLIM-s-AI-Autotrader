from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from autotrade.models import DashboardSnapshot, RunEvent, SymbolPerformance, StrategyPerformance


class SessionReportService:
    def __init__(self, *, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def write_report(
        self,
        *,
        session_minutes: int,
        completed_cycles: int,
        alerts: list[RunEvent],
        final_snapshot: DashboardSnapshot,
    ) -> tuple[Path, Path]:
        trades = [event for event in alerts if event.event_type in {"order_submitted", "dry_run_order"}]
        blocked = [
            event
            for event in alerts
            if event.event_type
            in {
                "ai_trading_cycle_blocked",
                "operator_override_blocked_trade",
                "duplicate_order_block",
                "risk_rejected",
            }
        ]
        warnings = [event for event in alerts if "warning" in event.event_type or "block" in event.event_type]
        symbol_perf = list(final_snapshot.symbol_performance)
        strategy_perf = list(final_snapshot.strategy_performance)
        best_symbol = max(symbol_perf, key=lambda item: item.realized_pl, default=None)
        worst_symbol = min(symbol_perf, key=lambda item: item.realized_pl, default=None)
        top_strategy = max(strategy_perf, key=lambda item: item.realized_pl, default=None)
        event_counter = Counter(event.event_type for event in alerts)

        payload = {
            "generated_at": final_snapshot.generated_at.isoformat(),
            "session_minutes": session_minutes,
            "completed_cycles": completed_cycles,
            "total_equity": final_snapshot.total_equity,
            "cash": final_snapshot.cash,
            "invested_value": final_snapshot.invested_value,
            "open_orders_count": final_snapshot.open_orders_count,
            "trade_count": len(trades),
            "blocked_count": len(blocked),
            "warning_count": len(warnings),
            "best_symbol": asdict(best_symbol) if best_symbol else None,
            "worst_symbol": asdict(worst_symbol) if worst_symbol else None,
            "top_strategy": asdict(top_strategy) if top_strategy else None,
            "symbol_performance": [asdict(item) for item in symbol_perf],
            "strategy_performance": [asdict(item) for item in strategy_perf],
            "event_counts": dict(sorted(event_counter.items())),
            "recent_alerts": [
                {
                    "event_type": event.event_type,
                    "message": event.message,
                    "created_at": event.created_at.isoformat(),
                    "details": event.details,
                }
                for event in alerts[-20:]
            ],
        }

        json_path = self._output_dir / "session_report.json"
        html_path = self._output_dir / "session_report.html"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        html_path.write_text(self._render_html(payload), encoding="utf-8")
        return json_path, html_path

    def _render_html(self, payload: dict) -> str:
        best_symbol = payload.get("best_symbol") or {}
        worst_symbol = payload.get("worst_symbol") or {}
        top_strategy = payload.get("top_strategy") or {}
        event_rows = "".join(
            f"<tr><td>{event_type}</td><td>{count}</td></tr>"
            for event_type, count in payload.get("event_counts", {}).items()
        ) or "<tr><td colspan='2'>No events captured.</td></tr>"
        recent_rows = "".join(
            f"<li><strong>{item['event_type']}</strong> {item['message']}</li>"
            for item in payload.get("recent_alerts", [])
        ) or "<li>No recent session alerts.</li>"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Slim's AI Autotrader Session Report</title>
  <style>
    body {{ margin:0; font-family:'Segoe UI',Tahoma,sans-serif; background:#08111a; color:#e9f1f7; }}
    .wrap {{ max-width:1080px; margin:0 auto; padding:28px 22px 40px; }}
    .hero, .panel {{ background:#101c28; border:1px solid #22384b; border-radius:18px; padding:20px; margin-bottom:18px; }}
    h1,h2,p {{ margin:0; }}
    .sub {{ margin-top:8px; color:#91a6b7; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px; }}
    .stat {{ background:rgba(255,255,255,0.03); border:1px solid #22384b; border-radius:14px; padding:12px; }}
    .stat span {{ display:block; color:#91a6b7; font-size:0.82rem; }}
    .stat strong {{ display:block; font-size:1.2rem; margin-top:6px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    table {{ width:100%; border-collapse:collapse; }}
    td, th {{ padding:8px 6px; border-bottom:1px solid rgba(145,166,183,0.15); text-align:left; }}
    ul {{ margin:12px 0 0; padding-left:18px; color:#d7e5f0; }}
    @media (max-width:900px) {{ .stats,.grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Slim's AI Autotrader Session Report</h1>
      <p class="sub">Generated {payload['generated_at']} after {payload['session_minutes']} minute(s) and {payload['completed_cycles']} completed cycle(s).</p>
      <div class="stats">
        <div class="stat"><span>Total Equity</span><strong>${payload['total_equity']:.2f}</strong></div>
        <div class="stat"><span>Trades</span><strong>{payload['trade_count']}</strong></div>
        <div class="stat"><span>Blocked Actions</span><strong>{payload['blocked_count']}</strong></div>
        <div class="stat"><span>Open Orders</span><strong>{payload['open_orders_count']}</strong></div>
      </div>
    </section>
    <div class="grid">
      <section class="panel">
        <h2>Highlights</h2>
        <p class="sub">Best symbol: {best_symbol.get('symbol', 'n/a')} ({best_symbol.get('realized_pl', 0):.2f})</p>
        <p class="sub">Worst symbol: {worst_symbol.get('symbol', 'n/a')} ({worst_symbol.get('realized_pl', 0):.2f})</p>
        <p class="sub">Top strategy: {top_strategy.get('strategy_name', 'n/a')} ({top_strategy.get('realized_pl', 0):.2f})</p>
      </section>
      <section class="panel">
        <h2>Recent Session Alerts</h2>
        <ul>{recent_rows}</ul>
      </section>
    </div>
    <section class="panel">
      <h2>Event Counts</h2>
      <table>
        <thead><tr><th>Event</th><th>Count</th></tr></thead>
        <tbody>{event_rows}</tbody>
      </table>
    </section>
  </div>
</body>
</html>"""
