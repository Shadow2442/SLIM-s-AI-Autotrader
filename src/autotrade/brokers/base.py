from __future__ import annotations

from abc import ABC, abstractmethod

from autotrade.models import AccountSnapshot, MarketBar, OrderRequest, OrderSnapshot, PositionSnapshot


class BrokerAdapter(ABC):
    @abstractmethod
    def get_account(self) -> AccountSnapshot:
        raise NotImplementedError

    @abstractmethod
    def list_positions(self) -> list[PositionSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def list_open_orders(self) -> list[OrderSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
        raise NotImplementedError

    @abstractmethod
    def get_historical_bars(
        self,
        symbols: list[str],
        *,
        timeframe: str,
        limit: int,
        feed: str,
    ) -> dict[str, list[MarketBar]]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> dict:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        raise NotImplementedError
