from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autotrade.config import infer_symbol_asset_class, normalize_symbol


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperatorOverrideStore:
    _SYSTEM_KEY = "__system__"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8-sig"))

    def save(self, payload: dict[str, dict]) -> dict[str, dict]:
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def set_override(self, symbol: str, action: str) -> dict[str, dict]:
        payload = self.load()
        symbol = normalize_symbol(symbol, infer_symbol_asset_class(symbol))
        payload[symbol] = {
            "action": action,
            "updated_at": utc_now_iso(),
        }
        return self.save(payload)

    def set_bulk_override(self, symbols: list[str], action: str) -> dict[str, dict]:
        payload = self.load()
        timestamp = utc_now_iso()
        for symbol in symbols:
            symbol = normalize_symbol(symbol, infer_symbol_asset_class(symbol))
            payload[symbol] = {
                "action": action,
                "updated_at": timestamp,
            }
        return self.save(payload)

    def ai_trading_enabled(self) -> bool:
        payload = self.load()
        system = payload.get(self._SYSTEM_KEY, {})
        return bool(system.get("ai_trading_enabled", True))

    def set_ai_trading_enabled(self, enabled: bool) -> dict[str, dict]:
        payload = self.load()
        payload[self._SYSTEM_KEY] = {
            "ai_trading_enabled": enabled,
            "updated_at": utc_now_iso(),
        }
        return self.save(payload)

    def clear_override(self, symbol: str) -> dict[str, dict]:
        payload = self.load()
        symbol = normalize_symbol(symbol, infer_symbol_asset_class(symbol))
        payload.pop(symbol, None)
        return self.save(payload)

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
