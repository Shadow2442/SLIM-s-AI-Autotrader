from __future__ import annotations

from autotrade.brokers.base import BrokerAdapter
from autotrade.models import RunEvent


class ReconciliationService:
    def __init__(self, broker: BrokerAdapter) -> None:
        self._broker = broker

    def reconcile(self) -> list[RunEvent]:
        account = self._broker.get_account()
        positions = self._broker.list_positions()
        open_orders = self._broker.list_open_orders()

        events = [
            RunEvent(
                event_type="account_snapshot",
                message="Captured account snapshot.",
                details={
                    "equity": account.equity,
                    "buying_power": account.buying_power,
                    "cash": account.cash,
                },
            ),
            RunEvent(
                event_type="positions_snapshot",
                message="Captured positions snapshot.",
                details={
                    "count": len(positions),
                    "symbols": [position.symbol for position in positions],
                },
            ),
            RunEvent(
                event_type="open_orders_snapshot",
                message="Captured open orders snapshot.",
                details={
                    "count": len(open_orders),
                    "symbols": [order.symbol for order in open_orders],
                },
            ),
        ]

        duplicate_symbols = sorted(
            {
                order.symbol
                for order in open_orders
                if [candidate.symbol for candidate in open_orders].count(order.symbol) > 1
            }
        )
        if duplicate_symbols:
            events.append(
                RunEvent(
                    event_type="reconciliation_warning",
                    message="Multiple open orders detected for one or more symbols.",
                    details={"symbols": duplicate_symbols},
                )
            )

        return events

    def cleanup_duplicate_open_orders(self) -> list[RunEvent]:
        open_orders = self._broker.list_open_orders()
        grouped: dict[tuple[str, str], list] = {}
        for order in open_orders:
            grouped.setdefault((order.symbol, order.side.lower()), []).append(order)

        events: list[RunEvent] = []
        for (symbol, side), orders in grouped.items():
            if side != "buy" or len(orders) <= 1:
                continue
            keep_order = orders[0]
            for order in orders[1:]:
                self._broker.cancel_order(order.order_id)
                events.append(
                    RunEvent(
                        event_type="duplicate_order_cancelled",
                        message="Cancelled duplicate open buy order.",
                        details={
                            "symbol": symbol,
                            "kept_order_id": keep_order.order_id,
                            "cancelled_order_id": order.order_id,
                        },
                    )
                )
        return events
