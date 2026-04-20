from autotrade.brokers.base import BrokerAdapter
from autotrade.models import AccountSnapshot, MarketBar, OrderRequest, OrderSnapshot, PositionSnapshot
from autotrade.services.reconciliation import ReconciliationService


class FakeReconciliationBroker(BrokerAdapter):
    def __init__(self) -> None:
        self.cancelled_orders: list[str] = []

    def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(equity=1000.0, buying_power=800.0, cash=500.0)

    def list_positions(self) -> list[PositionSnapshot]:
        return [PositionSnapshot(symbol="SPY", quantity=1.0, market_value=101.0)]

    def list_open_orders(self) -> list[OrderSnapshot]:
        return [
            OrderSnapshot(order_id="1", symbol="AAPL", side="buy", status="open"),
            OrderSnapshot(order_id="2", symbol="AAPL", side="buy", status="open"),
        ]

    def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
        return {}

    def get_historical_bars(
        self,
        symbols: list[str],
        *,
        timeframe: str,
        limit: int,
        feed: str,
    ) -> dict[str, list[MarketBar]]:
        return {}

    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        return []

    def submit_order(self, order: OrderRequest) -> dict:
        return {}

    def cancel_order(self, order_id: str) -> dict:
        self.cancelled_orders.append(order_id)
        return {"id": order_id, "status": "canceled"}


def test_reconciliation_warns_on_duplicate_open_order_symbols() -> None:
    service = ReconciliationService(FakeReconciliationBroker())

    events = service.reconcile()

    assert any(event.event_type == "reconciliation_warning" for event in events)


def test_reconciliation_cancels_duplicate_open_buy_orders() -> None:
    broker = FakeReconciliationBroker()
    service = ReconciliationService(broker)

    events = service.cleanup_duplicate_open_orders()

    assert broker.cancelled_orders == ["2"]
    assert any(event.event_type == "duplicate_order_cancelled" for event in events)
