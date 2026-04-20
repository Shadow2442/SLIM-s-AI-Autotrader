from __future__ import annotations

from autotrade.brokers.base import BrokerAdapter
from autotrade.config import AppConfig, infer_symbol_asset_class, validate_asset_class, validate_runtime_mode
from autotrade.models import MarketBar, OrderRequest, PositionSnapshot, RunEvent
from autotrade.risk.manager import RiskManager
from autotrade.strategies.simple_momentum import analyze_bars, generate_signal
from autotrade.services.logging import StructuredLogger
from autotrade.services.operator_overrides import OperatorOverrideStore


class TradingLoop:
    _TRANSIENT_OVERRIDE_ACTIONS = {"buy", "sell", "skip", "hold"}

    def __init__(
        self,
        *,
        config: AppConfig,
        broker: BrokerAdapter,
        risk_manager: RiskManager,
        logger: StructuredLogger | None = None,
        override_store: OperatorOverrideStore | None = None,
    ) -> None:
        self._config = config
        self._broker = broker
        self._risk_manager = risk_manager
        self._logger = logger
        self._override_store = override_store

    def run_once(self) -> list[RunEvent]:
        validate_runtime_mode(self._config.runtime.mode)
        validate_asset_class(self._config.runtime.asset_class)

        account = self._broker.get_account()
        positions = self._broker.list_positions()
        open_orders = self._broker.list_open_orders()
        watchlist = self._planned_watchlist()
        latest_bars = self._broker.get_latest_bars(
            watchlist,
            feed=self._config.runtime.market_data_feed,
        )
        historical_bars = self._broker.get_historical_bars(
            watchlist,
            timeframe=self._config.runtime.bar_timeframe,
            limit=self._config.strategy.history_limit,
            feed=self._config.runtime.market_data_feed,
        )
        events: list[RunEvent] = []
        overrides = self._override_store.load() if self._override_store is not None else {}
        if self._override_store is not None and not self._override_store.ai_trading_enabled():
            event = RunEvent(
                event_type="ai_trading_disabled",
                message="AI trading is globally turned off by operator control.",
                details={"enabled": False},
            )
            self._record_event(events, event)
            return events
        position_by_symbol = {position.symbol: position for position in positions}
        projected_positions = list(positions)
        deployment_budget = self._deployment_budget(account.cash)
        open_buy_symbols = {
            order.symbol
            for order in open_orders
            if order.side.lower() == "buy" and order.status.lower() in {"new", "accepted", "pending_new", "partially_filled", "held", "open"}
        }

        for symbol in watchlist:
            bar = latest_bars.get(symbol)
            symbol_bars = historical_bars.get(symbol, [])
            if not symbol_bars:
                event = RunEvent(
                    event_type="market_data_missing",
                    message="Latest or historical market data not available.",
                    details={"symbol": symbol},
                )
                self._record_event(events, event)
                continue
            if bar is None:
                bar = symbol_bars[-1]
                self._record_event(
                    events,
                    RunEvent(
                        event_type="market_data_fallback",
                        message="Latest bar unavailable; using the newest historical bar.",
                        details={"symbol": symbol, "timestamp": bar.timestamp},
                    ),
                )

            symbol_bars = self._bars_with_latest(symbol_bars, bar)
            position = position_by_symbol.get(symbol)
            signal = generate_signal(
                symbol,
                bars=symbol_bars,
                has_position=symbol in position_by_symbol,
                strategy=self._config.strategy,
                average_entry_price=position.average_entry_price if position is not None else None,
            )
            analysis = analyze_bars(
                bars=symbol_bars,
                has_position=symbol in position_by_symbol,
                strategy=self._config.strategy,
                average_entry_price=position.average_entry_price if position is not None else None,
            )
            override_action = str(overrides.get(symbol, {}).get("action", "")).strip().lower()
            transient_override = override_action in self._TRANSIENT_OVERRIDE_ACTIONS

            if override_action in {"pause_auto", "skip", "hold"}:
                self._record_event(
                    events,
                    RunEvent(
                        event_type="operator_override_blocked_trade",
                        message="Trade skipped because of operator override.",
                        details={"symbol": symbol, "override_action": override_action},
                    ),
                )
                if transient_override:
                    self._clear_override(symbol)
                continue

            if override_action == "buy":
                signal.action = "BUY"
                signal.reason = "Operator override requested a buy."
                self._record_event(
                    events,
                    RunEvent(
                        event_type="operator_override_forced_buy",
                        message="Operator override forced a buy review.",
                        details={"symbol": symbol, "override_action": override_action},
                    ),
                )

            if override_action == "sell":
                self._record_event(
                    events,
                    RunEvent(
                        event_type="operator_override_forced_sell",
                        message="Operator override requested a sell.",
                        details={"symbol": symbol, "override_action": override_action},
                    ),
                )
                if transient_override:
                    self._clear_override(symbol)
                sell_events = self._execute_sell_override(symbol=symbol, bar=bar, position=position)
                for event in sell_events:
                    self._record_event(events, event)
                continue

            self._record_event(
                events,
                RunEvent(
                    event_type="signal_generated",
                    message="Signal generated from latest bar data.",
                    details={
                        "symbol": symbol,
                        "price": bar.close,
                        "signal_reason": signal.reason,
                        "confidence": round(signal.confidence, 4),
                        "fast_moving_average": round(float(analysis["fast_ma"]), 4),
                        "slow_moving_average": round(float(analysis["slow_ma"]), 4),
                        "momentum_percent": round(float(analysis["momentum_percent"]), 4),
                        "moving_average_gap_percent": round(float(analysis["ma_gap_percent"]), 4),
                        "setup": str(analysis["setup"]),
                        "breakout_level": round(float(analysis["breakout_level"]), 4),
                        "pullback_level": round(float(analysis["pullback_level"]), 4),
                        "suggested_buy_price": round(float(analysis["suggested_buy_price"]), 4),
                        "suggested_sell_price": round(float(analysis["suggested_sell_price"]), 4),
                        "stop_price": round(float(analysis["stop_price"]), 4),
                        "trailing_stop_price": round(float(analysis["trailing_stop_price"]), 4),
                        "target_price": round(float(analysis["target_price"]), 4),
                        "timestamp": bar.timestamp,
                        "action": signal.action,
                    },
                ),
            )
            decision = self._risk_manager.evaluate(
                signal,
                account=account,
                open_positions=self._risk_open_positions_for_symbol(
                    symbol=symbol,
                    projected_positions=projected_positions,
                ),
                kill_switch=self._config.kill_switch,
            )

            self._record_event(
                events,
                RunEvent(
                    event_type="risk_decision",
                    message=decision.reason,
                    details={"symbol": symbol, "approved": decision.approved, "action": signal.action},
                )
            )

            if not decision.approved:
                if transient_override:
                    self._clear_override(symbol)
                continue

            if signal.action == "SELL":
                sell_events = self._execute_sell_override(symbol=symbol, bar=bar, position=position)
                for event in sell_events:
                    self._record_event(events, event)
                continue

            if signal.action != "BUY":
                continue

            if symbol in open_buy_symbols:
                self._record_event(
                    events,
                    RunEvent(
                        event_type="duplicate_order_block",
                        message="Skipped buy because an open buy order already exists for this symbol.",
                        details={"symbol": symbol},
                    ),
                )
                if transient_override:
                    self._clear_override(symbol)
                continue

            budget_reason = self._budget_guard_reason(
                symbol=symbol,
                account_cash=account.cash,
                projected_positions=projected_positions,
                next_notional=signal.notional,
                deployment_budget=deployment_budget,
            )
            if budget_reason is not None:
                self._record_event(
                    events,
                    RunEvent(
                        event_type="investment_plan_block",
                        message=budget_reason,
                        details={
                            "symbol": symbol,
                            "deployment_budget": deployment_budget,
                            "starting_budget": self._config.investment_plan.starting_budget,
                        },
                    ),
                )
                if transient_override:
                    self._clear_override(symbol)
                continue

            if self._config.runtime.mode == "dry_run" or self._config.runtime.dry_run:
                projected_positions = self._project_buy_positions(
                    projected_positions,
                    symbol=symbol,
                    notional=signal.notional,
                    price=bar.close,
                )
                self._record_event(
                    events,
                    RunEvent(
                        event_type="dry_run_order",
                        message="Order skipped due to dry-run mode.",
                        details={
                            "symbol": symbol,
                            "notional": signal.notional,
                            "price": bar.close,
                            "timestamp": bar.timestamp,
                            "side": "buy",
                        },
                    )
                )
                if transient_override:
                    self._clear_override(symbol)
                continue

            order = OrderRequest(
                symbol=symbol,
                side="buy",
                notional=signal.notional,
                time_in_force="gtc" if infer_symbol_asset_class(symbol) == "crypto" else "day",
            )
            result = self._broker.submit_order(order)
            self._risk_manager.record_trade()
            projected_positions = self._project_buy_positions(
                projected_positions,
                symbol=symbol,
                notional=signal.notional,
                price=bar.close,
            )
            self._record_event(
                events,
                RunEvent(
                    event_type="order_submitted",
                    message="Paper order submitted.",
                    details={
                        "symbol": symbol,
                        "order_id": result.get("id", "unknown"),
                        "price": bar.close,
                        "timestamp": bar.timestamp,
                        "side": "buy",
                        "notional": signal.notional,
                        "asset_class": infer_symbol_asset_class(symbol),
                    },
                )
            )
            if transient_override:
                self._clear_override(symbol)

        return events

    def _execute_sell_override(
        self,
        *,
        symbol: str,
        bar: MarketBar,
        position: PositionSnapshot | None,
    ) -> list[RunEvent]:
        if position is None or position.quantity <= 0:
            return [
                RunEvent(
                    event_type="operator_override_sell_ignored",
                    message="Sell override ignored because no open position exists.",
                    details={"symbol": symbol},
                )
            ]

        if self._config.runtime.mode == "dry_run" or self._config.runtime.dry_run:
            return [
                RunEvent(
                    event_type="dry_run_order",
                    message="Sell order skipped due to dry-run mode.",
                    details={
                        "symbol": symbol,
                        "quantity": position.quantity,
                        "price": bar.close,
                        "timestamp": bar.timestamp,
                        "side": "sell",
                    },
                )
            ]

        order = OrderRequest(
            symbol=symbol,
            side="sell",
            quantity=position.quantity,
            time_in_force="gtc" if infer_symbol_asset_class(symbol) == "crypto" else "day",
        )
        result = self._broker.submit_order(order)
        self._risk_manager.record_trade()
        return [
            RunEvent(
                event_type="order_submitted",
                message="Paper sell order submitted from operator override.",
                details={
                    "symbol": symbol,
                    "order_id": result.get("id", "unknown"),
                    "quantity": position.quantity,
                    "price": bar.close,
                    "timestamp": bar.timestamp,
                    "side": "sell",
                    "asset_class": infer_symbol_asset_class(symbol),
                },
            )
        ]

    @staticmethod
    def _project_buy_positions(
        positions: list[PositionSnapshot],
        *,
        symbol: str,
        notional: float,
        price: float,
    ) -> list[PositionSnapshot]:
        quantity = 0.0 if price <= 0 else notional / price
        next_positions = list(positions)
        for index, position in enumerate(next_positions):
            if position.symbol != symbol:
                continue
            next_positions[index] = PositionSnapshot(
                symbol=position.symbol,
                quantity=position.quantity + quantity,
                market_value=position.market_value + notional,
                average_entry_price=price,
                unrealized_pl=position.unrealized_pl,
                unrealized_pl_percent=position.unrealized_pl_percent,
                raw=position.raw,
            )
            return next_positions

        next_positions.append(
            PositionSnapshot(
                symbol=symbol,
                quantity=quantity,
                market_value=notional,
                average_entry_price=price,
            )
        )
        return next_positions

    def _record_event(self, events: list[RunEvent], event: RunEvent) -> None:
        events.append(event)
        if self._logger is not None:
            self._logger.write_event(event)

    def _clear_override(self, symbol: str) -> None:
        if self._override_store is None:
            return
        self._override_store.clear_override(symbol)

    def _planned_watchlist(self) -> list[str]:
        allowed = {
            symbol.upper()
            for symbol in self._config.investment_plan.allowed_symbols
            if symbol.strip()
        }
        avoided = {
            symbol.upper()
            for symbol in self._config.investment_plan.avoided_symbols
            if symbol.strip()
        }
        base_symbols = [symbol for symbol in self._config.watchlist if symbol.upper() not in avoided]
        if allowed:
            base_symbols = [symbol for symbol in base_symbols if symbol.upper() in allowed]

        preferred_order = [
            symbol
            for symbol in self._config.investment_plan.preferred_symbols
            if symbol in base_symbols
        ]
        remaining = [symbol for symbol in base_symbols if symbol not in preferred_order]
        return preferred_order + remaining

    def _deployment_budget(self, account_cash: float) -> float:
        reserve_multiplier = 1 - (self._config.investment_plan.cash_reserve_percent / 100)
        reserve_multiplier = max(0.0, min(1.0, reserve_multiplier))
        return min(self._config.investment_plan.starting_budget, account_cash) * reserve_multiplier

    def _risk_open_positions_for_symbol(
        self,
        *,
        symbol: str,
        projected_positions: list[PositionSnapshot],
    ) -> list[PositionSnapshot]:
        if self._config.runtime.asset_class != "mixed":
            return projected_positions
        symbol_asset_class = infer_symbol_asset_class(symbol)
        return [
            position
            for position in projected_positions
            if infer_symbol_asset_class(position.symbol) == symbol_asset_class
        ]

    def _asset_class_budget(self, *, asset_class: str, deployment_budget: float) -> float:
        plan = self._config.investment_plan
        allocation_percent = (
            plan.crypto_allocation_percent if asset_class == "crypto" else plan.equity_allocation_percent
        )
        allocation_ratio = max(0.0, min(1.0, allocation_percent / 100))
        return deployment_budget * allocation_ratio

    @staticmethod
    def _allocated_total_by_asset_class(
        projected_positions: list[PositionSnapshot],
        *,
        asset_class: str,
    ) -> float:
        return sum(
            position.market_value
            for position in projected_positions
            if infer_symbol_asset_class(position.symbol) == asset_class
        )

    def _budget_guard_reason(
        self,
        *,
        symbol: str,
        account_cash: float,
        projected_positions: list[PositionSnapshot],
        next_notional: float,
        deployment_budget: float,
    ) -> str | None:
        plan = self._config.investment_plan
        allocated_total = sum(position.market_value for position in projected_positions)
        if allocated_total + next_notional > deployment_budget:
            return "Investment plan budget cap reached."

        asset_class = infer_symbol_asset_class(symbol)
        allocated_asset_total = self._allocated_total_by_asset_class(
            projected_positions,
            asset_class=asset_class,
        )
        asset_class_budget = self._asset_class_budget(
            asset_class=asset_class,
            deployment_budget=deployment_budget,
        )
        if allocated_asset_total + next_notional > asset_class_budget:
            label = "Crypto" if asset_class == "crypto" else "Equity"
            return f"{label} stash budget cap reached."

        max_symbol_allocation = deployment_budget * (plan.max_symbol_allocation_percent / 100)
        symbol_market_value = sum(
            position.market_value for position in projected_positions if position.symbol == symbol
        )
        if symbol_market_value + next_notional > max_symbol_allocation:
            return "Per-symbol allocation cap reached."

        reserve_cash = min(plan.starting_budget, account_cash) - deployment_budget
        if account_cash - next_notional < reserve_cash:
            return "Trade would consume reserved cash buffer."

        return None

    @staticmethod
    def _bars_with_latest(bars: list[MarketBar], latest_bar: MarketBar) -> list[MarketBar]:
        if not bars:
            return [latest_bar]
        merged = list(bars)
        last_bar = merged[-1]
        if last_bar.timestamp == latest_bar.timestamp:
            merged[-1] = latest_bar
            return merged
        if latest_bar.timestamp > last_bar.timestamp:
            merged.append(latest_bar)
            return merged
        merged[-1] = latest_bar
        return merged
