from __future__ import annotations

from autotrade.config import RiskConfig
from autotrade.models import AccountSnapshot, PositionSnapshot, RiskDecision, Signal


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._submitted_trade_count = 0

    def evaluate(
        self,
        signal: Signal,
        *,
        account: AccountSnapshot,
        open_positions: list[PositionSnapshot],
        kill_switch: bool,
    ) -> RiskDecision:
        if kill_switch:
            return RiskDecision(False, "Kill switch enabled.", signal)
        if signal.notional > self._config.max_notional_per_trade:
            return RiskDecision(False, "Signal exceeds max notional per trade.", signal)
        if len(open_positions) >= self._config.max_open_positions and signal.action == "BUY":
            return RiskDecision(False, "Max open positions reached.", signal)
        if self._submitted_trade_count >= self._config.max_trades_per_session:
            return RiskDecision(False, "Session trade limit reached.", signal)
        if signal.notional > account.buying_power:
            return RiskDecision(False, "Insufficient buying power.", signal)
        return RiskDecision(True, "Approved.", signal)

    def record_trade(self) -> None:
        self._submitted_trade_count += 1
