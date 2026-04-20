from __future__ import annotations

import json
from pathlib import Path

from autotrade.models import (
    ChartPoint,
    DashboardSnapshot,
    StrategyPerformance,
    SymbolPerformance,
    TradeMarker,
    TradeRecord,
)


class HistoryStore:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._portfolio_history_path = self._base_dir / "portfolio_history.jsonl"
        self._trade_history_path = self._base_dir / "trade_markers.jsonl"
        self._trade_records_path = self._base_dir / "trade_records.jsonl"

    def append_dashboard_snapshot(self, snapshot: DashboardSnapshot) -> None:
        payload = {
            "generated_at": snapshot.generated_at.isoformat(),
            "total_equity": snapshot.total_equity,
            "cash": snapshot.cash,
            "buying_power": snapshot.buying_power,
            "invested_value": snapshot.invested_value,
        }
        with self._portfolio_history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def load_portfolio_history(self, *, limit: int = 200) -> list[ChartPoint]:
        if not self._portfolio_history_path.exists():
            return []
        lines = self._portfolio_history_path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [
            ChartPoint(timestamp=item["generated_at"], value=float(item["total_equity"]))
            for item in (json.loads(line) for line in lines if line.strip())
        ]

    def append_trade_marker(self, marker: TradeMarker) -> None:
        with self._trade_history_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "symbol": marker.symbol,
                        "side": marker.side,
                        "timestamp": marker.timestamp,
                        "price": marker.price,
                        "note": marker.note,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    def load_trade_markers(self, *, symbol: str | None = None, limit: int = 200) -> list[TradeMarker]:
        if not self._trade_history_path.exists():
            return []
        lines = self._trade_history_path.read_text(encoding="utf-8").splitlines()[-limit:]
        markers = [
            TradeMarker(
                symbol=item["symbol"],
                side=item["side"],
                timestamp=item["timestamp"],
                price=float(item["price"]),
                note=item["note"],
            )
            for item in (json.loads(line) for line in lines if line.strip())
        ]
        if symbol is not None:
            markers = [marker for marker in markers if marker.symbol == symbol]
        return markers

    def append_trade_record(self, record: TradeRecord) -> None:
        with self._trade_records_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "symbol": record.symbol,
                        "side": record.side,
                        "timestamp": record.timestamp,
                        "price": record.price,
                        "quantity": record.quantity,
                        "strategy_name": record.strategy_name,
                        "source": record.source,
                        "note": record.note,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    def load_trade_records(self, *, symbol: str | None = None, limit: int = 500) -> list[TradeRecord]:
        if not self._trade_records_path.exists():
            return []
        lines = self._trade_records_path.read_text(encoding="utf-8").splitlines()[-limit:]
        records = [
            TradeRecord(
                symbol=item["symbol"],
                side=item["side"],
                timestamp=item["timestamp"],
                price=float(item["price"]),
                quantity=float(item["quantity"]),
                strategy_name=item["strategy_name"],
                source=item["source"],
                note=item["note"],
            )
            for item in (json.loads(line) for line in lines if line.strip())
        ]
        if symbol is not None:
            records = [record for record in records if record.symbol == symbol]
        return records

    def summarize_performance(
        self,
        *,
        limit: int = 1000,
    ) -> tuple[list[SymbolPerformance], list[StrategyPerformance]]:
        records = self.load_trade_records(limit=limit)
        symbol_state: dict[str, dict] = {}
        strategy_state: dict[str, dict] = {}

        for record in sorted(records, key=lambda item: item.timestamp):
            symbol_bucket = symbol_state.setdefault(
                record.symbol,
                {
                    "realized_pl": 0.0,
                    "realized_trades": 0,
                    "open_quantity": 0.0,
                    "average_cost": 0.0,
                    "last_strategy": record.strategy_name,
                },
            )
            strategy_bucket = strategy_state.setdefault(
                record.strategy_name,
                {"realized_pl": 0.0, "realized_trades": 0},
            )
            symbol_bucket["last_strategy"] = record.strategy_name

            if record.side.lower() == "buy":
                current_qty = symbol_bucket["open_quantity"]
                current_cost = symbol_bucket["average_cost"]
                new_qty = current_qty + record.quantity
                if new_qty > 0:
                    symbol_bucket["average_cost"] = ((current_qty * current_cost) + (record.quantity * record.price)) / new_qty
                symbol_bucket["open_quantity"] = new_qty
                continue

            sell_qty = min(record.quantity, symbol_bucket["open_quantity"])
            realized_pl = (record.price - symbol_bucket["average_cost"]) * sell_qty
            symbol_bucket["realized_pl"] += realized_pl
            symbol_bucket["realized_trades"] += 1
            symbol_bucket["open_quantity"] = max(symbol_bucket["open_quantity"] - sell_qty, 0.0)
            if symbol_bucket["open_quantity"] == 0:
                symbol_bucket["average_cost"] = 0.0

            strategy_bucket["realized_pl"] += realized_pl
            strategy_bucket["realized_trades"] += 1

        symbol_performance = [
            SymbolPerformance(
                symbol=symbol,
                realized_pl=round(bucket["realized_pl"], 2),
                realized_trades=bucket["realized_trades"],
                open_quantity=round(bucket["open_quantity"], 6),
                average_cost=round(bucket["average_cost"], 4),
                last_strategy=bucket["last_strategy"],
            )
            for symbol, bucket in sorted(symbol_state.items())
        ]
        strategy_performance = [
            StrategyPerformance(
                strategy_name=strategy_name,
                realized_pl=round(bucket["realized_pl"], 2),
                realized_trades=bucket["realized_trades"],
            )
            for strategy_name, bucket in sorted(strategy_state.items())
        ]
        return symbol_performance, strategy_performance
