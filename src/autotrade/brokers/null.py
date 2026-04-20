from __future__ import annotations

from autotrade.brokers.base import BrokerAdapter
from autotrade.models import AccountSnapshot, MarketBar, OrderRequest, OrderSnapshot, PositionSnapshot


class NullBrokerAdapter(BrokerAdapter):
    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(equity=100000.0, buying_power=100000.0, cash=100000.0)

    def list_positions(self) -> list[PositionSnapshot]:
        return []

    def list_open_orders(self) -> list[OrderSnapshot]:
        return []

    def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
        bars: dict[str, MarketBar] = {}
        for index, symbol in enumerate(symbols, start=1):
            close = 95.0 + index + 29 * 0.35
            bars[symbol] = MarketBar(
                symbol=symbol,
                open=close - 0.4,
                high=close + 0.5,
                low=close - 0.8,
                close=close,
                volume=1000 + index,
                timestamp="2026-04-02T06:00:00Z",
            )
        return bars

    def get_historical_bars(
        self,
        symbols: list[str],
        *,
        timeframe: str,
        limit: int,
        feed: str,
    ) -> dict[str, list[MarketBar]]:
        bars_by_symbol: dict[str, list[MarketBar]] = {}
        for offset, symbol in enumerate(symbols, start=1):
            series: list[MarketBar] = []
            base = 95.0 + offset
            for step in range(limit):
                close = base + step * 0.35
                series.append(
                    MarketBar(
                        symbol=symbol,
                        open=close - 0.4,
                        high=close + 0.6,
                        low=close - 0.8,
                        close=close,
                        volume=1000 + step,
                        timestamp=f"2026-04-{(step // 24) + 1:02d}T{step % 24:02d}:00:00Z",
                    )
                )
            bars_by_symbol[symbol] = series
        return bars_by_symbol

    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        return []

    def submit_order(self, order: OrderRequest) -> dict:
        return {
            "id": f"dry-run-{order.symbol.lower()}",
            "symbol": order.symbol,
            "side": order.side,
            "status": "not_submitted",
        }

    def cancel_order(self, order_id: str) -> dict:
        return {"id": order_id, "status": "canceled"}
