from __future__ import annotations

import json
import threading
import time

from autotrade.config import normalize_symbol
from autotrade.services.operator_overrides import OperatorOverrideStore
from autotrade.services.runtime_state import RuntimeStateStore


class CryptoStreamWatcher:
    def __init__(
        self,
        *,
        symbols: list[str],
        api_key: str,
        api_secret: str,
        location: str,
        cooldown_seconds: int,
        runtime_state_store: RuntimeStateStore,
        override_store: OperatorOverrideStore,
    ) -> None:
        self._symbols = [normalize_symbol(symbol, "crypto") for symbol in symbols if symbol]
        self._api_key = api_key
        self._api_secret = api_secret
        self._location = location
        self._cooldown_seconds = max(1, int(cooldown_seconds))
        self._runtime_state_store = runtime_state_store
        self._override_store = override_store
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_trigger_at = 0.0
        self._last_trigger_prices: dict[str, float] = {}
        self._announced_live = False
        self._last_reconnect_log_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._symbols and self._api_key and self._api_secret)

    def start(self) -> bool:
        if not self.enabled:
            self._runtime_state_store.update_crypto_stream_status(
                status="inactive",
                message="Crypto stream is inactive.",
            )
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._run, name="crypto-stream-watcher", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._runtime_state_store.update_crypto_stream_status(
            status="stopped",
            message="Crypto stream stopped.",
        )

    def _run(self) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError:
            self._runtime_state_store.update_crypto_stream_status(
                status="unavailable",
                message="Crypto stream dependency is not installed.",
            )
            self._runtime_state_store.append_log(
                kind="warning",
                title="Crypto stream unavailable",
                message="Install the websockets dependency to enable live crypto streaming.",
            )
            return

        url = f"wss://stream.data.alpaca.markets/v1beta3/crypto/{self._location}"
        backoff_seconds = 1.0
        while not self._stop_event.is_set():
            try:
                self._runtime_state_store.update_crypto_stream_status(
                    status="connecting",
                    message=f"Connecting to {len(self._symbols)} crypto pair(s).",
                )
                with connect(url, open_timeout=10, close_timeout=2, max_size=2**20) as websocket:
                    websocket.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": self._api_key,
                                "secret": self._api_secret,
                            }
                        )
                    )
                    websocket.send(json.dumps({"action": "subscribe", "quotes": self._symbols, "trades": self._symbols}))
                    self._runtime_state_store.update_crypto_stream_status(
                        status="live",
                        message=f"Live on {len(self._symbols)} crypto pair(s).",
                    )
                    if not self._announced_live:
                        self._runtime_state_store.append_log(
                            kind="system",
                            title="Crypto stream live",
                            message=f"Watching {len(self._symbols)} crypto pair(s) for immediate run triggers.",
                        )
                        self._announced_live = True
                    backoff_seconds = 1.0
                    while not self._stop_event.is_set():
                        try:
                            raw_message = websocket.recv(timeout=1.0)
                        except TimeoutError:
                            continue
                        if not raw_message:
                            continue
                        self._handle_message(raw_message)
            except Exception as exc:  # noqa: BLE001
                if self._stop_event.is_set():
                    break
                self._runtime_state_store.update_crypto_stream_status(
                    status="reconnecting",
                    message=f"Reconnecting after stream issue: {type(exc).__name__}.",
                )
                if self._should_log_reconnect_warning():
                    self._runtime_state_store.append_log(
                        kind="warning",
                        title="Crypto stream reconnecting",
                        message=f"Live crypto feed hit {type(exc).__name__}; retrying in {int(backoff_seconds)}s.",
                    )
                self._stop_event.wait(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 10.0)

    def _handle_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, dict):
                continue
            self._handle_event(item)

    def _handle_event(self, item: dict) -> None:
        event_type = str(item.get("T", "")).strip()
        if event_type in {"success", "subscription"}:
            return
        if event_type not in {"q", "t"}:
            return
        symbol = normalize_symbol(str(item.get("S", "")).strip(), "crypto")
        price = self._extract_price(item)
        if not symbol or price is None:
            return
        self._runtime_state_store.update_crypto_stream_status(
            status="live",
            message=f"{symbol} live at ${price:,.4f}",
            symbol=symbol,
            price=price,
        )
        if self._should_request_cycle(symbol=symbol, price=price):
            self._runtime_state_store.request_immediate_cycle()
            self._runtime_state_store.append_log(
                kind="system",
                title="Crypto stream triggered run",
                message=f"{symbol} moved live to ${price:,.4f}; the next cycle will start immediately.",
            )
            self._last_trigger_at = time.monotonic()
            self._last_trigger_prices[symbol] = price

    def _should_request_cycle(self, *, symbol: str, price: float) -> bool:
        if not self._override_store.ai_trading_enabled():
            return False
        state = self._runtime_state_store.load()
        if not state.get("session_active"):
            return False
        if state.get("cycle_running"):
            return False
        if state.get("force_cycle_requested"):
            return False
        if state.get("status") not in {"waiting", "starting"}:
            return False
        if time.monotonic() - self._last_trigger_at < self._cooldown_seconds:
            return False

        last_trigger_price = self._last_trigger_prices.get(symbol)
        if last_trigger_price is None:
            return True
        move_percent = abs((price - last_trigger_price) / last_trigger_price) * 100 if last_trigger_price else 0.0
        return move_percent >= 0.1

    def _should_log_reconnect_warning(self) -> bool:
        now = time.monotonic()
        if now - self._last_reconnect_log_at < 30.0:
            return False
        self._last_reconnect_log_at = now
        return True

    @staticmethod
    def _extract_price(item: dict) -> float | None:
        event_type = str(item.get("T", "")).strip()
        if event_type == "q":
            bid = item.get("bp")
            ask = item.get("ap")
            if bid is None and ask is None:
                return None
            if bid is None:
                return float(ask)
            if ask is None:
                return float(bid)
            return (float(bid) + float(ask)) / 2
        if event_type == "t" and item.get("p") is not None:
            return float(item["p"])
        return None
