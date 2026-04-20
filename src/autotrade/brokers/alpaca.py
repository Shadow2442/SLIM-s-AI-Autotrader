from __future__ import annotations

from typing import Any

import httpx

from autotrade.brokers.base import BrokerAdapter
from autotrade.config import infer_symbol_asset_class, normalize_symbol
from autotrade.models import AccountSnapshot, MarketBar, OrderRequest, OrderSnapshot, PositionSnapshot


class AlpacaBrokerAdapter(BrokerAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        market_data_url: str,
        asset_class: str,
        crypto_location: str,
        api_key: str,
        api_secret: str,
        timeout: float = 10.0,
    ) -> None:
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
        }
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers=headers,
        )
        self._market_data_client = httpx.Client(
            base_url=market_data_url,
            timeout=timeout,
            headers=headers,
        )
        self._asset_class = asset_class
        self._crypto_location = crypto_location

    def _symbol_asset_class(self, symbol: str) -> str:
        if self._asset_class in {"us_equity", "crypto"}:
            return self._asset_class
        return infer_symbol_asset_class(symbol)

    def _split_symbols(self, symbols: list[str]) -> tuple[list[str], list[str]]:
        stock_symbols: list[str] = []
        crypto_symbols: list[str] = []
        for symbol in symbols:
            normalized_symbol = normalize_symbol(symbol, self._symbol_asset_class(symbol))
            if self._symbol_asset_class(normalized_symbol) == "crypto":
                crypto_symbols.append(normalized_symbol)
            else:
                stock_symbols.append(normalized_symbol)
        return stock_symbols, crypto_symbols

    def get_account(self) -> AccountSnapshot:
        response = self._client.get("/v2/account")
        response.raise_for_status()
        payload = response.json()
        return AccountSnapshot(
            equity=float(payload.get("equity", 0.0)),
            buying_power=float(payload.get("buying_power", 0.0)),
            cash=float(payload.get("cash", 0.0)),
            raw=payload,
        )

    def list_positions(self) -> list[PositionSnapshot]:
        response = self._client.get("/v2/positions")
        response.raise_for_status()
        items = response.json()
        positions: list[PositionSnapshot] = []
        for item in items:
            positions.append(
                PositionSnapshot(
                    symbol=normalize_symbol(item["symbol"], item.get("asset_class")),
                    quantity=float(item.get("qty", 0.0)),
                    market_value=float(item.get("market_value", 0.0)),
                    average_entry_price=float(item["avg_entry_price"]) if item.get("avg_entry_price") else None,
                    unrealized_pl=float(item["unrealized_pl"]) if item.get("unrealized_pl") else None,
                    unrealized_pl_percent=float(item["unrealized_plpc"]) if item.get("unrealized_plpc") else None,
                    raw=item,
                )
            )
        return positions

    def list_open_orders(self) -> list[OrderSnapshot]:
        response = self._client.get("/v2/orders", params={"status": "open", "direction": "desc"})
        response.raise_for_status()
        return self._normalize_orders(response.json())

    def get_latest_bars(self, symbols: list[str], *, feed: str) -> dict[str, MarketBar]:
        stock_symbols, crypto_symbols = self._split_symbols(symbols)
        bars: dict[str, MarketBar] = {}

        if crypto_symbols:
            response = self._market_data_client.get(
                f"/v1beta3/crypto/{self._crypto_location}/latest/bars",
                params={"symbols": ",".join(crypto_symbols)},
            )
            response.raise_for_status()
            payload = response.json().get("bars", {})
            bars.update(
                {
                    symbol: MarketBar(
                        symbol=symbol,
                        open=float(item["o"]),
                        high=float(item["h"]),
                        low=float(item["l"]),
                        close=float(item["c"]),
                        volume=float(item["v"]),
                        timestamp=item["t"],
                    )
                    for symbol, item in payload.items()
                }
            )

        if stock_symbols:
            response = self._market_data_client.get(
                "/v2/stocks/bars/latest",
                params={"symbols": ",".join(stock_symbols), "feed": feed},
            )
            response.raise_for_status()
            payload = response.json().get("bars", {})
            for symbol, item in payload.items():
                bars[symbol] = MarketBar(
                    symbol=symbol,
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    volume=float(item["v"]),
                    timestamp=item["t"],
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
        for symbol in symbols:
            if self._symbol_asset_class(symbol) == "crypto":
                response = self._market_data_client.get(
                    f"/v1beta3/crypto/{self._crypto_location}/bars",
                    params={
                        "symbols": symbol,
                        "timeframe": timeframe,
                        "limit": limit,
                    },
                )
            else:
                response = self._market_data_client.get(
                    "/v2/stocks/bars",
                    params={
                        "symbols": symbol,
                        "timeframe": timeframe,
                        "limit": limit,
                        "feed": feed,
                    },
                )
            response.raise_for_status()
            payload = response.json().get("bars", {})
            items = payload.get(symbol, [])
            bars_by_symbol[symbol] = [
                MarketBar(
                    symbol=symbol,
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    volume=float(item["v"]),
                    timestamp=item["t"],
                )
                for item in items
            ]
        return bars_by_symbol

    def list_recent_orders(self, *, status: str = "all", limit: int = 100) -> list[OrderSnapshot]:
        response = self._client.get(
            "/v2/orders",
            params={"status": status, "direction": "desc", "limit": limit},
        )
        response.raise_for_status()
        return self._normalize_orders(response.json())

    def submit_order(self, order: OrderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": normalize_symbol(order.symbol, infer_symbol_asset_class(order.symbol)),
            "side": order.side,
            "type": order.order_type,
            "time_in_force": order.time_in_force,
        }
        if order.quantity is not None:
            payload["qty"] = order.quantity
        if order.notional is not None:
            payload["notional"] = order.notional

        response = self._client.post("/v2/orders", json=payload)
        response.raise_for_status()
        return response.json()

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        response = self._client.delete(f"/v2/orders/{order_id}")
        response.raise_for_status()
        if response.content:
            return response.json()
        return {"id": order_id, "status": "canceled"}

    @staticmethod
    def _normalize_orders(items: list[dict[str, Any]]) -> list[OrderSnapshot]:
        orders: list[OrderSnapshot] = []
        for item in items:
            orders.append(
                OrderSnapshot(
                    order_id=item["id"],
                    symbol=normalize_symbol(item["symbol"], item.get("asset_class")),
                    side=item["side"],
                    status=item["status"],
                    notional=float(item["notional"]) if item.get("notional") else None,
                    quantity=float(item["qty"]) if item.get("qty") else None,
                    raw=item,
                )
            )
        return orders
