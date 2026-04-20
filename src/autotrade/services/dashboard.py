from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from autotrade.brokers.base import BrokerAdapter
from autotrade.config import AppConfig, infer_symbol_asset_class
from autotrade.models import (
    AssetChart,
    AssetRecommendation,
    ChartPoint,
    DashboardSnapshot,
    MarketBar,
    OpenOrderInfo,
    RecentOrderInfo,
    RunEvent,
    TradeMarker,
    TradeRecord,
    utc_now,
)
from autotrade.services.history import HistoryStore
from autotrade.services.operator_overrides import OperatorOverrideStore
from autotrade.strategies.simple_momentum import analyze_bars


class DashboardService:
    def __init__(self, *, broker: BrokerAdapter, config: AppConfig, output_dir: Path) -> None:
        self._broker = broker
        self._config = config
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._history_store = HistoryStore(self._output_dir / "history")
        self._override_store = OperatorOverrideStore(self._output_dir / "operator_overrides.json")

    def build_snapshot(self, alerts: list[RunEvent] | None = None) -> DashboardSnapshot:
        alerts = alerts or []
        account = self._broker.get_account()
        positions = self._broker.list_positions()
        open_orders = self._broker.list_open_orders()
        recent_orders = self._broker.list_recent_orders(limit=100)
        watchlist = self._planned_watchlist()
        latest_bars = self._broker.get_latest_bars(
            watchlist,
            feed=self._config.runtime.market_data_feed,
        )
        historical_bars = self._broker.get_historical_bars(
            watchlist,
            timeframe=self._config.runtime.bar_timeframe,
            limit=30,
            feed=self._config.runtime.market_data_feed,
        )

        self._record_broker_order_markers(recent_orders)

        position_by_symbol = {position.symbol: position for position in positions}
        filled_position_cost_basis = sum(
            float(position.average_entry_price or 0.0) * float(position.quantity or 0.0)
            for position in positions
        )
        invested_value = sum(position.market_value for position in positions)
        open_order_details = [
            OpenOrderInfo(
                symbol=order.symbol,
                asset_class=infer_symbol_asset_class(order.symbol),
                side=order.side,
                status=order.status,
                notional_value=self._open_order_notional_value(order),
            )
            for order in open_orders
        ]
        pending_open_order_value = sum(item.notional_value for item in open_order_details)
        status_counts: dict[str, int] = {}
        for item in open_order_details:
            key = item.status.upper()
            status_counts[key] = status_counts.get(key, 0) + 1
        open_order_status_summary = (
            ", ".join(f"{count} {status.lower()}" for status, count in sorted(status_counts.items()))
            if status_counts
            else "No open orders"
        )
        open_order_fill_hint = self._estimate_open_order_fill_hint(open_orders)
        recent_order_activity = self._recent_order_activity(recent_orders)
        recommendations: list[AssetRecommendation] = []
        risk_alerts_by_symbol = self._group_event_alerts(alerts)
        overrides = self._override_store.load()

        for symbol in watchlist:
            position = position_by_symbol.get(symbol)
            latest_bar = latest_bars.get(symbol)
            bars = historical_bars.get(symbol, [])
            if latest_bar is None and bars:
                latest_bar = bars[-1]
            current_price = latest_bar.close if latest_bar is not None else 0.0
            if latest_bar is not None:
                bars = self._bars_with_latest(bars, latest_bar)
            trend_percent = self._trend_percent(bars)
            volatility_percent = self._volatility_percent(bars)
            analysis = analyze_bars(
                bars=bars,
                has_position=position is not None,
                strategy=self._config.strategy,
                average_entry_price=position.average_entry_price if position is not None else None,
            )

            if position is not None:
                unrealized_pl = position.unrealized_pl or 0.0
                unrealized_pl_percent = (position.unrealized_pl_percent or 0.0) * 100
                market_value = position.market_value
                recommendation, risk_level, rationale = self._recommend_position(
                    unrealized_pl_percent=unrealized_pl_percent,
                    current_price=current_price,
                    average_entry_price=position.average_entry_price,
                    trend_percent=trend_percent,
                    volatility_percent=volatility_percent,
                    has_position=True,
                    strategy_setup=str(analysis["setup"]),
                    signal_action=str(analysis["action"]),
                    momentum_percent=float(analysis["momentum_percent"]),
                    moving_average_gap_percent=float(analysis["ma_gap_percent"]),
                )
            else:
                unrealized_pl = 0.0
                unrealized_pl_percent = 0.0
                market_value = 0.0
                recommendation, risk_level, rationale = self._recommend_position(
                    unrealized_pl_percent=0.0,
                    current_price=current_price,
                    average_entry_price=None,
                    trend_percent=trend_percent,
                    volatility_percent=volatility_percent,
                    has_position=False,
                    strategy_setup=str(analysis["setup"]),
                    signal_action=str(analysis["action"]),
                    momentum_percent=float(analysis["momentum_percent"]),
                    moving_average_gap_percent=float(analysis["ma_gap_percent"]),
                )

            if symbol in risk_alerts_by_symbol:
                recommendation, risk_level, rationale = self._apply_event_override(
                    symbol=symbol,
                    recommendation=recommendation,
                    risk_level=risk_level,
                    rationale=rationale,
                    alerts=risk_alerts_by_symbol[symbol],
                )

            override_action = str(overrides.get(symbol, {}).get("action", "")).strip().lower()
            if override_action:
                recommendation, risk_level, rationale = self._apply_operator_override(
                    recommendation=recommendation,
                    risk_level=risk_level,
                    rationale=rationale,
                    override_action=override_action,
                )

            recommendations.append(
                AssetRecommendation(
                    symbol=symbol,
                    asset_class=infer_symbol_asset_class(symbol),
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_pl=unrealized_pl,
                    unrealized_pl_percent=unrealized_pl_percent,
                    risk_level=risk_level,
                    recommendation=recommendation,
                    rationale=f"{rationale} Trend {trend_percent:.2f}% | Vol {volatility_percent:.2f}%.",
                    signal_action=str(analysis["action"]),
                    signal_confidence=float(analysis["confidence"]),
                    fast_moving_average=float(analysis["fast_ma"]),
                    slow_moving_average=float(analysis["slow_ma"]),
                    momentum_percent=float(analysis["momentum_percent"]),
                    moving_average_gap_percent=float(analysis["ma_gap_percent"]),
                    signal_reason=str(analysis["reason"]),
                    strategy_setup=str(analysis["setup"]),
                    breakout_level=float(analysis["breakout_level"]),
                    pullback_level=float(analysis["pullback_level"]),
                    suggested_buy_price=float(analysis["suggested_buy_price"]),
                    suggested_sell_price=float(analysis["suggested_sell_price"]),
                    stop_price=float(analysis["stop_price"]),
                    trailing_stop_price=float(analysis["trailing_stop_price"]),
                    target_price=float(analysis["target_price"]),
                )
            )

        asset_charts = [
            AssetChart(
                symbol=symbol,
                points=[
                    ChartPoint(timestamp=bar.timestamp, value=bar.close)
                    for bar in self._bars_with_latest(historical_bars.get(symbol, []), latest_bars[symbol])
                ]
                if symbol in latest_bars
                else [ChartPoint(timestamp=bar.timestamp, value=bar.close) for bar in historical_bars.get(symbol, [])],
                markers=self._history_store.load_trade_markers(symbol=symbol, limit=50),
            )
            for symbol in watchlist
        ]
        symbol_performance, strategy_performance = self._history_store.summarize_performance(limit=2000)

        return DashboardSnapshot(
            generated_at=utc_now(),
            total_equity=account.equity,
            cash=account.cash,
            buying_power=account.buying_power,
            filled_position_cost_basis=filled_position_cost_basis,
            invested_value=invested_value,
            open_orders_count=len(open_orders),
            pending_open_order_value=pending_open_order_value,
            open_order_status_summary=open_order_status_summary,
            open_order_fill_hint=open_order_fill_hint,
            open_order_details=open_order_details,
            recent_order_activity=recent_order_activity,
            recommendations=recommendations,
            alerts=alerts,
            portfolio_history=self._history_store.load_portfolio_history(limit=100),
            asset_charts=asset_charts,
            symbol_performance=symbol_performance,
            strategy_performance=strategy_performance,
        )

    def write_reports(self, snapshot: DashboardSnapshot) -> tuple[Path, Path]:
        json_path = self._output_dir / "dashboard.json"
        html_path = self._output_dir / "dashboard.html"
        operator_path = self._output_dir / "operator_window.html"

        self._history_store.append_dashboard_snapshot(snapshot)
        snapshot.portfolio_history = self._history_store.load_portfolio_history(limit=100)

        payload = asdict(snapshot)
        payload["generated_at"] = snapshot.generated_at.isoformat()
        payload["alerts"] = [
            {
                "event_type": alert.event_type,
                "message": alert.message,
                "details": alert.details,
                "created_at": alert.created_at.isoformat(),
            }
            for alert in snapshot.alerts
        ]
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        html_path.write_text(self._render_html(snapshot), encoding="utf-8")
        operator_path.write_text(self._render_operator_window(snapshot), encoding="utf-8")
        return json_path, html_path

    def record_trade_markers_from_events(self, events: list[RunEvent]) -> None:
        for event in events:
            if event.event_type not in {"order_submitted", "dry_run_order"}:
                continue
            symbol = str(event.details.get("symbol", ""))
            if not symbol:
                continue
            self._history_store.append_trade_marker(
                TradeMarker(
                    symbol=symbol,
                    side=str(event.details.get("side", "buy")),
                    timestamp=str(event.details.get("timestamp", utc_now().isoformat())),
                    price=float(event.details.get("price", 0.0)),
                    note=event.message,
                )
            )
            self._history_store.append_trade_record(
                TradeRecord(
                    symbol=symbol,
                    side=str(event.details.get("side", "buy")),
                    timestamp=str(event.details.get("timestamp", utc_now().isoformat())),
                    price=float(event.details.get("price", 0.0)),
                    quantity=self._event_quantity(event),
                    strategy_name=self._config.runtime.strategy_name,
                    source="runtime_event",
                    note=event.message,
                )
            )

    def _record_broker_order_markers(self, recent_orders) -> None:
        existing = {(m.symbol, m.side, m.timestamp, m.price) for m in self._history_store.load_trade_markers(limit=500)}
        existing_records = {
            (r.symbol, r.side, r.timestamp, r.price, r.quantity, r.source)
            for r in self._history_store.load_trade_records(limit=2000)
        }
        for order in recent_orders:
            raw = order.raw
            timestamp = raw.get("filled_at") or raw.get("submitted_at")
            if not timestamp:
                continue
            price = None
            if raw.get("filled_avg_price"):
                price = float(raw["filled_avg_price"])
            elif raw.get("limit_price"):
                price = float(raw["limit_price"])
            elif order.notional and order.quantity:
                price = float(order.notional) / float(order.quantity)
            if price is None:
                continue
            key = (order.symbol, order.side, str(timestamp), float(price))
            if key in existing:
                continue
            self._history_store.append_trade_marker(
                TradeMarker(
                    symbol=order.symbol,
                    side=order.side,
                    timestamp=str(timestamp),
                    price=float(price),
                    note=f"Broker order {order.status}",
                )
            )
            existing.add(key)
            quantity = float(order.quantity or 0.0)
            record_key = (order.symbol, order.side, str(timestamp), float(price), quantity, "broker_order")
            if quantity > 0 and record_key not in existing_records:
                self._history_store.append_trade_record(
                    TradeRecord(
                        symbol=order.symbol,
                        side=order.side,
                        timestamp=str(timestamp),
                        price=float(price),
                        quantity=quantity,
                        strategy_name=self._config.runtime.strategy_name,
                        source="broker_order",
                        note=f"Broker order {order.status}",
                    )
                )
                existing_records.add(record_key)

    @staticmethod
    def _open_order_notional_value(order) -> float:
        if order.notional:
            return float(order.notional)
        raw = order.raw or {}
        if raw.get("notional"):
            return float(raw["notional"])
        quantity = order.quantity or raw.get("qty") or raw.get("quantity")
        price = raw.get("limit_price") or raw.get("filled_avg_price")
        if quantity and price:
            return float(quantity) * float(price)
        return 0.0

    @staticmethod
    def _estimate_open_order_fill_hint(open_orders) -> str:
        if not open_orders:
            return "No pending fills."

        has_crypto = any("/" in str(getattr(order, "symbol", "")) for order in open_orders)
        has_equity = any("/" not in str(getattr(order, "symbol", "")) for order in open_orders)
        accepted_count = sum(1 for order in open_orders if str(order.status).lower() == "accepted")

        eastern = timezone(timedelta(hours=-4))
        zurich = timezone(timedelta(hours=2))
        market_open = time(9, 30)
        market_close = time(16, 0)
        submitted_times: list[datetime] = []
        after_hours_market_orders = False

        for order in open_orders:
            raw = order.raw or {}
            submitted_at = raw.get("submitted_at")
            if submitted_at:
                try:
                    submitted_dt = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
                    submitted_times.append(submitted_dt.astimezone(UTC))
                except ValueError:
                    pass
            if str(raw.get("type", order.raw.get("order_type", "market"))).lower() == "market":
                if submitted_at:
                    try:
                        submitted_et = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00")).astimezone(eastern)
                        if submitted_et.time() >= market_close or submitted_et.time() < market_open:
                            after_hours_market_orders = True
                    except ValueError:
                        pass

        base_dt = max(submitted_times) if submitted_times else utc_now()
        reference_et = base_dt.astimezone(eastern)

        def next_weekday_open(dt_et: datetime) -> datetime:
            candidate = dt_et
            if candidate.weekday() >= 5:
                days_ahead = 7 - candidate.weekday()
                candidate = datetime.combine((candidate + timedelta(days=days_ahead)).date(), market_open, tzinfo=eastern)
            elif candidate.time() >= market_close:
                candidate = datetime.combine((candidate + timedelta(days=1)).date(), market_open, tzinfo=eastern)
            elif candidate.time() < market_open:
                candidate = datetime.combine(candidate.date(), market_open, tzinfo=eastern)
            else:
                candidate = datetime.combine(candidate.date(), market_open, tzinfo=eastern)
            while candidate.weekday() >= 5:
                candidate = datetime.combine((candidate + timedelta(days=1)).date(), market_open, tzinfo=eastern)
            return candidate

        if has_crypto and not has_equity:
            if accepted_count:
                return "Crypto trades 24/7; accepted orders can fill anytime if marketable."
            return "Crypto orders are pending live execution."

        if has_crypto and has_equity and after_hours_market_orders:
            next_open_et = next_weekday_open(reference_et)
            next_open_ch = next_open_et.astimezone(zurich)
            return (
                f"Mixed queue: crypto can fill 24/7, while equity orders may wait until "
                f"{next_open_ch:%d.%m.%Y - %H:%M} Zurich."
            )

        if after_hours_market_orders:
            next_open_et = next_weekday_open(reference_et)
            next_open_ch = next_open_et.astimezone(zurich)
            return f"Likely waiting for next US market open at {next_open_ch:%d.%m.%Y - %H:%M} Zurich."

        if accepted_count:
            return "Accepted by Alpaca, but not filled yet."
        return "Open orders are pending broker execution."

    def _recent_order_activity(self, recent_orders) -> list[RecentOrderInfo]:
        sortable: list[tuple[datetime, RecentOrderInfo]] = []
        for order in recent_orders:
            raw = order.raw or {}
            submitted_at = raw.get("filled_at") or raw.get("submitted_at") or raw.get("created_at")
            if not submitted_at:
                continue
            try:
                submitted_dt = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
            except ValueError:
                continue
            sortable.append(
                (
                    submitted_dt.astimezone(UTC),
                    RecentOrderInfo(
                        symbol=order.symbol,
                        asset_class=infer_symbol_asset_class(order.symbol),
                        side=str(order.side),
                        status=str(order.status),
                        amount_label=self._recent_order_amount_label(order),
                        price_label=self._recent_order_price_label(order),
                        submitted_at=submitted_dt.astimezone(UTC).isoformat(),
                    ),
                )
            )
        sortable.sort(key=lambda item: item[0], reverse=True)
        if not sortable:
            return []

        by_asset_class: dict[str, list[tuple[datetime, RecentOrderInfo]]] = {}
        for item in sortable:
            by_asset_class.setdefault(item[1].asset_class, []).append(item)

        if len(by_asset_class) <= 1:
            return [item for _, item in sortable[:5]]

        selected: list[tuple[datetime, RecentOrderInfo]] = []
        for asset_class in ("crypto", "us_equity"):
            items = by_asset_class.get(asset_class, [])
            if items:
                selected.append(items[0])

        seen_keys = {
            (entry[1].symbol, entry[1].side, entry[1].status, entry[1].submitted_at)
            for entry in selected
        }
        for item in sortable:
            key = (item[1].symbol, item[1].side, item[1].status, item[1].submitted_at)
            if key in seen_keys:
                continue
            selected.append(item)
            seen_keys.add(key)
            if len(selected) >= 5:
                break

        selected.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in selected[:5]]

    @staticmethod
    def _recent_order_amount_label(order) -> str:
        raw = order.raw or {}
        quantity = order.quantity or raw.get("qty") or raw.get("quantity")
        if quantity:
            try:
                amount = f"{float(quantity):.6f}".rstrip("0").rstrip(".")
                symbol = str(order.symbol or "").strip()
                return f"{amount} {symbol}".strip()
            except (TypeError, ValueError):
                pass
        notional = order.notional or raw.get("notional")
        if notional:
            try:
                return f"${float(notional):.2f} notional"
            except (TypeError, ValueError):
                pass
        return "n/a"

    @staticmethod
    def _recent_order_price_label(order) -> str:
        raw = order.raw or {}
        notional = order.notional or raw.get("notional")
        if notional:
            try:
                return f"${float(notional):,.2f}"
            except (TypeError, ValueError):
                return str(notional)
        price = raw.get("filled_avg_price") or raw.get("limit_price")
        if price:
            try:
                return f"${float(price):,.2f}"
            except (TypeError, ValueError):
                return str(price)
        quantity = order.quantity or raw.get("qty") or raw.get("quantity")
        if quantity and notional:
            try:
                computed = float(notional) / float(quantity)
                return f"${computed:,.2f}"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        return ""

    @staticmethod
    def _recent_order_time_label(submitted_at: str) -> str:
        try:
            submitted_dt = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
        except ValueError:
            return "--.--"
        return submitted_dt.astimezone().strftime("%H.%M")

    def _recommend_position(
        self,
        *,
        unrealized_pl_percent: float,
        current_price: float,
        average_entry_price: float | None,
        trend_percent: float,
        volatility_percent: float,
        has_position: bool,
        strategy_setup: str,
        signal_action: str,
        momentum_percent: float,
        moving_average_gap_percent: float,
    ) -> tuple[str, str, str]:
        if not has_position and strategy_setup == "BREAKOUT_BUY":
            return ("BUY_CANDIDATE", "medium", "Trend breakout is live above recent resistance.")
        if not has_position and strategy_setup == "PULLBACK_BUY":
            return ("BUY_CANDIDATE", "medium", "Trend is healthy and price is pulling back into the fast moving average.")
        if not has_position and strategy_setup == "TREND_WATCH":
            return ("WATCH", "medium", "Trend is positive, but the strategy wants a cleaner pullback or breakout.")
        if has_position and signal_action == "SELL":
            if moving_average_gap_percent < 0 and momentum_percent <= 0:
                return (
                    "SELL_OR_REDUCE",
                    "high",
                    "Fast trend has crossed below the slow trend and momentum turned negative.",
                )
            if moving_average_gap_percent < 0:
                return (
                    "SELL_OR_REDUCE",
                    "high",
                    "Fast moving average fell below the slow moving average.",
                )
            return (
                "SELL_OR_REDUCE",
                "high",
                "Momentum fell below the configured exit threshold.",
            )
        if has_position and unrealized_pl_percent <= -5:
            return ("SELL_OR_REDUCE", "high", "Position is materially underwater; reduce exposure or exit.")
        if has_position and unrealized_pl_percent >= 5 and trend_percent > 0:
            return ("HOLD_OR_SCALE", "medium", "Position is profitable; hold and consider scaling carefully.")
        if has_position and average_entry_price is not None and current_price > average_entry_price and volatility_percent < 3:
            return ("HOLD", "low", "Price remains above entry and the position is stable.")
        if not has_position and trend_percent > 3 and volatility_percent < 4:
            return ("BUY_CANDIDATE", "medium", "Trend is positive and volatility is controlled.")
        if not has_position and trend_percent < -3:
            return ("AVOID_OR_WAIT", "high", "Trend is negative; avoid adding fresh exposure right now.")
        if volatility_percent >= 6:
            return ("WATCH", "high", "Volatility is elevated; wait for cleaner conditions.")
        return ("WATCH", "medium", "Signal is mixed; monitor before increasing allocation.")

    @staticmethod
    def _group_event_alerts(alerts: list[RunEvent]) -> dict[str, list[RunEvent]]:
        grouped: dict[str, list[RunEvent]] = {}
        for alert in alerts:
            if alert.event_type != "event_risk_alert":
                continue
            symbol = str(alert.details.get("symbol", ""))
            if not symbol:
                continue
            grouped.setdefault(symbol, []).append(alert)
        return grouped

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

    def _apply_event_override(
        self,
        *,
        symbol: str,
        recommendation: str,
        risk_level: str,
        rationale: str,
        alerts: list[RunEvent],
    ) -> tuple[str, str, str]:
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        highest = max(alerts, key=lambda alert: severity_rank.get(str(alert.details.get("severity", "low")), 0))
        severity = str(highest.details.get("severity", "medium"))
        override = str(highest.details.get("recommendation_override", recommendation))
        event_summary = str(highest.details.get("summary", highest.message))
        risk_level = max(risk_level, severity, key=lambda x: severity_rank.get(x, 0))
        return (
            override,
            risk_level,
            f"{rationale} Event risk for {symbol}: {severity.upper()} - {event_summary}",
        )

    @staticmethod
    def _apply_operator_override(
        *,
        recommendation: str,
        risk_level: str,
        rationale: str,
        override_action: str,
    ) -> tuple[str, str, str]:
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}

        def escalate(base: str, target: str) -> str:
            return max(base, target, key=lambda value: severity_rank.get(value, 0))

        override_map = {
            "buy": ("MANUAL_BUY", escalate(risk_level, "medium"), "Operator requested a manual buy."),
            "sell": ("MANUAL_SELL", "high", "Operator requested a manual sell."),
            "hold": ("MANUAL_HOLD", risk_level, "Operator requested holding the position."),
            "skip": ("SKIP_FOR_NOW", escalate(risk_level, "medium"), "Operator requested skipping this idea."),
            "pause_auto": ("AUTO_PAUSED", escalate(risk_level, "medium"), "Operator paused automated trading for this symbol."),
            "approve_ai": (recommendation, risk_level, "Operator approved the AI recommendation."),
        }
        mapped = override_map.get(override_action)
        if mapped is None:
            return recommendation, risk_level, rationale
        next_recommendation, next_risk, override_note = mapped
        risk = max(risk_level, next_risk, key=lambda value: severity_rank.get(value, 0))
        return next_recommendation, risk, f"{rationale} {override_note}"

    @staticmethod
    def _trend_percent(bars: list[MarketBar]) -> float:
        if len(bars) < 2 or bars[0].close == 0:
            return 0.0
        return ((bars[-1].close - bars[0].close) / bars[0].close) * 100

    @staticmethod
    def _volatility_percent(bars: list[MarketBar]) -> float:
        if not bars:
            return 0.0
        closes = [bar.close for bar in bars]
        average = sum(closes) / len(closes)
        if average == 0:
            return 0.0
        variance = sum((value - average) ** 2 for value in closes) / len(closes)
        return (variance ** 0.5 / average) * 100

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

    def _render_html(self, snapshot: DashboardSnapshot) -> str:
        generated_label = self._format_display_datetime(snapshot.generated_at)
        recommendation_rows = "\n".join(
            (
                "<tr>"
                f"<td>{item.symbol}</td>"
                f"<td>${item.current_price:.2f}</td>"
                f"<td>${item.market_value:.2f}</td>"
                f"<td>${item.unrealized_pl:.2f}</td>"
                f"<td>{item.unrealized_pl_percent:.2f}%</td>"
                f"<td><span class='risk {item.risk_level}'>{item.risk_level.upper()}</span></td>"
                f"<td>{item.recommendation}</td>"
                f"<td>{item.rationale}<br /><span class='label'>Setup {item.strategy_setup} | Signal {item.signal_action} | Conf {item.signal_confidence:.2f}</span><br /><span class='label'>Fast {item.fast_moving_average:.2f} | Slow {item.slow_moving_average:.2f} | Mom {item.momentum_percent:.2f}% | Gap {item.moving_average_gap_percent:.2f}%</span><br /><span class='label'>Breakout {item.breakout_level:.2f} | Pullback {item.pullback_level:.2f} | Stop {item.stop_price:.2f} | Trail {item.trailing_stop_price:.2f} | Target {item.target_price:.2f}</span><br /><span class='label'>Why: {item.signal_reason}</span></td>"
                "</tr>"
            )
            for item in snapshot.recommendations
        ) or "<tr><td colspan='8'>No assets available yet.</td></tr>"

        alert_rows = "\n".join(
            f"<li><strong>{alert.event_type}</strong>: {alert.message} - {alert.details}</li>"
            for alert in snapshot.alerts
        ) or "<li>No active alerts.</li>"

        invested_percent = (snapshot.invested_value / snapshot.total_equity * 100) if snapshot.total_equity else 0.0
        cash_percent = 100 - invested_percent if snapshot.total_equity else 0.0
        portfolio_svg = self._sparkline_svg(snapshot.portfolio_history, stroke="#1d5c63")
        asset_chart_blocks = "\n".join(
            (
                "<div class='chart-card'>"
                f"<h3>{chart.symbol}</h3>"
                f"{self._sparkline_svg(chart.points, stroke='#2f7d4c', markers=chart.markers)}"
                f"<div class='chart-meta'>{len(chart.markers)} markers recorded</div>"
                "</div>"
            )
            for chart in snapshot.asset_charts
        ) or "<div class='chart-card'>No chart data available yet.</div>"
        symbol_perf_rows = "\n".join(
            (
                "<tr>"
                f"<td>{item.symbol}</td>"
                f"<td>${item.realized_pl:.2f}</td>"
                f"<td>{item.realized_trades}</td>"
                f"<td>{item.open_quantity:.4f}</td>"
                f"<td>${item.average_cost:.2f}</td>"
                f"<td>{item.last_strategy}</td>"
                "</tr>"
            )
            for item in snapshot.symbol_performance
        ) or "<tr><td colspan='6'>No realized trades recorded yet.</td></tr>"
        strategy_perf_rows = "\n".join(
            (
                "<tr>"
                f"<td>{item.strategy_name}</td>"
                f"<td>${item.realized_pl:.2f}</td>"
                f"<td>{item.realized_trades}</td>"
                "</tr>"
            )
            for item in snapshot.strategy_performance
        ) or "<tr><td colspan='3'>No strategy performance yet.</td></tr>"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Autotrade Dashboard</title>
  <style>
    :root {{
      --bg: #f4f1ea; --panel: #fffdf8; --ink: #1e1b18; --muted: #6c655f; --line: #d9d0c6;
      --good: #2f7d4c; --warn: #c37b1f; --bad: #b33a3a; --accent: #1d5c63;
    }}
    body {{ margin:0; font-family: Georgia, "Times New Roman", serif; background:linear-gradient(180deg,#ebe4d8 0%,var(--bg) 55%,#f8f5ef 100%); color:var(--ink); }}
    .wrap {{ max-width:1180px; margin:0 auto; padding:32px 20px 48px; }}
    .hero {{ display:grid; grid-template-columns:1.5fr 1fr; gap:20px; }}
    .panel {{ background:var(--panel); border:1px solid var(--line); border-radius:18px; padding:20px; box-shadow:0 14px 40px rgba(56,45,30,0.08); }}
    h1,h2,h3 {{ margin:0 0 12px; font-weight:600; }}
    .sub {{ color:var(--muted); margin-bottom:18px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:18px; }}
    .card,.chart-card {{ background:#fcfaf4; border:1px solid var(--line); border-radius:14px; padding:14px; }}
    .label,.chart-meta {{ color:var(--muted); font-size:0.9rem; }}
    .value {{ font-size:1.5rem; margin-top:6px; }}
    .allocation {{ display:flex; gap:10px; margin-top:18px; align-items:center; }}
    .bar {{ flex:1; height:18px; background:#e8ded2; border-radius:999px; overflow:hidden; border:1px solid var(--line); }}
    .bar span {{ display:block; height:100%; background:linear-gradient(90deg,var(--accent),#4f8d95); width:{invested_percent:.2f}%; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
    th,td {{ text-align:left; padding:12px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ color:var(--muted); font-size:0.9rem; font-weight:600; letter-spacing:0.02em; }}
    .risk {{ display:inline-block; padding:4px 10px; border-radius:999px; color:white; font-size:0.8rem; }}
    .risk.low {{ background:var(--good); }} .risk.medium {{ background:var(--warn); }} .risk.high {{ background:var(--bad); }} .risk.critical {{ background:#5c1b1b; }}
    ul {{ margin:0; padding-left:18px; }}
    .split {{ display:grid; grid-template-columns:2fr 1fr; gap:20px; margin-top:20px; }}
    .chart-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:20px; margin-top:20px; }}
    svg {{ width:100%; height:170px; display:block; background:linear-gradient(180deg,rgba(29,92,99,0.06),rgba(29,92,99,0)); border-radius:12px; margin-top:12px; }}
    @media (max-width:900px) {{ .hero,.split,.cards,.chart-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <section class="panel">
        <h1>Autotrade Portfolio Dashboard</h1>
        <div class="sub">Generated {generated_label} | Designed for fast trading updates and risk reviews.</div>
        <div class="cards">
          <div class="card"><div class="label">Total Equity</div><div class="value">${snapshot.total_equity:.2f}</div></div>
          <div class="card"><div class="label">Cash</div><div class="value">${snapshot.cash:.2f}</div></div>
          <div class="card"><div class="label">Buying Power</div><div class="value">${snapshot.buying_power:.2f}</div></div>
          <div class="card"><div class="label">Open Orders</div><div class="value">{snapshot.open_orders_count}</div></div>
        </div>
        <div class="allocation">
          <div style="min-width:140px;"><strong>Capital Allocation</strong><br /><span class="label">Invested ${snapshot.invested_value:.2f} | Cash {cash_percent:.2f}%</span></div>
          <div class="bar"><span></span></div>
        </div>
      </section>
      <aside class="panel">
        <h2>Alerts And Warnings</h2>
        <div class="sub">These should become your red-light system for manual review or automated exits.</div>
        <ul>{alert_rows}</ul>
      </aside>
    </div>
    <section class="panel" style="margin-top:20px;">
      <h2>Equity Curve</h2>
      <div class="sub">This becomes more meaningful as repeated runs append history into the project.</div>
      {portfolio_svg}
    </section>
    <div class="split">
      <section class="panel">
        <h2>Per-Asset Recommendation Board</h2>
        <div class="sub">This now includes watchlist opportunities as well as held positions.</div>
        <table>
          <thead><tr><th>Symbol</th><th>Price</th><th>Invested</th><th>P/L</th><th>P/L %</th><th>Risk</th><th>Recommendation</th><th>Rationale</th></tr></thead>
          <tbody>{recommendation_rows}</tbody>
        </table>
      </section>
      <aside class="panel">
        <h2>What This Dashboard Will Grow Into</h2>
        <ul>
          <li>buy and sell markers on historical price charts</li>
          <li>per-strategy performance attribution</li>
          <li>news and event-linked risk warnings</li>
          <li>automatic sell or reallocation logic when risk turns critical</li>
          <li>multi-run profit tracking across sessions</li>
        </ul>
      </aside>
    </div>
    <div class="split">
      <section class="panel">
        <h2>Realized P&amp;L By Symbol</h2>
        <table>
          <thead><tr><th>Symbol</th><th>Realized P/L</th><th>Closed Trades</th><th>Open Qty</th><th>Avg Cost</th><th>Last Strategy</th></tr></thead>
          <tbody>{symbol_perf_rows}</tbody>
        </table>
      </section>
      <aside class="panel">
        <h2>Strategy Performance</h2>
        <table>
          <thead><tr><th>Strategy</th><th>Realized P/L</th><th>Closed Trades</th></tr></thead>
          <tbody>{strategy_perf_rows}</tbody>
        </table>
      </aside>
    </div>
    <section class="panel" style="margin-top:20px;">
      <h2>Asset Charts And Trade Markers</h2>
      <div class="sub">Charts now use historical bars and merge in stored trade markers over time.</div>
      <div class="chart-grid">{asset_chart_blocks}</div>
    </section>
  </div>
</body>
</html>"""

    def _render_operator_window(self, snapshot: DashboardSnapshot) -> str:
        generated_label = self._format_display_datetime(snapshot.generated_at)
        crypto_count = sum(1 for item in snapshot.recommendations if item.asset_class == "crypto")
        equity_count = sum(1 for item in snapshot.recommendations if item.asset_class != "crypto")
        market_summary = (
            f"<span class='market-pill'>Tracking {len(snapshot.recommendations)} assets</span>"
            f"<span class='market-pill equity'>Equities {equity_count}</span>"
            f"<span class='market-pill crypto'>Crypto {crypto_count}</span>"
        )
        equity_market_value = sum(item.market_value for item in snapshot.recommendations if item.asset_class != "crypto")
        crypto_market_value = sum(item.market_value for item in snapshot.recommendations if item.asset_class == "crypto")
        equity_pending_value = sum(item.notional_value for item in snapshot.open_order_details if item.asset_class != "crypto")
        crypto_pending_value = sum(item.notional_value for item in snapshot.open_order_details if item.asset_class == "crypto")
        desk_summary = (
            "<div class='desk-grid'>"
            f"<section class='desk-card equity'><div class='desk-head'><span class='desk-kicker'>Equities Desk</span><span class='desk-count'>{equity_count} tracked</span></div><strong>${equity_market_value:.2f}</strong><small>Filled value</small><div class='desk-meta'><span>Pending ${equity_pending_value:.2f}</span><span>Session-aware execution</span></div></section>"
            f"<section class='desk-card crypto'><div class='desk-head'><span class='desk-kicker'>Crypto Desk</span><span class='desk-count'>{crypto_count} tracked</span></div><strong>${crypto_market_value:.2f}</strong><small>Filled value</small><div class='desk-meta'><span>Pending ${crypto_pending_value:.2f}</span><span>24/7 execution path</span></div></section>"
            "</div>"
        )
        def movement_for_symbol(symbol: str) -> tuple[float, float]:
            chart = next((item for item in snapshot.asset_charts if item.symbol == symbol), None)
            if chart is None or len(chart.points) < 2:
                return (0.0, 0.0)
            previous = chart.points[-2].value
            current = chart.points[-1].value
            if previous == 0:
                return (current - previous, 0.0)
            change = current - previous
            return (change, (change / previous) * 100)

        def zones_for_item(item: AssetRecommendation) -> tuple[float, float]:
            if item.suggested_buy_price > 0 or item.suggested_sell_price > 0:
                buy_zone = item.suggested_buy_price or item.current_price * 0.98
                sell_zone = item.suggested_sell_price or item.current_price * 1.02
                return (buy_zone, sell_zone)
            chart = next((asset for asset in snapshot.asset_charts if asset.symbol == item.symbol), None)
            if chart is None or not chart.points:
                return (item.current_price * 0.98, item.current_price * 1.02)
            closes = [point.value for point in chart.points[-10:]]
            recent_low = min(closes)
            recent_high = max(closes)
            spread = max(recent_high - recent_low, item.current_price * 0.01)
            buy_zone = min(item.current_price * 0.995, recent_low + spread * 0.1)
            sell_zone = max(item.current_price * 1.005, recent_high - spread * 0.1)
            return (buy_zone, sell_zone)

        asset_cards = []
        for item in snapshot.recommendations:
            chart = next((asset for asset in snapshot.asset_charts if asset.symbol == item.symbol), None)
            chart_svg = self._sparkline_svg(chart.points if chart else [], stroke="#145a8d", markers=chart.markers if chart else [])
            delta_value, delta_percent = movement_for_symbol(item.symbol)
            buy_zone, sell_zone = zones_for_item(item)
            movement_class = "up" if delta_value > 0 else "down" if delta_value < 0 else "flat"
            asset_cards.append(
                (
                    f"<section class='asset-card' data-asset-class='{item.asset_class}'>"
                    f"<div class='asset-top'><div><div class='asset-label-row'><h2>{item.symbol}</h2><span class='asset-pill {item.asset_class}'>{item.asset_class.replace('_', ' ').upper()}</span></div><div class='price'>${item.current_price:.2f}</div></div>"
                    f"<div class='move {movement_class}'>{delta_value:+.2f} / {delta_percent:+.2f}% since last update</div></div>"
                    f"<div class='chart-wrap'>{chart_svg}</div>"
                    "<div class='zones'>"
                    f"<div><span>Suggested Buy Zone</span><strong>${buy_zone:.2f}</strong></div>"
                    f"<div><span>Suggested Sell Zone</span><strong>${sell_zone:.2f}</strong></div>"
                    "</div>"
                    "<div class='meta-grid'>"
                    f"<div><span>AI Recommendation</span><strong>{item.recommendation}</strong></div>"
                    f"<div><span>Risk</span><strong class='risk {item.risk_level}'>{item.risk_level.upper()}</strong></div>"
                    f"<div><span>Invested</span><strong>${item.market_value:.2f}</strong></div>"
                    f"<div><span>Unrealized P/L</span><strong>${item.unrealized_pl:.2f} ({item.unrealized_pl_percent:.2f}%)</strong></div>"
                    "</div>"
                    "<div class='meta-grid'>"
                    f"<div><span>Setup</span><strong>{item.strategy_setup}</strong></div>"
                    f"<div><span>Signal</span><strong>{item.signal_action} ({item.signal_confidence:.2f})</strong></div>"
                    f"<div><span>Fast / Slow MA</span><strong>{item.fast_moving_average:.2f} / {item.slow_moving_average:.2f}</strong></div>"
                    f"<div><span>Momentum</span><strong>{item.momentum_percent:.2f}%</strong></div>"
                    f"<div><span>MA Gap</span><strong>{item.moving_average_gap_percent:.2f}%</strong></div>"
                    f"<div><span>Breakout / Pullback</span><strong>{item.breakout_level:.2f} / {item.pullback_level:.2f}</strong></div>"
                    f"<div><span>Stop / Trail</span><strong>{item.stop_price:.2f} / {item.trailing_stop_price:.2f}</strong></div>"
                    f"<div><span>Target</span><strong>{item.target_price:.2f}</strong></div>"
                    "</div>"
                    f"<div class='strategy-note'><span>Signal Basis</span><strong>{item.signal_reason}</strong></div>"
                    f"<p class='rationale'>{item.rationale}</p>"
                    f"<div class='action-row' data-symbol='{item.symbol}'>"
                    "<button data-action='buy'>Buy</button>"
                    "<button data-action='sell'>Sell</button>"
                    "<button data-action='hold'>Hold</button>"
                    "<button data-action='skip'>Skip</button>"
                    "<button data-action='pause'>Pause Auto</button>"
                    "</div>"
                    f"<div class='override-note' id='override-{item.symbol}'>No manual override yet.</div>"
                    "</section>"
                )
            )

        alert_blocks = "\n".join(
            f"<li><strong>{alert.event_type}</strong> {alert.message}</li>" for alert in snapshot.alerts
        ) or "<li>No active warnings right now.</li>"
        open_order_rows = (
            "".join(
                (
                    f"<div class='pending-order-row'>"
                    f"<span>{detail.symbol} {detail.side.upper()}</span>"
                    f"<strong>${detail.notional_value:.2f}</strong>"
                    f"<small>{detail.status.upper()}</small>"
                    f"</div>"
                )
                for detail in snapshot.open_order_details[:6]
            )
            if snapshot.open_order_details
            else "<div class='pending-order-empty'>No pending open orders right now.</div>"
        )
        def recent_order_status_class(status: str) -> str:
            normalized = str(status or "").strip().lower()
            if normalized in {"filled", "done_for_day", "completed"}:
                return "filled"
            if normalized in {"accepted", "new", "pending_new", "pending_replace", "held"}:
                return "pending"
            if normalized in {"partially_filled", "pending_cancel", "pending_review"}:
                return "partial"
            if normalized in {"canceled", "cancelled", "rejected", "expired", "stopped", "suspended"}:
                return "failed"
            return "pending"

        def recent_order_status_label(status: str) -> str:
            normalized = str(status or "").strip().lower()
            if normalized in {"filled", "done_for_day", "completed"}:
                return "FULFILLED"
            if normalized in {"partially_filled", "pending_cancel", "pending_review"}:
                return "PARTIAL"
            if normalized in {"canceled", "cancelled", "rejected", "expired", "stopped", "suspended"}:
                return "FAILED"
            return "PENDING"

        recent_order_rows = (
            "".join(
                (
                    f"<div class='trade-order-row {recent_order_status_class(order.status)}'>"
                    f"<span class='trade-order-dot'></span>"
                    f"<div class='trade-order-copy'>"
                    f"<strong>{order.side.upper()} {order.symbol}</strong>"
                    f"<small>{self._recent_order_time_label(order.submitted_at)} · {order.amount_label} - {order.price_label}</small>"
                    f"</div>"
                    f"<span class='trade-order-pill {recent_order_status_class(order.status)}'>{recent_order_status_label(order.status)}</span>"
                    f"</div>"
                )
                for order in snapshot.recent_order_activity[:5]
            )
            if snapshot.recent_order_activity
            else "<div class='trade-order-empty'>No recent trade orders yet.</div>"
        )

        snapshot_json = json.dumps(asdict(snapshot), default=str).replace("</", "<\\/")
        favicon_svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#08111a"/>
  <rect x="6" y="6" width="52" height="52" rx="12" fill="#101c28" stroke="#22384b" stroke-width="2"/>
  <circle cx="24" cy="24" r="4" fill="#5db7ff"/>
  <circle cx="40" cy="24" r="4" fill="#5db7ff"/>
  <path d="M18 40 C24 46, 40 46, 46 40" fill="none" stroke="#f4b04f" stroke-width="3.5" stroke-linecap="round"/>
  <path d="M14 38 L23 31 L31 35 L41 20 L50 24" fill="none" stroke="#2bd67b" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""".strip()
        favicon_uri = f"data:image/svg+xml,{quote(favicon_svg)}"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Slim's AI Autotrader</title>
  <link rel="icon" href="{favicon_uri}" type="image/svg+xml" />
  <style>
    :root {{
      --bg:#08111a; --panel:#101c28; --panel-2:#132434; --ink:#e9f1f7; --muted:#91a6b7; --line:#22384b;
      --good:#2bd67b; --warn:#f4b04f; --bad:#ff6b6b; --critical:#ff3b3b; --accent:#5db7ff;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:radial-gradient(circle at top,#15293a 0%,#0b1520 35%,#08111a 100%); color:var(--ink); font-family: "Segoe UI", Tahoma, sans-serif; }}
    .wrap {{ max-width:1540px; margin:0 auto; padding:20px 28px 110px; }}
    .topbar {{ display:grid; grid-template-columns:minmax(0,1.7fr) minmax(430px,1.1fr); gap:20px; margin-bottom:16px; align-items:start; }}
    .panel {{ background:linear-gradient(180deg,var(--panel) 0%,var(--panel-2) 100%); border:1px solid var(--line); border-radius:20px; padding:20px; box-shadow:0 18px 44px rgba(0,0,0,0.32); }}
    h1,h2,h3,p {{ margin:0; }}
    .panel-head {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:start; }}
    .panel-head-copy {{ min-width:0; }}
    .panel-head-copy h1 {{ font-size:clamp(2.1rem, 3vw, 3rem); line-height:1.02; letter-spacing:-0.03em; }}
    .panel-head-copy .eyebrow {{ display:inline-flex; align-items:center; gap:8px; margin-bottom:10px; padding:6px 10px; border-radius:999px; background:rgba(93,183,255,0.08); border:1px solid rgba(93,183,255,0.16); color:#9fd4ff; font-size:0.78rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; }}
    .panel-head-actions {{ display:flex; align-items:center; gap:10px; justify-content:flex-end; flex-wrap:wrap; }}
    .sub {{ color:var(--muted); margin-top:8px; line-height:1.45; max-width:62ch; }}
    .market-strip {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
    .market-pill {{ display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px; background:rgba(255,255,255,0.05); border:1px solid rgba(145,166,183,0.18); color:#d8e7f2; font-size:0.76rem; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; }}
    .market-pill.equity {{ background:rgba(93,183,255,0.10); border-color:rgba(93,183,255,0.2); color:#a7d7ff; }}
    .market-pill.crypto {{ background:rgba(43,214,123,0.10); border-color:rgba(43,214,123,0.2); color:#95efb9; }}
    .desk-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:14px; }}
    .desk-card {{ border:1px solid var(--line); border-radius:16px; padding:14px; background:linear-gradient(180deg,rgba(255,255,255,0.035) 0%,rgba(255,255,255,0.02) 100%); }}
    .desk-card strong {{ display:block; font-size:1.3rem; margin-top:8px; letter-spacing:-0.03em; }}
    .desk-card small {{ display:block; margin-top:4px; color:var(--muted); font-size:0.74rem; }}
    .desk-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }}
    .desk-kicker {{ font-size:0.78rem; font-weight:800; letter-spacing:0.05em; text-transform:uppercase; }}
    .desk-count {{ font-size:0.75rem; color:var(--muted); }}
    .desk-meta {{ display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap; margin-top:10px; color:#c3d2dd; font-size:0.78rem; }}
    .desk-card.equity {{ box-shadow:inset 0 0 0 1px rgba(93,183,255,0.08); }}
    .desk-card.equity .desk-kicker {{ color:#a7d7ff; }}
    .desk-card.crypto {{ box-shadow:inset 0 0 0 1px rgba(43,214,123,0.08); }}
    .desk-card.crypto .desk-kicker {{ color:#95efb9; }}
    .view-toggle-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin:16px 0 12px; }}
    .view-toggle-group {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .view-toggle-button {{ background:rgba(255,255,255,0.05); border:1px solid rgba(145,166,183,0.18); color:#dbe8f2; }}
    .view-toggle-button.active {{ background:linear-gradient(180deg,rgba(93,183,255,0.24) 0%,rgba(33,95,148,0.34) 100%); border-color:rgba(93,183,255,0.32); }}
    .view-note {{ color:var(--muted); font-size:0.82rem; }}
    .stat-grid {{ display:grid; grid-template-columns:repeat(6,minmax(112px,1fr)); gap:10px; margin-top:18px; }}
    .stat {{ position:relative; overflow:hidden; background:linear-gradient(180deg,rgba(255,255,255,0.045) 0%,rgba(255,255,255,0.025) 100%); border:1px solid var(--line); border-radius:16px; padding:12px 12px 11px; box-shadow:inset 0 1px 0 rgba(255,255,255,0.04); }}
    .stat::before {{ content:""; position:absolute; inset:0 auto 0 0; width:4px; background:var(--accent-soft,#5db7ff); opacity:0.95; }}
    .stat::after {{ content:""; position:absolute; right:-28px; top:-28px; width:82px; height:82px; border-radius:999px; background:var(--accent-glow,rgba(93,183,255,0.12)); filter:blur(2px); }}
    .stat span {{ display:block; color:var(--muted); font-size:0.78rem; letter-spacing:0.05em; text-transform:uppercase; }}
    .stat strong {{ display:block; font-size:1.26rem; margin-top:6px; letter-spacing:-0.03em; position:relative; z-index:1; }}
    .stat small {{ display:block; margin-top:6px; color:#9eb3c4; font-size:0.7rem; position:relative; z-index:1; line-height:1.35; }}
    .stat.equity {{ --accent-soft:#5db7ff; --accent-glow:rgba(93,183,255,0.16); }}
    .stat.cash {{ --accent-soft:#2bd67b; --accent-glow:rgba(43,214,123,0.15); }}
    .stat.cost {{ --accent-soft:#c98cff; --accent-glow:rgba(201,140,255,0.16); }}
    .stat.filled {{ --accent-soft:#f4b04f; --accent-glow:rgba(244,176,79,0.16); }}
    .stat.pending {{ --accent-soft:#ff8c6b; --accent-glow:rgba(255,140,107,0.16); }}
    .stat.status {{ --accent-soft:#88f0d5; --accent-glow:rgba(136,240,213,0.14); }}
    .info-box {{ margin-top:14px; background:rgba(255,255,255,0.03); border:1px solid var(--line); border-radius:14px; padding:14px; }}
    .info-box-head {{ display:flex; justify-content:space-between; gap:12px; align-items:baseline; flex-wrap:wrap; }}
    .info-box-head span {{ color:var(--muted); font-size:0.82rem; }}
    .info-box-head strong {{ display:block; font-size:1.02rem; margin-top:4px; }}
    .pending-order-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:12px; }}
    .pending-order-row {{ background:rgba(255,255,255,0.025); border:1px solid rgba(145,166,183,0.12); border-radius:12px; padding:10px 12px; display:grid; grid-template-columns:1fr auto; gap:4px 10px; align-items:center; }}
    .pending-order-row span {{ font-size:0.86rem; color:#dce9f3; }}
    .pending-order-row strong {{ font-size:0.96rem; }}
    .pending-order-row small {{ grid-column:1 / -1; color:var(--muted); font-size:0.72rem; letter-spacing:0.04em; }}
    .pending-order-empty {{ margin-top:12px; color:var(--muted); font-size:0.84rem; }}
    .asset-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }}
    .asset-card {{ background:linear-gradient(180deg,var(--panel) 0%,var(--panel-2) 100%); border:1px solid var(--line); border-radius:18px; padding:15px; box-shadow:0 14px 32px rgba(0,0,0,0.26); }}
    .asset-label-row {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
    .asset-pill {{ display:inline-flex; align-items:center; padding:4px 8px; border-radius:999px; font-size:0.69rem; font-weight:800; letter-spacing:0.05em; text-transform:uppercase; border:1px solid rgba(145,166,183,0.18); color:#dbe9f3; }}
    .asset-pill.us_equity {{ background:rgba(93,183,255,0.10); border-color:rgba(93,183,255,0.24); color:#a6d7ff; }}
    .asset-pill.crypto {{ background:rgba(43,214,123,0.10); border-color:rgba(43,214,123,0.24); color:#98efbc; }}
    .asset-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
    .price {{ font-size:1.46rem; margin-top:4px; }}
    .move {{ font-weight:700; padding:7px 10px; border-radius:999px; font-size:0.84rem; }}
    .move.up {{ background:rgba(43,214,123,0.14); color:var(--good); }}
    .move.down {{ background:rgba(255,107,107,0.14); color:var(--bad); }}
    .move.flat {{ background:rgba(145,166,183,0.14); color:#b3c2ce; }}
    .chart-wrap svg {{ width:100%; height:132px; margin-top:10px; }}
    .zones, .meta-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-top:14px; }}
    .zones div, .meta-grid div {{ background:rgba(255,255,255,0.03); border:1px solid var(--line); border-radius:12px; padding:10px; }}
    .zones span, .meta-grid span {{ display:block; color:var(--muted); font-size:0.78rem; margin-bottom:4px; }}
    .zones strong, .meta-grid strong {{ font-size:0.92rem; line-height:1.35; }}
    .rationale {{ margin-top:12px; line-height:1.4; color:#d7e5f0; font-size:0.9rem; }}
    .risk {{ display:inline-block; padding:4px 10px; border-radius:999px; color:white; font-size:0.8rem; }}
    .risk.low {{ background:var(--good); }} .risk.medium {{ background:var(--warn); }} .risk.high {{ background:var(--bad); }} .risk.critical {{ background:var(--critical); }}
    .action-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }}
    button {{ border:none; border-radius:12px; padding:10px 14px; background:#184765; color:white; font-weight:600; cursor:pointer; }}
    button:hover {{ filter:brightness(1.06); }}
    .override-note {{ margin-top:10px; color:var(--muted); font-size:0.84rem; }}
    .strategy-note {{ margin-top:12px; background:rgba(93,183,255,0.08); border:1px solid rgba(93,183,255,0.18); border-radius:12px; padding:10px; }}
    .strategy-note span {{ display:block; color:var(--muted); font-size:0.78rem; margin-bottom:4px; }}
    .strategy-note strong {{ display:block; font-weight:600; line-height:1.4; }}
    .status-strip {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px 18px; margin-top:18px; color:var(--muted); font-size:0.9rem; align-items:start; }}
    .status-main {{ display:flex; align-items:flex-start; gap:12px; min-width:0; padding-top:4px; }}
    #live-status {{ white-space:normal; overflow:visible; text-overflow:clip; line-height:1.4; max-width:44ch; }}
    .runtime-detail {{ grid-column:1 / -1; font-size:0.79rem; color:#91a6b7; padding-left:2px; margin-top:-2px; line-height:1.45; }}
    .runtime-detail {{ grid-column:1 / -1; font-size:0.79rem; color:#91a6b7; padding-left:2px; margin-top:-2px; line-height:1.45; }}
    .bot-status-grid {{ grid-column:1 / -1; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:4px; }}
    .bot-strip {{ border:1px solid rgba(145,166,183,0.14); background:rgba(255,255,255,0.03); border-radius:16px; padding:14px; min-width:0; position:relative; overflow:hidden; }}
    .bot-strip::before {{ content:""; position:absolute; inset:0 0 auto 0; height:3px; background:linear-gradient(90deg,rgba(93,183,255,0.75),rgba(93,183,255,0.05)); }}
    .bot-strip.crypto::before {{ background:linear-gradient(90deg,rgba(55,214,170,0.82),rgba(55,214,170,0.08)); }}
    .bot-strip.master::before {{ background:linear-gradient(90deg,rgba(255,214,102,0.78),rgba(255,214,102,0.08)); }}
    .bot-strip span {{ display:block; color:var(--muted); font-size:0.72rem; letter-spacing:0.05em; text-transform:uppercase; margin-bottom:8px; }}
    .bot-strip strong {{ display:block; font-size:1rem; color:#f0f6fb; line-height:1.35; }}
    .bot-strip small {{ display:block; margin-top:6px; color:#9eb3c4; font-size:0.76rem; line-height:1.45; }}
    .bot-strip .mini-badge {{ display:inline-flex; align-items:center; gap:6px; margin-top:10px; padding:5px 9px; border-radius:999px; font-size:0.7rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; border:1px solid rgba(145,166,183,0.24); color:#cfe0ed; background:rgba(255,255,255,0.03); }}
    .bot-strip .mini-badge.running {{ color:#7df0ae; border-color:rgba(43,214,123,0.35); background:rgba(43,214,123,0.12); }}
    .bot-strip .mini-badge.waiting {{ color:#a8d7ff; border-color:rgba(93,183,255,0.35); background:rgba(93,183,255,0.12); }}
    .bot-strip .mini-badge.triggered {{ color:#9cf4d8; border-color:rgba(55,214,170,0.35); background:rgba(55,214,170,0.12); }}
    .bot-strip .mini-badge.blocked {{ color:#ffb0b0; border-color:rgba(255,107,107,0.35); background:rgba(255,107,107,0.12); }}
    .status-extras {{ grid-column:1 / -1; display:grid; grid-template-columns:minmax(0,1.1fr) minmax(280px,0.9fr); gap:12px; margin-top:4px; }}
    .process-strip, .activity-strip {{ border:1px solid rgba(145,166,183,0.14); background:rgba(255,255,255,0.03); border-radius:14px; padding:12px 14px; min-width:0; }}
    .process-strip span, .activity-strip span {{ display:block; color:var(--muted); font-size:0.72rem; letter-spacing:0.05em; text-transform:uppercase; margin-bottom:6px; }}
    .process-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 12px; }}
    .process-item {{ min-width:0; }}
    .process-item strong {{ display:block; font-size:0.9rem; color:#e5eef5; }}
    .process-item small {{ display:block; margin-top:4px; color:#8ea4b4; font-size:0.74rem; overflow-wrap:anywhere; }}
    .activity-strip strong {{ display:block; font-size:0.96rem; color:#f0f6fb; line-height:1.35; }}
    .activity-strip small {{ display:block; margin-top:6px; color:#9eb3c4; font-size:0.76rem; line-height:1.4; }}
    .monitor-row {{ margin-top:18px; }}
    .nightwatch-panel {{ border:1px solid rgba(145,166,183,0.16); background:linear-gradient(180deg,rgba(10,21,31,0.92) 0%,rgba(7,15,24,0.94) 100%); border-radius:18px; padding:18px 20px; }}
    .nightwatch-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:12px; }}
    .nightwatch-head h3 {{ margin:0; font-size:1.15rem; }}
    .nightwatch-head p {{ margin:6px 0 0; color:var(--muted); font-size:0.82rem; max-width:640px; }}
    .nightwatch-badge {{ display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px; font-size:0.72rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; border:1px solid rgba(145,166,183,0.24); background:rgba(255,255,255,0.03); color:#cfe0ed; }}
    .nightwatch-badge.active {{ color:#8feab8; border-color:rgba(43,214,123,0.35); background:rgba(43,214,123,0.10); }}
    .nightwatch-badge.idle {{ color:#a8d7ff; border-color:rgba(93,183,255,0.35); background:rgba(93,183,255,0.10); }}
    .nightwatch-badge.alert {{ color:#ffb7b7; border-color:rgba(255,107,107,0.35); background:rgba(255,107,107,0.10); }}
    .nightwatch-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:10px; }}
    .nightwatch-stat {{ border:1px solid rgba(145,166,183,0.14); background:rgba(255,255,255,0.03); border-radius:14px; padding:12px; }}
    .nightwatch-stat span {{ display:block; color:var(--muted); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.04em; }}
    .nightwatch-stat strong {{ display:block; color:#eef5fb; font-size:1.08rem; margin-top:6px; }}
    .nightwatch-note {{ margin-top:12px; color:#9eb3c4; font-size:0.8rem; line-height:1.45; }}
    .nightwatch-list {{ margin-top:12px; display:grid; gap:8px; }}
    .nightwatch-item {{ border:1px solid rgba(145,166,183,0.12); background:rgba(255,255,255,0.025); border-radius:12px; padding:10px 12px; }}
    .nightwatch-item strong {{ display:block; font-size:0.86rem; color:#f0f6fb; }}
    .nightwatch-item small {{ display:block; margin-top:4px; color:#94aabd; font-size:0.76rem; line-height:1.35; }}
    .dot {{ width:10px; height:10px; border-radius:999px; background:var(--good); box-shadow:0 0 12px rgba(43,214,123,0.45); }}
    .status-controls {{ display:flex; align-items:center; justify-content:flex-end; gap:10px; flex-wrap:wrap; }}
    .start-bot-button {{ background:linear-gradient(180deg,rgba(43,214,123,0.28) 0%,rgba(22,128,73,0.32) 100%); border:1px solid rgba(43,214,123,0.35); }}
    .start-run-now-button {{ background:linear-gradient(180deg,rgba(93,183,255,0.24) 0%,rgba(33,95,148,0.34) 100%); border:1px solid rgba(93,183,255,0.32); }}
    .duration-input {{ width:90px; padding:10px 12px; border-radius:12px; border:1px solid var(--line); background:rgba(255,255,255,0.04); color:var(--ink); }}
    .duration-label {{ font-size:0.8rem; color:var(--muted); }}
    .save-duration-button {{ background:#30495b; }}
    .runner-badge {{ display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px; font-size:0.75rem; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; border:1px solid var(--line); }}
    .runner-badge.running {{ background:rgba(43,214,123,0.16); color:var(--good); border-color:rgba(43,214,123,0.3); }}
    .runner-badge.waiting {{ background:rgba(93,183,255,0.14); color:#9dd2ff; border-color:rgba(93,183,255,0.28); }}
    .runner-badge.blocked {{ background:rgba(255,107,107,0.16); color:#ff9b9b; border-color:rgba(255,107,107,0.32); }}
    .runner-badge.finished {{ background:rgba(145,166,183,0.16); color:#c7d3dc; border-color:rgba(145,166,183,0.28); }}
    ul {{ margin:10px 0 0; padding-left:0; list-style:none; }}
    .alert-item {{ display:flex; gap:10px; align-items:flex-start; margin-bottom:10px; }}
    .alert-icon {{ width:22px; min-width:22px; text-align:center; font-weight:700; }}
    .alert-item.user-stop {{ color:#ff8d8d; }}
    .alert-item.user-start {{ color:#96efb8; }}
    .alert-item.warning {{ color:#ffb3a0; }}
    .alert-item.system {{ color:var(--ink); }}
    .side-column {{ display:grid; grid-template-rows:minmax(0,0.3fr) minmax(0,0.82fr) minmax(0,0.5fr) minmax(0,1.28fr); gap:14px; align-self:start; position:sticky; top:16px; max-height:calc(100vh - 32px); min-height:790px; min-width:430px; overflow:hidden; }}
    .side-column > .panel {{ padding:18px 20px; border-radius:18px; }}
    .log-panel {{ min-height:0; display:flex; flex-direction:column; overflow:hidden; }}
    .log-panel::-webkit-scrollbar {{ width:8px; }}
    .log-panel::-webkit-scrollbar-thumb {{ background:rgba(145,166,183,0.28); border-radius:999px; }}
    .log-panel h2, .watch-panel h2, .pulse-panel h2, .trade-panel h2 {{ font-size:1.45rem; line-height:1.08; letter-spacing:-0.025em; }}
    .log-panel .sub, .watch-panel .sub, .pulse-panel .sub, .trade-panel .sub {{ font-size:0.79rem; max-width:none; margin-top:6px; }}
    .log-panel ul {{ margin-top:12px; min-height:0; overflow:hidden; padding-right:0; }}
    .log-panel .alert-item {{ font-size:0.74rem; line-height:1.28; margin-bottom:7px; }}
    .log-panel .alert-item strong {{ display:block; font-size:0.78rem; margin-bottom:2px; }}
    .watch-panel {{ min-height:0; display:flex; flex-direction:column; overflow:hidden; }}
    .market-watch-list {{ margin-top:12px; display:grid; gap:8px; min-height:0; overflow:hidden; }}
    .market-watch-row {{ display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:10px; padding:10px 11px; border-radius:12px; border:1px solid rgba(145,166,183,0.12); background:rgba(255,255,255,0.025); }}
    .market-watch-dot {{ width:10px; height:10px; border-radius:999px; background:#7aa7c5; box-shadow:0 0 12px rgba(122,167,197,0.35); }}
    .market-watch-row.opportunity .market-watch-dot {{ background:var(--good); box-shadow:0 0 12px rgba(43,214,123,0.4); }}
    .market-watch-row.watch .market-watch-dot {{ background:#f4b04f; box-shadow:0 0 12px rgba(244,176,79,0.36); }}
    .market-watch-row.risk .market-watch-dot {{ background:#ff6b6b; box-shadow:0 0 12px rgba(255,107,107,0.38); }}
    .market-watch-row.pending .market-watch-dot {{ background:#5db7ff; box-shadow:0 0 12px rgba(93,183,255,0.4); }}
    .market-watch-copy {{ min-width:0; }}
    .market-watch-copy strong {{ display:block; font-size:0.78rem; color:#f0f6fb; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .market-watch-copy small {{ display:block; margin-top:2px; color:#94aabd; font-size:0.68rem; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .market-watch-badge {{ display:inline-flex; align-items:center; justify-content:center; min-width:76px; height:22px; padding:0 8px; border-radius:999px; font-size:0.6rem; font-weight:800; letter-spacing:0.05em; text-transform:uppercase; border:1px solid rgba(145,166,183,0.2); white-space:nowrap; overflow:hidden; }}
    .market-watch-row.opportunity .market-watch-badge {{ color:#98efbc; background:rgba(43,214,123,0.12); border-color:rgba(43,214,123,0.28); }}
    .market-watch-row.watch .market-watch-badge {{ color:#ffd491; background:rgba(244,176,79,0.12); border-color:rgba(244,176,79,0.28); }}
    .market-watch-row.risk .market-watch-badge {{ color:#ffb0b0; background:rgba(255,107,107,0.12); border-color:rgba(255,107,107,0.28); }}
    .market-watch-row.pending .market-watch-badge {{ color:#a6d7ff; background:rgba(93,183,255,0.12); border-color:rgba(93,183,255,0.28); }}
    .market-watch-empty {{ margin-top:12px; color:var(--muted); font-size:0.82rem; }}
    .pulse-panel {{ min-height:0; display:flex; flex-direction:column; overflow:hidden; }}
    .pulse-grid {{ margin-top:12px; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }}
    .pulse-stat {{ border:1px solid rgba(145,166,183,0.12); background:rgba(255,255,255,0.025); border-radius:12px; padding:10px; }}
    .pulse-stat span {{ display:block; color:var(--muted); font-size:0.68rem; text-transform:uppercase; letter-spacing:0.05em; }}
    .pulse-stat strong {{ display:block; color:#eef5fb; font-size:0.96rem; margin-top:6px; }}
    .pulse-note {{ margin-top:10px; color:#9eb3c4; font-size:0.76rem; line-height:1.4; border:1px solid rgba(145,166,183,0.12); background:rgba(255,255,255,0.025); border-radius:12px; padding:10px; }}
    .trade-panel {{ min-height:0; display:flex; flex-direction:column; overflow:hidden; }}
    .trade-panel::-webkit-scrollbar {{ width:8px; }}
    .trade-panel::-webkit-scrollbar-thumb {{ background:rgba(145,166,183,0.28); border-radius:999px; }}
    .trade-order-list {{ margin-top:12px; display:grid; gap:8px; min-height:0; overflow:auto; padding-right:6px; }}
    .trade-order-row {{ display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:8px; padding:8px 10px; border-radius:12px; border:1px solid rgba(145,166,183,0.12); background:rgba(255,255,255,0.025); }}
    .trade-order-dot {{ width:10px; height:10px; border-radius:999px; background:#7aa7c5; box-shadow:0 0 12px rgba(122,167,197,0.35); }}
    .trade-order-copy {{ min-width:0; }}
    .trade-order-copy strong {{ display:block; font-size:0.78rem; color:#f0f6fb; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .trade-order-copy small {{ display:block; margin-top:2px; color:#94aabd; font-size:0.68rem; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .trade-order-pill {{ display:inline-flex; align-items:center; justify-content:center; min-width:72px; height:22px; padding:0 8px; border-radius:999px; font-size:0.61rem; font-weight:800; letter-spacing:0.05em; text-transform:uppercase; border:1px solid rgba(145,166,183,0.2); white-space:nowrap; overflow:hidden; }}
    .trade-order-row.filled .trade-order-dot {{ background:var(--good); box-shadow:0 0 12px rgba(43,214,123,0.4); }}
    .trade-order-row.filled .trade-order-pill {{ color:#98efbc; background:rgba(43,214,123,0.12); border-color:rgba(43,214,123,0.28); }}
    .trade-order-row.pending .trade-order-dot {{ background:#5db7ff; box-shadow:0 0 12px rgba(93,183,255,0.4); }}
    .trade-order-row.pending .trade-order-pill {{ color:#a6d7ff; background:rgba(93,183,255,0.12); border-color:rgba(93,183,255,0.28); }}
    .trade-order-row.partial .trade-order-dot {{ background:#f4b04f; box-shadow:0 0 12px rgba(244,176,79,0.36); }}
    .trade-order-row.partial .trade-order-pill {{ color:#ffd491; background:rgba(244,176,79,0.12); border-color:rgba(244,176,79,0.28); }}
    .trade-order-row.failed .trade-order-dot {{ background:#ff6b6b; box-shadow:0 0 12px rgba(255,107,107,0.38); }}
    .trade-order-row.failed .trade-order-pill {{ color:#ffb0b0; background:rgba(255,107,107,0.12); border-color:rgba(255,107,107,0.28); }}
    .trade-order-empty {{ margin-top:12px; color:var(--muted); font-size:0.82rem; }}
    .footer-bar {{ position:fixed; left:0; right:0; bottom:0; display:flex; justify-content:center; align-items:center; gap:10px; padding:14px 16px; background:rgba(6,13,20,0.92); backdrop-filter:blur(10px); border-top:1px solid var(--line); }}
    .footer-bar button {{ background:#226186; }}
    .footer-bar button.secondary {{ background:#30495b; }}
    .footer-copy {{ margin-left:18px; color:var(--muted); font-size:0.84rem; letter-spacing:0.02em; white-space:nowrap; }}
    .master-toggle {{ min-width:190px; padding:12px 16px; border-radius:14px; border:1px solid var(--line); text-align:left; box-shadow:0 10px 28px rgba(0,0,0,0.18); position:relative; z-index:3; }}
    .master-toggle .kicker {{ display:block; color:var(--muted); font-size:0.78rem; margin-bottom:4px; }}
    .master-toggle.on {{ background:linear-gradient(180deg,rgba(43,214,123,0.28) 0%,rgba(22,128,73,0.32) 100%); color:var(--ink); border-color:rgba(43,214,123,0.38); }}
    .master-toggle.off {{ background:linear-gradient(180deg,rgba(255,107,107,0.30) 0%,rgba(162,39,39,0.34) 100%); color:var(--ink); border-color:rgba(255,107,107,0.42); }}
    .reload-icon-button {{ width:46px; height:46px; display:flex; align-items:center; justify-content:center; border-radius:14px; border:1px solid var(--line); background:rgba(255,255,255,0.06); color:var(--ink); font-size:1.08rem; box-shadow:0 10px 24px rgba(0,0,0,0.18); }}
    .reload-icon-button:hover {{ background:rgba(93,183,255,0.16); }}
    .plan-settings-button {{ min-width:160px; padding:12px 16px; border-radius:14px; border:1px solid var(--line); background:rgba(255,255,255,0.06); color:var(--ink); font-weight:700; box-shadow:0 10px 24px rgba(0,0,0,0.18); }}
    .plan-settings-button:hover {{ background:rgba(93,183,255,0.16); }}
    .modal-backdrop {{ position:fixed; inset:0; display:none; align-items:center; justify-content:center; padding:28px; background:rgba(3,9,14,0.78); backdrop-filter:blur(8px); z-index:40; }}
    .modal-backdrop.open {{ display:flex; }}
    .modal-panel {{ width:min(1100px, 100%); max-height:calc(100vh - 56px); overflow:auto; background:linear-gradient(180deg,rgba(10,21,31,0.98) 0%,rgba(7,15,24,0.98) 100%); border:1px solid rgba(93,183,255,0.24); border-radius:26px; padding:24px; box-shadow:0 28px 60px rgba(0,0,0,0.35); }}
    .modal-panel h3 {{ margin:0; font-size:1.8rem; letter-spacing:-0.03em; }}
    .modal-close {{ width:42px; height:42px; border-radius:14px; border:1px solid var(--line); background:rgba(255,255,255,0.05); color:var(--ink); font-size:1.1rem; }}
    .modal-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:18px; }}
    .modal-sub {{ color:var(--muted); max-width:780px; }}
    .wallet-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:16px; margin:18px 0; }}
    .wallet-card {{ padding:18px; border-radius:18px; border:1px solid rgba(93,183,255,0.2); background:rgba(255,255,255,0.03); display:flex; flex-direction:column; }}
    .wallet-card span {{ display:flex; align-items:flex-end; min-height:2.2rem; color:var(--muted); font-size:0.8rem; margin-bottom:8px; text-transform:uppercase; letter-spacing:0.04em; line-height:1.2; }}
    .wallet-card strong {{ display:block; font-size:1.7rem; margin-bottom:10px; }}
    .wallet-meta {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; font-size:0.83rem; color:var(--muted); }}
    .wallet-meta b {{ display:block; color:var(--ink); font-size:1rem; margin-top:2px; }}
    .settings-grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:14px; margin:18px 0; }}
    .settings-field {{ display:flex; flex-direction:column; gap:8px; }}
    .settings-field label {{ font-size:0.82rem; color:var(--muted); }}
    .settings-field input, .settings-field select {{ padding:12px 14px; border-radius:14px; border:1px solid var(--line); background:rgba(255,255,255,0.04); color:var(--ink); }}
    .settings-field select {{ appearance:none; -webkit-appearance:none; -moz-appearance:none; background-color:#08111a; color:#f0f6fb; color-scheme:dark; }}
    .settings-field select option {{ background:#08111a; color:#f0f6fb; }}
    .settings-actions {{ display:flex; justify-content:space-between; align-items:center; gap:14px; flex-wrap:wrap; margin-top:18px; }}
    .settings-note {{ color:var(--muted); font-size:0.82rem; }}
    .settings-save-button, .transfer-button {{ background:#145a8d; }}
    .transfer-grid {{ display:grid; grid-template-columns:1.1fr 1.1fr 0.9fr auto; gap:14px; align-items:end; margin-top:14px; }}
    .transfer-card {{ margin-top:18px; padding:18px; border-radius:18px; border:1px solid rgba(93,183,255,0.2); background:rgba(255,255,255,0.03); }}
    .transfer-card h4 {{ margin:0 0 4px; font-size:1.05rem; }}
    .transfer-card p {{ margin:0; color:var(--muted); font-size:0.84rem; }}
    @media (max-width:980px) {{ .topbar,.asset-grid,.stat-grid,.zones,.meta-grid,.status-strip,.panel-head,.desk-grid,.status-extras,.wallet-grid,.settings-grid,.transfer-grid,.nightwatch-grid {{ grid-template-columns:1fr; }} .asset-top {{ flex-direction:column; }} .status-controls, .panel-head-actions,.settings-actions,.nightwatch-head {{ justify-content:flex-start; }} #live-status {{ max-width:none; }} .log-panel,.trade-panel {{ max-height:none; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <section class="panel">
        <div class="panel-head">
          <div class="panel-head-copy">
            <div class="eyebrow">Live Paper Operator</div>
            <h1>Slim's AI Autotrader</h1>
            <p class="sub" id="generated-at">Manual review cockpit for AI trading decisions, pending orders, and session control. Generated {generated_label}.</p>
            <div class="market-strip" id="market-strip">{market_summary}</div>
          </div>
          <div class="panel-head-actions">
            <button type="button" class="plan-settings-button" id="investment-plan-button">
              Investment Plan
            </button>
            <button type="button" class="reload-icon-button" id="full-reload-button" title="Full reload">
              &#x21bb;
            </button>
            <button type="button" class="master-toggle on" id="ai-master-toggle" title="Toggle AI trading">
              <span class="kicker">AI Trading</span>
              <strong id="ai-master-label">ON</strong>
            </button>
          </div>
        </div>
        <div class="stat-grid">
          <div class="stat equity"><span>Total Equity</span><strong id="stat-equity">${snapshot.total_equity:.2f}</strong><small>Account value right now</small></div>
          <div class="stat cash"><span>Cash</span><strong id="stat-cash">${snapshot.cash:.2f}</strong><small>Available unallocated capital</small></div>
          <div class="stat cost"><span>Total Spent</span><strong id="stat-cost-basis">${snapshot.filled_position_cost_basis:.2f}</strong><small>Cost basis of filled buys</small></div>
          <div class="stat filled"><span>Current Value</span><strong id="stat-invested">${snapshot.invested_value:.2f}</strong><small>What filled holdings are worth now</small></div>
          <div class="stat pending"><span>Pending Orders</span><strong id="stat-pending-orders">${snapshot.pending_open_order_value:.2f}</strong><small><span id="stat-orders">{snapshot.open_orders_count}</span> order(s) waiting</small></div>
          <div class="stat status"><span>Order Status</span><strong id="stat-order-status">{snapshot.open_order_status_summary}</strong><small>Pending queue state</small></div>
        </div>
        {desk_summary}
        <div class="info-box">
          <div class="info-box-head">
            <div>
              <span>Open Order Queue</span>
              <strong id="pending-order-value">${snapshot.pending_open_order_value:.2f}</strong>
            </div>
            <span id="pending-order-count-label">{snapshot.open_order_status_summary}</span>
          </div>
          <div class="pending-order-empty" id="pending-order-hint">{snapshot.open_order_fill_hint}</div>
          <div class="pending-order-list" id="pending-order-list">{open_order_rows}</div>
        </div>
        <div class="status-strip">
          <div class="status-main">
            <span class="runner-badge waiting" id="runner-badge">Waiting</span>
            <span class="dot"></span>
            <span id="live-status">Monitoring for fresh dashboard updates.</span>
          </div>
          <div class="status-controls">
            <button type="button" class="start-bot-button" id="start-bot-button">Start Bot</button>
            <button type="button" class="start-run-now-button" id="start-run-now-button">Start Run Now</button>
            <span class="duration-label">Run (min)</span>
            <input type="number" min="1" step="1" class="duration-input" id="duration-minutes-input" value="15" />
            <button type="button" class="save-duration-button" id="save-duration-button">Save</button>
          </div>
          <div class="runtime-detail" id="runtime-detail">Session countdown will appear here once the bot starts.</div>
          <div class="bot-status-grid">
            <div class="bot-strip master">
              <span>Master Session</span>
              <strong id="master-bot-title">Session standby</strong>
              <small id="master-bot-message">Waiting for the first live session update.</small>
              <div class="mini-badge waiting" id="master-bot-badge">Waiting</div>
            </div>
            <div class="bot-strip">
              <span>Equities Desk</span>
              <strong id="equities-bot-title">Scheduled equity cycle</strong>
              <small id="equities-bot-message">Equity runs follow the scheduled timer.</small>
              <div class="mini-badge waiting" id="equities-bot-badge">Waiting</div>
            </div>
            <div class="bot-strip crypto">
              <span>Crypto Desk</span>
              <strong id="crypto-bot-title">Stream-aware crypto cycle</strong>
              <small id="crypto-bot-message">Crypto can wake early on live stream triggers.</small>
              <div class="mini-badge waiting" id="crypto-bot-badge">Waiting</div>
            </div>
          </div>
          <div class="status-extras">
            <div class="process-strip">
              <span>Process / Lock Status</span>
              <div class="process-grid" id="process-grid">
                <div class="process-item"><strong id="bot-pid">n/a</strong><small>Bot PID</small></div>
                <div class="process-item"><strong id="session-lock-pid">n/a</strong><small>Session lock owner</small></div>
                <div class="process-item"><strong id="server-pid">n/a</strong><small>Operator server PID</small></div>
                <div class="process-item"><strong id="server-lock-pid">n/a</strong><small>Server lock owner</small></div>
              </div>
            </div>
            <div class="activity-strip">
              <span>Live Activity</span>
              <strong id="live-activity-title">Waiting for activity...</strong>
              <small id="live-activity-message">The bot will surface its freshest action here during the run.</small>
            </div>
          </div>
        </div>
      </section>
      <aside class="side-column">
        <section class="panel log-panel">
          <h2>Warnings / Logs</h2>
          <p class="sub">Compact operator feed for warnings, confirmations, and recent system notes.</p>
          <ul id="alerts-list">{alert_blocks}</ul>
        </section>
        <section class="panel watch-panel">
          <h2>Market Watch</h2>
          <p class="sub">Live opportunities, risks, and pending situations across equities and crypto.</p>
          <div class="market-watch-list" id="market-watch-list"><div class="market-watch-empty">Loading current market watch...</div></div>
        </section>
        <section class="panel pulse-panel">
          <h2>Desk Pulse</h2>
          <p class="sub">Compact session health, pending load, and the freshest noteworthy action.</p>
          <div class="pulse-grid">
            <div class="pulse-stat"><span>Session</span><strong id="pulse-session-status">Idle</strong></div>
            <div class="pulse-stat"><span>Next Run</span><strong id="pulse-next-run">n/a</strong></div>
            <div class="pulse-stat"><span>Pending USD</span><strong id="pulse-pending-usd">$0.00</strong></div>
            <div class="pulse-stat"><span>Trades</span><strong id="pulse-trade-count">0</strong></div>
          </div>
          <div class="pulse-note" id="pulse-note">Waiting for the first meaningful update...</div>
        </section>
        <section class="panel trade-panel">
          <h2>Last 5 Orders</h2>
          <p class="sub">Fresh broker order activity with quick side, amount, and completion state.</p>
          <div class="trade-order-list" id="trade-order-list">{recent_order_rows}</div>
        </section>
      </aside>
    </div>
    <div class="modal-backdrop" id="investment-plan-modal">
      <div class="modal-panel">
        <div class="modal-head">
          <div>
            <div class="eyebrow">Investment Settings</div>
            <h3>Investment Plan</h3>
            <p class="modal-sub">Broker cash is shared across the Alpaca account. These are internal AI planning buckets for cash buffer, equities, and crypto, so we can steer the bot cleanly without pretending the broker created separate USD subaccounts.</p>
          </div>
          <button type="button" class="modal-close" id="investment-plan-close" title="Close settings">&times;</button>
        </div>
        <div class="wallet-grid" id="investment-wallet-grid">
          <div class="wallet-card"><span>Bot Cash Buffer</span><strong>$0.00</strong><div class="wallet-meta"><div>Broker cash<b>$0.00</b></div><div>Moveable<b>$0.00</b></div></div></div>
          <div class="wallet-card"><span>Equity Stash</span><strong>$0.00</strong><div class="wallet-meta"><div>Committed<b>$0.00</b></div><div>Free<b>$0.00</b></div></div></div>
          <div class="wallet-card"><span>Crypto Stash</span><strong>$0.00</strong><div class="wallet-meta"><div>Committed<b>$0.00</b></div><div>Free<b>$0.00</b></div></div></div>
        </div>
        <div class="settings-grid">
          <div class="settings-field">
            <label for="settings-starting-budget">Starting budget (USD)</label>
            <input type="text" inputmode="decimal" id="settings-starting-budget" value="200,00" />
          </div>
          <div class="settings-field">
            <label for="settings-cash-reserve">Cash reserve (%)</label>
            <input type="text" inputmode="decimal" id="settings-cash-reserve" value="20,00" />
          </div>
          <div class="settings-field">
            <label for="settings-equity-stash">Equity stash (%)</label>
            <input type="text" inputmode="decimal" id="settings-equity-stash" value="25,00" />
          </div>
          <div class="settings-field">
            <label for="settings-crypto-stash">Crypto stash (%)</label>
            <input type="text" inputmode="decimal" id="settings-crypto-stash" value="75,00" />
          </div>
        </div>
        <div class="settings-actions">
          <div class="settings-note" id="investment-plan-note">Changes are saved to the bot plan and apply on the next fresh bot start.</div>
          <button type="button" class="settings-save-button" id="investment-plan-save">Save Plan</button>
        </div>
        <div class="transfer-card">
          <h4>Move USD between wallets</h4>
          <p>Normal broker apps expose available cash, buying power, and portfolio buckets separately. We do the same here, but every move below is an internal bot planning transfer inside one broker cash pool.</p>
          <div class="transfer-grid">
            <div class="settings-field">
              <label for="transfer-from-wallet">From</label>
              <select id="transfer-from-wallet">
                <option value="cash">Bot cash buffer</option>
                <option value="equity">Equity stash</option>
                <option value="crypto">Crypto stash</option>
              </select>
            </div>
            <div class="settings-field">
              <label for="transfer-to-wallet">To</label>
              <select id="transfer-to-wallet">
                <option value="crypto">Crypto stash</option>
                <option value="equity">Equity stash</option>
                <option value="cash">Bot cash buffer</option>
              </select>
            </div>
            <div class="settings-field">
              <label for="transfer-amount">Amount (USD)</label>
              <input type="text" inputmode="decimal" id="transfer-amount" value="10,00" />
            </div>
            <button type="button" class="transfer-button" id="transfer-wallets-button">Move</button>
          </div>
        </div>
      </div>
      </div>
      <div class="monitor-row">
        <section class="nightwatch-panel">
          <div class="nightwatch-head">
            <div>
              <h3>Night Watch</h3>
              <p>Compact session monitor for longer runs, transaction health, warnings, and the latest finished report.</p>
            </div>
            <div class="nightwatch-badge idle" id="nightwatch-badge">Idle</div>
          </div>
          <div class="nightwatch-grid">
            <div class="nightwatch-stat"><span>Session Status</span><strong id="nightwatch-status">Idle</strong></div>
            <div class="nightwatch-stat"><span>Completed Cycles</span><strong id="nightwatch-cycles">0</strong></div>
            <div class="nightwatch-stat"><span>Trades</span><strong id="nightwatch-trades">0</strong></div>
            <div class="nightwatch-stat"><span>Warnings</span><strong id="nightwatch-warnings">0</strong></div>
          </div>
          <div class="nightwatch-note" id="nightwatch-summary">No finished session report yet. The current runtime state will appear here once the bot starts moving.</div>
          <div class="nightwatch-list" id="nightwatch-events">
            <div class="nightwatch-item"><strong>Waiting for the first report...</strong><small>The operator window will summarize the latest session here instead of stuffing Codex with monitor chatter.</small></div>
          </div>
        </section>
      </div>
      <div class="view-toggle-row">
        <div class="view-toggle-group" id="view-toggle-group">
        <button type="button" class="view-toggle-button active" data-view="all">All Markets</button>
        <button type="button" class="view-toggle-button" data-view="us_equity">Equities Desk</button>
        <button type="button" class="view-toggle-button" data-view="crypto">Crypto Desk</button>
      </div>
      <div class="view-note" id="view-note">Showing the combined market desk.</div>
    </div>
    <div class="asset-grid" id="asset-grid">
      {"".join(asset_cards)}
    </div>
  </div>
  <div class="footer-bar">
    <button id="refresh-window">Refresh View</button>
    <button class="secondary" id="approve-all">Approve AI</button>
    <button class="secondary" id="pause-all">Pause Auto</button>
    <button class="secondary" id="clear-overrides">Clear Overrides</button>
    <span class="footer-copy">&copy; SlimShady 2026</span>
  </div>
  <script>
    let currentSnapshot = {snapshot_json};
    const liveStatus = document.getElementById("live-status");
    const aiMasterToggle = document.getElementById("ai-master-toggle");
    const aiMasterLabel = document.getElementById("ai-master-label");
    const investmentPlanButton = document.getElementById("investment-plan-button");
    const investmentPlanModal = document.getElementById("investment-plan-modal");
    const investmentPlanClose = document.getElementById("investment-plan-close");
    const investmentPlanSave = document.getElementById("investment-plan-save");
    const transferWalletsButton = document.getElementById("transfer-wallets-button");
    const investmentWalletGrid = document.getElementById("investment-wallet-grid");
    const investmentPlanNote = document.getElementById("investment-plan-note");
    const settingsStartingBudget = document.getElementById("settings-starting-budget");
    const settingsCashReserve = document.getElementById("settings-cash-reserve");
    const settingsEquityStash = document.getElementById("settings-equity-stash");
    const settingsCryptoStash = document.getElementById("settings-crypto-stash");
    const transferFromWallet = document.getElementById("transfer-from-wallet");
    const transferToWallet = document.getElementById("transfer-to-wallet");
    const transferAmount = document.getElementById("transfer-amount");
    const nightWatchBadge = document.getElementById("nightwatch-badge");
    const nightWatchStatus = document.getElementById("nightwatch-status");
    const nightWatchCycles = document.getElementById("nightwatch-cycles");
    const nightWatchTrades = document.getElementById("nightwatch-trades");
    const nightWatchWarnings = document.getElementById("nightwatch-warnings");
    const nightWatchSummary = document.getElementById("nightwatch-summary");
    const nightWatchEvents = document.getElementById("nightwatch-events");
    const fullReloadButton = document.getElementById("full-reload-button");
    const startBotButton = document.getElementById("start-bot-button");
    const startRunNowButton = document.getElementById("start-run-now-button");
    const saveDurationButton = document.getElementById("save-duration-button");
    const durationMinutesInput = document.getElementById("duration-minutes-input");
    let durationMinutesDirty = false;
    const costBasisNode = document.getElementById("stat-cost-basis");
    const statPendingOrdersNode = document.getElementById("stat-pending-orders");
    const statOrderStatusNode = document.getElementById("stat-order-status");
    const marketStripNode = document.getElementById("market-strip");
    const viewToggleGroup = document.getElementById("view-toggle-group");
    const viewNoteNode = document.getElementById("view-note");
    const pendingOrderValueNode = document.getElementById("pending-order-value");
    const pendingOrderCountLabel = document.getElementById("pending-order-count-label");
    const pendingOrderHint = document.getElementById("pending-order-hint");
    const pendingOrderList = document.getElementById("pending-order-list");
    const marketWatchList = document.getElementById("market-watch-list");
    const tradeOrderList = document.getElementById("trade-order-list");
    const operatorApiBase = window.location.protocol === "file:"
      ? `http://127.0.0.1:${{window.location.port || "8765"}}`
      : "";
    let lastHeartbeatAt = 0;
    const autoVisualRefresh = true;
    let aiTradingEnabled = true;
    let operatorNotice = null;
    let currentViewFilter = "all";
    let lastTransactionLogSignature = null;
    let currentInvestmentPlan = null;
    let currentSessionReport = null;
    let currentRuntimeState = {{
      status: "idle",
      session_active: false,
      cycle_running: false,
      current_cycle: 0,
      completed_cycles: 0,
      next_cycle_at: null,
      recent_logs: [],
      session_end_at: null,
    }};
    let currentRuntimeMeta = {{
      session_lock_owner_pid: null,
      operator_server_lock_owner_pid: null,
      operator_server_pid: null,
    }};
    let dashboardRefreshTimer = null;
    let liveStatusResetTimer = null;

    function apiUrl(path) {{
      return `${{operatorApiBase}}${{path}}`;
    }}

    function timestampMillis(value) {{
      if (!value) return 0;
      const parsed = Date.parse(String(value));
      return Number.isFinite(parsed) ? parsed : 0;
    }}

    function latestTransactionMillis(runtimeLogs) {{
      return (runtimeLogs || [])
        .filter((entry) => String(entry.kind || "") === "transaction")
        .map((entry) => timestampMillis(entry.created_at))
        .reduce((latest, current) => Math.max(latest, current), 0);
    }}

    function snapshotIsStaleForRuntime() {{
      const snapshotTime = timestampMillis(currentSnapshot.generated_at);
      if (!snapshotTime) return true;
      const lastCycleFinished = timestampMillis(currentRuntimeState.last_cycle_finished_at);
      const lastTransaction = latestTransactionMillis(currentRuntimeState.recent_logs || []);
      return snapshotTime < Math.max(lastCycleFinished, lastTransaction);
    }}

    function snapshotSignature(snapshot) {{
      return JSON.stringify({{
        equity: Number(snapshot.total_equity || 0).toFixed(2),
        cash: Number(snapshot.cash || 0).toFixed(2),
        invested: Number(snapshot.invested_value || 0).toFixed(2),
        pendingValue: Number(snapshot.pending_open_order_value || 0).toFixed(2),
        openOrdersCount: Number(snapshot.open_orders_count || 0),
        openOrderSummary: String(snapshot.open_order_status_summary || ""),
        recommendations: (snapshot.recommendations || []).map((item) => [
          item.symbol,
          item.recommendation,
          item.signal_action,
          item.risk_level,
          Number(item.current_price || 0).toFixed(2),
        ]),
        openOrderDetails: (snapshot.open_order_details || []).map((item) => [
          item.symbol,
          item.side,
          item.status,
          Number(item.notional_value || 0).toFixed(2),
        ]),
        recentOrders: (snapshot.recent_order_activity || []).slice(0, 5).map((item) => [
          item.symbol,
          item.side,
          item.status,
          item.submitted_at,
          item.amount_label,
          item.price_label,
        ]),
        alerts: (snapshot.alerts || []).map((alert) => [alert.event_type, alert.message]),
      }});
    }}

    let lastRenderedSnapshotSignature = snapshotSignature(currentSnapshot);

    function playUpdateTone() {{
      try {{
        const context = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = context.createOscillator();
        const gainNode = context.createGain();
        oscillator.type = "triangle";
        oscillator.frequency.value = 880;
        gainNode.gain.setValueAtTime(0.0001, context.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.05, context.currentTime + 0.02);
        gainNode.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.25);
        oscillator.connect(gainNode);
        gainNode.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.28);
      }} catch (error) {{
        // Browser blocked audio until user interaction; that's okay.
      }}
    }}

    function playTransactionTone() {{
      try {{
        const context = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = context.createOscillator();
        const gainNode = context.createGain();
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(622.25, context.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(783.99, context.currentTime + 0.12);
        gainNode.gain.setValueAtTime(0.0001, context.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.055, context.currentTime + 0.02);
        gainNode.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.32);
        oscillator.connect(gainNode);
        gainNode.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.34);
      }} catch (error) {{
        // Browser blocked audio until user interaction; that's okay.
      }}
    }}

    async function sendHeartbeat() {{
      const now = Date.now();
      if (now - lastHeartbeatAt < 10000) {{
        return;
      }}
      lastHeartbeatAt = now;
      try {{
        await fetch(apiUrl("/api/window-heartbeat"), {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ visible: document.visibilityState }}),
        }});
      }} catch (error) {{
        // If the server is temporarily unavailable, the next loop will try again.
      }}
    }}

    async function loadOverrides() {{
      try {{
        const response = await fetch(apiUrl("/api/overrides"));
        if (!response.ok) throw new Error("override fetch failed");
        const payload = await response.json();
        aiTradingEnabled = payload.ai_trading_enabled !== false;
        currentRuntimeMeta = {{
          session_lock_owner_pid: payload.session_lock_owner_pid ?? null,
          operator_server_lock_owner_pid: payload.operator_server_lock_owner_pid ?? null,
          operator_server_pid: payload.operator_server_pid ?? null,
        }};
        renderAiTradingState();
        renderProcessStatus();
        return payload.overrides || {{}};
      }} catch (error) {{
        if (liveStatus) {{
          liveStatus.textContent = "Override sync unavailable right now.";
        }}
        return {{}};
      }}
    }}

    function renderAiTradingState() {{
      if (!aiMasterToggle || !aiMasterLabel) return;
      aiMasterToggle.classList.toggle("on", aiTradingEnabled);
      aiMasterToggle.classList.toggle("off", !aiTradingEnabled);
      aiMasterLabel.textContent = aiTradingEnabled ? "ON" : "OFF";
    }}

    async function renderOverrides() {{
      const overrides = await loadOverrides();
      for (const rec of currentSnapshot.recommendations) {{
        const note = document.getElementById(`override-${{rec.symbol}}`);
        if (!note) continue;
        const current = overrides[rec.symbol];
        note.textContent = current
          ? `Manual override: ${{current.action.toUpperCase()}} at ${{current.updated_at}}`
          : "No manual override yet.";
      }}
    }}

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function formatMoney(value) {{
      return `$${{new Intl.NumberFormat("de-DE", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}).format(Number(value || 0))}}`;
    }}

    function formatPercent(value) {{
      return `${{new Intl.NumberFormat("de-DE", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}).format(Number(value || 0))}}%`;
    }}

    function formatCompactTime(value) {{
      if (!value) return "--.--";
      const parsed = new Date(String(value));
      if (Number.isNaN(parsed.getTime())) return "--.--";
      return new Intl.DateTimeFormat("de-CH", {{
        timeZone: "Europe/Zurich",
        hour: "2-digit",
        minute: "2-digit",
      }}).format(parsed).replace(":", ".");
    }}

    function formatPlainNumber(value) {{
      return new Intl.NumberFormat("de-DE", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}).format(Number(value || 0));
    }}

    function parseLocaleNumber(value) {{
      const raw = String(value ?? "").trim().replace(/\\s+/g, "").replace(/'/g, "");
      if (!raw) return 0;
      const lastComma = raw.lastIndexOf(",");
      const lastDot = raw.lastIndexOf(".");
      if (lastComma !== -1 && lastDot !== -1) {{
        if (lastComma > lastDot) {{
          return Number(raw.replaceAll(".", "").replace(",", "."));
        }}
        return Number(raw.replaceAll(",", ""));
      }}
      if (lastComma !== -1) {{
        return Number(raw.replace(",", "."));
      }}
      return Number(raw);
    }}

    function parseDurationMinutes(value) {{
      const parsed = Math.round(parseLocaleNumber(value));
      if (!Number.isFinite(parsed) || parsed < 1) {{
        return null;
      }}
      return parsed;
    }}

    function renderMarketStrip(snapshot) {{
      if (!marketStripNode) return;
      const recommendations = snapshot.recommendations || [];
      const cryptoCount = recommendations.filter((item) => item.asset_class === "crypto").length;
      const equityCount = recommendations.length - cryptoCount;
      marketStripNode.innerHTML = `
        <span class="market-pill">Tracking ${{recommendations.length}} assets</span>
        <span class="market-pill equity">Equities ${{equityCount}}</span>
        <span class="market-pill crypto">Crypto ${{cryptoCount}}</span>
      `;
    }}

    function openInvestmentPlanModal() {{
      if (!investmentPlanModal) return;
      investmentPlanModal.classList.add("open");
    }}

    function closeInvestmentPlanModal() {{
      if (!investmentPlanModal) return;
      investmentPlanModal.classList.remove("open");
    }}

    function renderInvestmentPlan(payload) {{
      currentInvestmentPlan = payload;
      if (!payload) return;
      const plan = payload.plan || {{}};
      const wallets = payload.wallets || {{}};
      if (settingsStartingBudget) settingsStartingBudget.value = formatPlainNumber(plan.starting_budget || 0);
      if (settingsCashReserve) settingsCashReserve.value = formatPlainNumber(plan.cash_reserve_percent || 0);
      if (settingsEquityStash) settingsEquityStash.value = formatPlainNumber(plan.equity_allocation_percent || 0);
      if (settingsCryptoStash) settingsCryptoStash.value = formatPlainNumber(plan.crypto_allocation_percent || 0);
        if (investmentWalletGrid) {{
          investmentWalletGrid.innerHTML = `
            <div class="wallet-card">
              <span>Bot Cash Buffer</span>
              <strong>${{formatMoney(wallets.cash_wallet_usd || 0)}}</strong>
              <div class="wallet-meta">
                <div>Broker cash<b>${{formatMoney(wallets.broker_cash_usd || 0)}}</b></div>
                <div>Moveable<b>${{formatMoney(wallets.cash_available_to_move_usd || 0)}}</b></div>
              </div>
          </div>
          <div class="wallet-card">
            <span>Equity Stash</span>
            <strong>${{formatMoney(wallets.equity_wallet_usd || 0)}}</strong>
            <div class="wallet-meta">
              <div>Committed<b>${{formatMoney(wallets.equity_committed_usd || 0)}}</b></div>
              <div>Free<b>${{formatMoney(wallets.equity_available_usd || 0)}}</b></div>
              <div>Filled<b>${{formatMoney(wallets.equity_invested_usd || 0)}}</b></div>
              <div>Pending<b>${{formatMoney(wallets.equity_pending_usd || 0)}}</b></div>
            </div>
          </div>
          <div class="wallet-card">
            <span>Crypto Stash</span>
            <strong>${{formatMoney(wallets.crypto_wallet_usd || 0)}}</strong>
            <div class="wallet-meta">
              <div>Committed<b>${{formatMoney(wallets.crypto_committed_usd || 0)}}</b></div>
              <div>Free<b>${{formatMoney(wallets.crypto_available_usd || 0)}}</b></div>
              <div>Filled<b>${{formatMoney(wallets.crypto_invested_usd || 0)}}</b></div>
              <div>Pending<b>${{formatMoney(wallets.crypto_pending_usd || 0)}}</b></div>
            </div>
          </div>
        `;
      }}
      if (investmentPlanNote) {{
        investmentPlanNote.textContent = `Broker cash ${{formatMoney(wallets.broker_cash_usd || 0)}} | bot planning budget ${{formatMoney(plan.starting_budget || 0)}} | bot cash reserve ${{formatPercent(plan.cash_reserve_percent || 0)}} | equity stash ${{formatPercent(plan.equity_allocation_percent || 0)}} | crypto stash ${{formatPercent(plan.crypto_allocation_percent || 0)}}.`;
      }}
    }}

    async function loadInvestmentPlan() {{
      try {{
        const response = await fetch(apiUrl("/api/investment-plan"), {{ cache: "no-store" }});
        if (!response.ok) throw new Error("investment plan fetch failed");
        const payload = await response.json();
        renderInvestmentPlan(payload);
      }} catch (error) {{
        if (investmentPlanNote) {{
          investmentPlanNote.textContent = "Investment plan sync is unavailable right now.";
        }}
      }}
    }}

    function applyAssetViewFilter() {{
      const cards = Array.from(document.querySelectorAll(".asset-card"));
      let visibleCount = 0;
      for (const card of cards) {{
        const assetClass = String(card.dataset.assetClass || "us_equity");
        const shouldShow = currentViewFilter === "all" || assetClass === currentViewFilter;
        card.style.display = shouldShow ? "" : "none";
        if (shouldShow) visibleCount += 1;
      }}
      if (viewNoteNode) {{
        if (currentViewFilter === "crypto") {{
          viewNoteNode.textContent = `Showing the crypto desk only (${{visibleCount}} card(s)).`;
        }} else if (currentViewFilter === "us_equity") {{
          viewNoteNode.textContent = `Showing the equities desk only (${{visibleCount}} card(s)).`;
        }} else {{
          viewNoteNode.textContent = `Showing the combined market desk (${{visibleCount}} card(s)).`;
        }}
      }}
      if (viewToggleGroup) {{
        for (const button of viewToggleGroup.querySelectorAll("[data-view]")) {{
          button.classList.toggle("active", button.getAttribute("data-view") === currentViewFilter);
        }}
      }}
    }}

    function formatDisplayDate(value) {{
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {{
        return String(value ?? "");
      }}
      const pad = (part) => String(part).padStart(2, "0");
      return `${{pad(date.getDate())}}.${{pad(date.getMonth() + 1)}}.${{date.getFullYear()}} - ${{pad(date.getHours())}}:${{pad(date.getMinutes())}}:${{pad(date.getSeconds())}}`;
    }}

      function formatCountdownFromTimestamp(value) {{
        if (!value) return "n/a";
        const target = new Date(value);
        if (Number.isNaN(target.getTime())) return "n/a";
      const diff = Math.max(0, target.getTime() - Date.now());
      const totalSeconds = Math.floor(diff / 1000);
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      if (hours > 0) {{
        return `${{hours}}h ${{String(minutes).padStart(2, "0")}}m ${{String(seconds).padStart(2, "0")}}s`;
        }}
        return `${{minutes}}m ${{String(seconds).padStart(2, "0")}}s`;
      }}

      function hasLiveCryptoTrigger() {{
        return Boolean(
          currentRuntimeState &&
          String(currentRuntimeState.crypto_stream_status || "").toLowerCase() === "live" &&
          String(currentRuntimeState.crypto_stream_message || "").trim()
        );
      }}

      function setDeskStatus(prefix, badgeClass, badgeText, title, message) {{
        const badge = document.getElementById(`${{prefix}}-bot-badge`);
        const titleNode = document.getElementById(`${{prefix}}-bot-title`);
        const messageNode = document.getElementById(`${{prefix}}-bot-message`);
        if (badge) {{
          badge.className = `mini-badge ${{badgeClass}}`;
          badge.textContent = badgeText;
        }}
        if (titleNode) titleNode.textContent = title;
        if (messageNode) messageNode.textContent = message;
      }}

    function movementForSymbol(symbol, snapshot) {{
      const chart = (snapshot.asset_charts || []).find((item) => item.symbol === symbol);
      if (!chart || !chart.points || chart.points.length < 2) {{
        return {{ value: 0, percent: 0 }};
      }}
      const previous = Number(chart.points[chart.points.length - 2].value || 0);
      const current = Number(chart.points[chart.points.length - 1].value || 0);
      const change = current - previous;
      return {{
        value: change,
        percent: previous === 0 ? 0 : (change / previous) * 100,
      }};
    }}

    function zonesForItem(item) {{
      if (item.suggested_buy_price > 0 || item.suggested_sell_price > 0) {{
        return {{
          buy: item.suggested_buy_price || item.current_price * 0.98,
          sell: item.suggested_sell_price || item.current_price * 1.02,
        }};
      }}
      return {{
        buy: item.current_price * 0.98,
        sell: item.current_price * 1.02,
      }};
    }}

    function sparklineSvg(points, markers, stroke = "#145a8d") {{
      const width = 720;
      const height = 160;
      const margin = 14;
      if (!points || points.length === 0) {{
        return `<svg viewBox="0 0 ${{width}} ${{height}}" role="img"><text x="24" y="80" fill="#91a6b7">No chart data yet.</text></svg>`;
      }}

      const values = points.map((point) => Number(point.value || 0));
      const minValue = Math.min(...values);
      const maxValue = Math.max(...values);
      const valueRange = Math.max(maxValue - minValue, 1e-9);
      const step = (width - margin * 2) / Math.max(points.length - 1, 1);
      const coords = points.map((point, index) => {{
        const x = margin + index * step;
        const normalized = (Number(point.value || 0) - minValue) / valueRange;
        const y = height - margin - normalized * (height - margin * 2);
        return {{ x, y, timestamp: point.timestamp }};
      }});
      const polyline = coords.map((coord) => `${{coord.x.toFixed(1)}},${{coord.y.toFixed(1)}}`).join(" ");
      const markerIndex = new Map(coords.map((coord, index) => [coord.timestamp, index]));
      const markerNodes = (markers || []).map((marker) => {{
        const idx = markerIndex.get(marker.timestamp);
        if (idx === undefined) {{
          return "";
        }}
        const coord = coords[idx];
        const color = String(marker.side || "").toLowerCase() === "buy" ? "#2f7d4c" : "#b33a3a";
        return `<circle cx="${{coord.x.toFixed(1)}}" cy="${{coord.y.toFixed(1)}}" r="5" fill="${{color}}" stroke="white" stroke-width="2"><title>${{escapeHtml(String(marker.side || "").toUpperCase())}} ${{escapeHtml(marker.symbol)}} @ ${{formatMoney(marker.price)}} - ${{escapeHtml(marker.note)}}</title></circle>`;
      }}).join("");
      return `<svg viewBox="0 0 ${{width}} ${{height}}" role="img"><polyline fill="none" stroke="${{stroke}}" stroke-width="3" points="${{polyline}}" />${{markerNodes}}</svg>`;
    }}

    function runtimeLogClass(kind) {{
      if (kind === "user-stop") return "user-stop";
      if (kind === "user-start") return "user-start";
      if (kind === "warning") return "warning";
      return "system";
    }}

    function runtimeLogIcon(kind) {{
      if (kind === "user-stop") return "■";
      if (kind === "user-start") return "✓";
      if (kind === "warning") return "!";
      return "•";
    }}

    function renderAlertList(alerts, runtimeLogs = []) {{
      const target = document.getElementById("alerts-list");
      if (!target) return;
      const localNotice = operatorNotice
        ? `<li class="alert-item ${{escapeHtml(operatorNotice.kind)}}"><span class="alert-icon">${{escapeHtml(operatorNotice.icon)}}</span><div><strong>${{escapeHtml(operatorNotice.title)}}</strong><div>${{escapeHtml(operatorNotice.message)}}</div></div></li>`
        : "";
      const runtimeItems = (runtimeLogs || []).length
        ? runtimeLogs
            .slice()
            .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))
            .slice(0, 6)
            .map((entry) => `<li class="alert-item ${{runtimeLogClass(entry.kind)}}"><span class="alert-icon">${{runtimeLogIcon(entry.kind)}}</span><div><strong>${{escapeHtml(entry.title)}}</strong><div>${{escapeHtml(entry.message)}}</div></div></li>`)
            .join("")
        : "";
      const systemItems = (alerts || []).length
        ? alerts.map((alert) => `<li class="alert-item system"><span class="alert-icon">•</span><div><strong>${{escapeHtml(alert.event_type)}}</strong> ${{escapeHtml(alert.message)}}</div></li>`).join("")
        : "";
      const items = localNotice || runtimeItems || systemItems
        ? `${{localNotice}}${{runtimeItems}}${{systemItems}}`
        : "<li>No active warnings right now.</li>";
      target.innerHTML = items;
    }}

    function syncTransactionNotification(runtimeLogs, playSound = false) {{
      const latestTransaction = (runtimeLogs || [])
        .filter((entry) => String(entry.kind || "") === "transaction")
        .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))[0];
      const nextSignature = latestTransaction
        ? `${{String(latestTransaction.created_at || "")}}|${{String(latestTransaction.title || "")}}|${{String(latestTransaction.message || "")}}`
        : null;
      if (lastTransactionLogSignature === null) {{
        lastTransactionLogSignature = nextSignature;
        return;
      }}
      if (playSound && nextSignature && nextSignature !== lastTransactionLogSignature) {{
        playTransactionTone();
      }}
      lastTransactionLogSignature = nextSignature;
    }}

    function renderPendingOpenOrders(snapshot) {{
      if (costBasisNode) {{
        costBasisNode.textContent = formatMoney(snapshot.filled_position_cost_basis || 0);
      }}
      if (statPendingOrdersNode) {{
        statPendingOrdersNode.textContent = formatMoney(snapshot.pending_open_order_value || 0);
      }}
      if (statOrderStatusNode) {{
        statOrderStatusNode.textContent = String(snapshot.open_order_status_summary || "No open orders");
      }}
      if (pendingOrderValueNode) {{
        pendingOrderValueNode.textContent = formatMoney(snapshot.pending_open_order_value || 0);
      }}
      if (pendingOrderCountLabel) {{
        pendingOrderCountLabel.textContent = String(snapshot.open_order_status_summary || "No open orders");
      }}
      if (pendingOrderHint) {{
        pendingOrderHint.textContent = String(snapshot.open_order_fill_hint || "No pending fills.");
      }}
      if (!pendingOrderList) return;
      const details = snapshot.open_order_details || [];
      if (!details.length) {{
        pendingOrderList.innerHTML = '<div class="pending-order-empty">No pending open orders right now.</div>';
        return;
      }}
        pendingOrderList.innerHTML = details
          .slice(0, 6)
          .map((detail) => `
            <div class="pending-order-row">
              <span>${{escapeHtml(detail.symbol)}} ${{escapeHtml(String(detail.side || "").toUpperCase())}}</span>
            <strong>${{formatMoney(detail.notional_value || 0)}}</strong>
            <small>${{escapeHtml(String(detail.status || "").toUpperCase())}}</small>
          </div>
          `)
          .join("");
    }}

    function renderMarketWatch(snapshot) {{
      if (!marketWatchList) return;
      const recommendations = Array.isArray(snapshot.recommendations) ? snapshot.recommendations.slice() : [];
      const pendingSymbols = new Set((snapshot.open_order_details || []).map((item) => String(item.symbol || "")));
      if (!recommendations.length) {{
        marketWatchList.innerHTML = '<div class="market-watch-empty">No active symbols in the watchlist right now.</div>';
        return;
      }}
      const rows = recommendations
        .map((item) => {{
          const movement = movementForSymbol(item.symbol, snapshot);
          const assetClass = String(item.asset_class || "").replaceAll("_", " ").toUpperCase();
          const recommendation = String(item.recommendation || "").toUpperCase();
          const rationale = String(item.rationale || "").trim();
          const hasPendingOrder = pendingSymbols.has(String(item.symbol || ""));
          let tone = "watch";
          let badge = "WATCH";
          let message = rationale || "Monitoring current setup.";

          if (hasPendingOrder) {{
            tone = "pending";
            badge = "PENDING";
            message = "Broker order is queued; waiting for execution.";
          }} else if (["EXIT_NOW", "SELL", "SELL_OR_HEDGE", "REDUCE"].includes(recommendation) || String(item.risk_level || "").toLowerCase() === "critical") {{
            tone = "risk";
            badge = "RISK";
            message = rationale || "Risk conditions are elevated.";
          }} else if (["BUY", "BUY_CANDIDATE", "MANUAL_BUY"].includes(recommendation) || String(item.signal_action || "").toUpperCase() === "BUY") {{
            tone = "opportunity";
            badge = "OPPORTUNITY";
            message = rationale || "Momentum and setup look constructive.";
          }} else if (String(item.asset_class || "") === "crypto" && hasLiveCryptoTrigger()) {{
            tone = "opportunity";
            badge = "LIVE";
            message = String(currentRuntimeState.crypto_stream_message || "Crypto stream is armed for live triggers.");
          }}

          const moveLabel = movement.percent === 0
            ? assetClass
            : `${{movement.percent >= 0 ? "+" : ""}}${{movement.percent.toFixed(2)}}% · ${{assetClass}}`;

          return {{
            tone,
            badge,
            symbol: String(item.symbol || ""),
            moveLabel,
            message,
            priority: tone === "risk" ? 0 : tone === "opportunity" ? 1 : tone === "pending" ? 2 : 3,
          }};
        }})
        .sort((left, right) => left.priority - right.priority || left.symbol.localeCompare(right.symbol))
        .slice(0, 6);

      marketWatchList.innerHTML = rows
        .map((row) => `
          <div class="market-watch-row ${{row.tone}}">
            <span class="market-watch-dot"></span>
            <div class="market-watch-copy">
              <strong>${{escapeHtml(row.symbol)}} - ${{escapeHtml(row.moveLabel)}}</strong>
              <small>${{escapeHtml(row.message)}}</small>
            </div>
            <span class="market-watch-badge">${{escapeHtml(row.badge)}}</span>
          </div>
        `)
        .join("");
    }}

    function recentOrderStatusClass(status) {{
      const normalized = String(status || "").trim().toLowerCase();
      if (["filled", "done_for_day", "completed"].includes(normalized)) return "filled";
      if (["accepted", "new", "pending_new", "pending_replace", "held"].includes(normalized)) return "pending";
      if (["partially_filled", "pending_cancel", "pending_review"].includes(normalized)) return "partial";
      if (["canceled", "cancelled", "rejected", "expired", "stopped", "suspended"].includes(normalized)) return "failed";
      return "pending";
    }}

    function recentOrderStatusLabel(status) {{
      const normalized = String(status || "").trim().toLowerCase();
      if (["filled", "done_for_day", "completed"].includes(normalized)) return "FULFILLED";
      if (["partially_filled", "pending_cancel", "pending_review"].includes(normalized)) return "PARTIAL";
      if (["canceled", "cancelled", "rejected", "expired", "stopped", "suspended"].includes(normalized)) return "FAILED";
      return "PENDING";
    }}
    function renderRecentOrderActivity(snapshot) {{
      if (!tradeOrderList) return;
      const details = Array.isArray(snapshot.recent_order_activity) ? snapshot.recent_order_activity.slice(0, 5) : [];
      if (!details.length) {{
        tradeOrderList.innerHTML = '<div class="trade-order-empty">No recent trade orders yet.</div>';
        return;
      }}
      tradeOrderList.innerHTML = details
        .map((detail) => {{
          const badgeClass = recentOrderStatusClass(detail.status);
          const side = String(detail.side || "").toUpperCase();
          const symbol = String(detail.symbol || "");
          const amount = String(detail.amount_label || "n/a");
          const price = String(detail.price_label || "").trim();
          const timeLabel = formatCompactTime(detail.submitted_at);
          const summary = price ? `${{timeLabel}} · ${{amount}} - ${{price}}` : `${{timeLabel}} · ${{amount}}`;
          return `
            <div class="trade-order-row ${{badgeClass}}">
              <span class="trade-order-dot"></span>
              <div class="trade-order-copy">
                <strong>${{escapeHtml(side)}} ${{escapeHtml(symbol)}}</strong>
                <small>${{escapeHtml(summary)}}</small>
              </div>
              <span class="trade-order-pill ${{badgeClass}}">${{escapeHtml(recentOrderStatusLabel(detail.status))}}</span>
            </div>
          `;
        }})
        .join("");
    }}

      function renderProcessStatus() {{
        const botPidNode = document.getElementById("bot-pid");
        const sessionLockPidNode = document.getElementById("session-lock-pid");
        const serverPidNode = document.getElementById("server-pid");
        const serverLockPidNode = document.getElementById("server-lock-pid");
        if (!botPidNode || !sessionLockPidNode || !serverPidNode || !serverLockPidNode) return;
        botPidNode.textContent = currentRuntimeState.bot_pid ? `PID ${{String(currentRuntimeState.bot_pid)}}` : "n/a";
        sessionLockPidNode.textContent = currentRuntimeMeta.session_lock_owner_pid ? `PID ${{String(currentRuntimeMeta.session_lock_owner_pid)}}` : "n/a";
        serverPidNode.textContent = currentRuntimeMeta.operator_server_pid ? `PID ${{String(currentRuntimeMeta.operator_server_pid)}}` : "n/a";
        serverLockPidNode.textContent = currentRuntimeMeta.operator_server_lock_owner_pid ? `PID ${{String(currentRuntimeMeta.operator_server_lock_owner_pid)}}` : "n/a";
      }}

    function renderLiveActivity() {{
      const titleNode = document.getElementById("live-activity-title");
      const messageNode = document.getElementById("live-activity-message");
      if (!titleNode || !messageNode) return;
        const logs = Array.isArray(currentRuntimeState.recent_logs) ? currentRuntimeState.recent_logs.slice() : [];
        const latest = logs.sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))[0];
        if (!latest) {{
          titleNode.textContent = "Waiting for activity...";
          messageNode.textContent = "The bot will surface its freshest action here during the run.";
          return;
        }}
        const createdAt = latest.created_at ? formatDisplayDate(latest.created_at) : "just now";
      titleNode.textContent = String(latest.title || "Recent bot action");
      messageNode.textContent = `${{String(latest.message || "No details yet.")}} (${{createdAt}})`;
    }}

    function renderNightWatch() {{
      if (!nightWatchBadge || !nightWatchStatus || !nightWatchCycles || !nightWatchTrades || !nightWatchWarnings || !nightWatchSummary || !nightWatchEvents) return;
      const runtimeStatus = String(currentRuntimeState.status || "idle").toLowerCase();
      const report = currentSessionReport || null;
      const warningCount = Number(report?.warning_count || 0);
      const tradeCount = Number(report?.trade_count || 0);
      const blockedCount = Number(report?.blocked_count || 0);
      const cycleCount = Number(currentRuntimeState.completed_cycles || report?.completed_cycles || 0);

      let badgeClass = "idle";
      let badgeText = "Idle";
      let statusText = "Idle";
      if (runtimeStatus === "running") {{
        badgeClass = "active";
        badgeText = "Running";
        statusText = "Live session running";
      }} else if (runtimeStatus === "waiting" || runtimeStatus === "starting") {{
        badgeClass = "active";
        badgeText = "Watching";
        statusText = "Live session between cycles";
      }} else if (warningCount > 0 || blockedCount > 0) {{
        badgeClass = "alert";
        badgeText = "Alert";
        statusText = "Recent session needs attention";
      }}

      nightWatchBadge.className = `nightwatch-badge ${{badgeClass}}`;
      nightWatchBadge.textContent = badgeText;
      nightWatchStatus.textContent = statusText;
      nightWatchCycles.textContent = String(cycleCount);
      nightWatchTrades.textContent = String(tradeCount);
      nightWatchWarnings.textContent = String(warningCount);

      if (runtimeStatus === "running" || runtimeStatus === "waiting" || runtimeStatus === "starting") {{
        const nextScheduled = currentRuntimeState.next_cycle_at
          ? formatCountdownFromTimestamp(currentRuntimeState.next_cycle_at)
          : "n/a";
        nightWatchSummary.textContent = `Live session is active. Next scheduled cycle in ${{nextScheduled}}. Latest stream state: ${{String(currentRuntimeState.crypto_stream_message || "No live stream message")}}.`;
      }} else if (report) {{
        const generated = report.generated_at ? formatDisplayDate(report.generated_at) : "unknown";
        nightWatchSummary.textContent = `Latest finished report from ${{generated}}: ${{tradeCount}} trade(s), ${{blockedCount}} blocked action(s), ${{warningCount}} warning(s), ${{Number(report.open_orders_count || 0)}} open order(s).`;
      }} else {{
        nightWatchSummary.textContent = "No finished session report yet. The current runtime state will appear here once the bot starts moving.";
      }}

      const items = [];
      if (report?.recent_alerts?.length) {{
        for (const item of report.recent_alerts.slice(-3).reverse()) {{
          items.push(`<div class="nightwatch-item"><strong>${{escapeHtml(item.event_type || "event")}}</strong><small>${{escapeHtml(item.message || "No details")}}</small></div>`);
        }}
      }} else {{
        const logs = Array.isArray(currentRuntimeState.recent_logs) ? currentRuntimeState.recent_logs.slice(0, 3) : [];
        for (const log of logs) {{
          items.push(`<div class="nightwatch-item"><strong>${{escapeHtml(log.title || "Runtime")}}</strong><small>${{escapeHtml(log.message || "No details")}}</small></div>`);
        }}
      }}
      nightWatchEvents.innerHTML = items.join("") || `<div class="nightwatch-item"><strong>Waiting for the first report...</strong><small>The operator window will summarize the latest session here instead of stuffing Codex with monitor chatter.</small></div>`;
    }}

      function renderRuntimeState() {{
        const liveStatusNode = document.getElementById("live-status");
        const badge = document.getElementById("runner-badge");
        const detail = document.getElementById("runtime-detail");
        if (!liveStatusNode || !badge || !detail) return;
      const streamSuffix = currentRuntimeState.crypto_stream_message
        ? ` | Crypto stream: ${{currentRuntimeState.crypto_stream_message}}`
        : "";
      const status = String(currentRuntimeState.status || "idle").toLowerCase();
      badge.className = "runner-badge";
      if (
        durationMinutesInput &&
        currentRuntimeState.desired_session_duration_minutes &&
        !durationMinutesDirty &&
        document.activeElement !== durationMinutesInput
      ) {{
        durationMinutesInput.value = String(currentRuntimeState.desired_session_duration_minutes);
      }}
      if (startBotButton) {{
        startBotButton.disabled = status === "running" || status === "starting";
        startBotButton.textContent = status === "running" ? "Bot Running" : "Start Bot";
      }}
        if (startRunNowButton) {{
          startRunNowButton.disabled = status === "running" || !currentRuntimeState.session_active;
        }}
        const sessionLeft = formatCountdownFromTimestamp(currentRuntimeState.session_end_at);
        const nextScheduled = formatCountdownFromTimestamp(currentRuntimeState.next_cycle_at);
        const completedCycles = Number(currentRuntimeState.completed_cycles || 0);
        if (status === "running") {{
          badge.classList.add("running");
          badge.textContent = "Running";
          liveStatusNode.textContent = `Cycle ${{
            Number(currentRuntimeState.current_cycle || 0)
          }} is running now.`;
          detail.textContent = `Session left: ${{sessionLeft}} | Completed cycles: ${{
            completedCycles
          }} | Poll interval: ${{
            Number(currentRuntimeState.poll_interval_seconds || 0)
          }}s${{streamSuffix}}`;
          setDeskStatus("master", "running", "Running", "Master session is active", `Cycle ${{
            Number(currentRuntimeState.current_cycle || 0)
          }} is executing right now.`);
          setDeskStatus("equities", "running", "Running", "Equities desk is active", `Equities follow the shared session clock. Session left: ${{sessionLeft}}.`);
          setDeskStatus("crypto", hasLiveCryptoTrigger() ? "triggered" : "running", hasLiveCryptoTrigger() ? "Triggered" : "Running", hasLiveCryptoTrigger() ? "Crypto desk is stream-awake" : "Crypto desk is active", hasLiveCryptoTrigger() ? `${{currentRuntimeState.crypto_stream_message}}` : `Crypto cycle is processing normally. Session left: ${{sessionLeft}}.`);
          return;
        }}
        if (status === "waiting" || status === "starting" || status === "idle") {{
          badge.classList.add("waiting");
          badge.textContent = status === "starting" ? "Starting" : "Waiting";
          const scheduledText = currentRuntimeState.next_cycle_at
            ? `Next scheduled cycle at ${{formatDisplayDate(currentRuntimeState.next_cycle_at)}}.`
            : "Session is waiting for the next cycle.";
          liveStatusNode.textContent = hasLiveCryptoTrigger()
            ? `${{scheduledText}} Live crypto trigger may start a run earlier.`
            : scheduledText;
          detail.textContent = `Session left: ${{sessionLeft}} | Next scheduled cycle in: ${{nextScheduled}} | Completed cycles: ${{
            completedCycles
          }}${{streamSuffix}}`;
          setDeskStatus("master", "waiting", status === "starting" ? "Starting" : "Waiting", "Master session is between cycles", `Session left ${{sessionLeft}}. Next scheduled cycle in ${{nextScheduled}}.`);
          setDeskStatus("equities", "waiting", "Scheduled", "Equities desk follows the timer", `Next scheduled equities cycle in ${{nextScheduled}}.`);
          setDeskStatus("crypto", hasLiveCryptoTrigger() ? "triggered" : "waiting", hasLiveCryptoTrigger() ? "Live trigger" : "Scheduled", hasLiveCryptoTrigger() ? "Crypto desk can jump early" : "Crypto desk is waiting", hasLiveCryptoTrigger() ? `${{currentRuntimeState.crypto_stream_message}}. Scheduled cycle in ${{nextScheduled}}.` : `Next scheduled crypto cycle in ${{nextScheduled}}.`);
          return;
        }}
        if (status === "blocked_off") {{
          badge.classList.add("blocked");
          badge.textContent = "Stopped";
          liveStatusNode.textContent = "Next cycle is blocked because AI Trading is OFF.";
          detail.textContent = `Session left: ${{sessionLeft}} | Blocked next cycle at: ${{
            currentRuntimeState.next_cycle_at ? formatDisplayDate(currentRuntimeState.next_cycle_at) : "n/a"
          }}${{streamSuffix}}`;
          setDeskStatus("master", "blocked", "Stopped", "Master session is blocked", "AI Trading is OFF, so the next cycle cannot start.");
          setDeskStatus("equities", "blocked", "Stopped", "Equities desk is paused", "Equity reviews are blocked until AI Trading is turned back on.");
          setDeskStatus("crypto", "blocked", "Stopped", "Crypto desk is paused", "Crypto may stream live, but execution is blocked while AI Trading is OFF.");
          return;
        }}
        badge.classList.add("finished");
        badge.textContent = "Finished";
        liveStatusNode.textContent = currentRuntimeState.session_end_at
          ? `Session finished. Planned end was ${{formatDisplayDate(currentRuntimeState.session_end_at)}}.`
          : "Session finished.";
        detail.textContent = `Completed cycles: ${{
          completedCycles
        }} | Desired runtime: ${{
          Number(currentRuntimeState.desired_session_duration_minutes || 0)
        }} minute(s).${{streamSuffix}}`;
        setDeskStatus("master", "blocked", "Finished", "Master session is finished", `Completed cycles: ${{completedCycles}}.`);
        setDeskStatus("equities", "waiting", "Idle", "Equities desk is idle", "Start a new session to schedule fresh equity reviews.");
        setDeskStatus("crypto", "waiting", "Idle", "Crypto desk is idle", hasLiveCryptoTrigger() ? `${{currentRuntimeState.crypto_stream_message}}` : "Start a new session to re-arm live crypto triggers.");
      }}

    function renderAssetCards(snapshot) {{
      const target = document.getElementById("asset-grid");
      if (!target) return;
      const cards = (snapshot.recommendations || []).map((item) => {{
        const chart = (snapshot.asset_charts || []).find((asset) => asset.symbol === item.symbol);
        const movement = movementForSymbol(item.symbol, snapshot);
        const zones = zonesForItem(item);
        const movementClass = movement.value > 0 ? "up" : movement.value < 0 ? "down" : "flat";
        return `<section class="asset-card" data-asset-class="${{escapeHtml(item.asset_class)}}">
          <div class="asset-top"><div><div class="asset-label-row"><h2>${{escapeHtml(item.symbol)}}</h2><span class="asset-pill ${{escapeHtml(item.asset_class)}}">${{escapeHtml(String(item.asset_class || "").replaceAll("_", " ").toUpperCase())}}</span></div><div class="price">${{formatMoney(item.current_price)}}</div></div>
          <div class="move ${{movementClass}}">${{movement.value >= 0 ? "+" : ""}}${{movement.value.toFixed(2)}} / ${{movement.percent >= 0 ? "+" : ""}}${{movement.percent.toFixed(2)}}% since last update</div></div>
          <div class="chart-wrap">${{sparklineSvg(chart?.points || [], chart?.markers || [])}}</div>
          <div class="zones">
            <div><span>Suggested Buy Zone</span><strong>${{formatMoney(zones.buy)}}</strong></div>
            <div><span>Suggested Sell Zone</span><strong>${{formatMoney(zones.sell)}}</strong></div>
          </div>
          <div class="meta-grid">
            <div><span>AI Recommendation</span><strong>${{escapeHtml(item.recommendation)}}</strong></div>
            <div><span>Risk</span><strong class="risk ${{escapeHtml(item.risk_level)}}">${{escapeHtml(String(item.risk_level || "").toUpperCase())}}</strong></div>
            <div><span>Invested</span><strong>${{formatMoney(item.market_value)}}</strong></div>
            <div><span>Unrealized P/L</span><strong>${{formatMoney(item.unrealized_pl)}} (${{formatPercent(item.unrealized_pl_percent)}})</strong></div>
          </div>
          <div class="meta-grid">
            <div><span>Setup</span><strong>${{escapeHtml(item.strategy_setup)}}</strong></div>
            <div><span>Signal</span><strong>${{escapeHtml(item.signal_action)}} (${{Number(item.signal_confidence || 0).toFixed(2)}})</strong></div>
            <div><span>Fast / Slow MA</span><strong>${{Number(item.fast_moving_average || 0).toFixed(2)}} / ${{Number(item.slow_moving_average || 0).toFixed(2)}}</strong></div>
            <div><span>Momentum</span><strong>${{formatPercent(item.momentum_percent)}}</strong></div>
            <div><span>MA Gap</span><strong>${{formatPercent(item.moving_average_gap_percent)}}</strong></div>
            <div><span>Breakout / Pullback</span><strong>${{Number(item.breakout_level || 0).toFixed(2)}} / ${{Number(item.pullback_level || 0).toFixed(2)}}</strong></div>
            <div><span>Stop / Trail</span><strong>${{Number(item.stop_price || 0).toFixed(2)}} / ${{Number(item.trailing_stop_price || 0).toFixed(2)}}</strong></div>
            <div><span>Target</span><strong>${{Number(item.target_price || 0).toFixed(2)}}</strong></div>
          </div>
          <div class="strategy-note"><span>Signal Basis</span><strong>${{escapeHtml(item.signal_reason)}}</strong></div>
          <p class="rationale">${{escapeHtml(item.rationale)}}</p>
          <div class="action-row" data-symbol="${{escapeHtml(item.symbol)}}">
            <button data-action="buy">Buy</button>
            <button data-action="sell">Sell</button>
            <button data-action="hold">Hold</button>
            <button data-action="skip">Skip</button>
            <button data-action="pause">Pause Auto</button>
          </div>
          <div class="override-note" id="override-${{escapeHtml(item.symbol)}}">No manual override yet.</div>
        </section>`;
      }}).join("");
      target.innerHTML = cards;
      applyAssetViewFilter();
    }}

    function renderSnapshot(snapshot) {{
      currentSnapshot = snapshot;
      const generated = document.getElementById("generated-at");
      if (generated) {{
        generated.textContent = `Manual review cockpit for AI trading decisions, pending orders, and session control. Generated ${{formatDisplayDate(snapshot.generated_at)}}.`;
      }}
      const equity = document.getElementById("stat-equity");
      const cash = document.getElementById("stat-cash");
      const invested = document.getElementById("stat-invested");
      const orders = document.getElementById("stat-orders");
      if (equity) equity.textContent = formatMoney(snapshot.total_equity);
      if (cash) cash.textContent = formatMoney(snapshot.cash);
      if (invested) invested.textContent = formatMoney(snapshot.invested_value);
      if (orders) orders.textContent = String(snapshot.open_orders_count || 0);
        renderMarketStrip(snapshot);
        renderPendingOpenOrders(snapshot);
        renderMarketWatch(snapshot);
        renderRecentOrderActivity(snapshot);
        renderAlertList(snapshot.alerts || [], currentRuntimeState.recent_logs || []);
        renderAssetCards(snapshot);
        renderOverrides();
        renderProcessStatus();
        renderLiveActivity();
        if (currentInvestmentPlan) {{
          loadInvestmentPlan();
        }}
      lastRenderedSnapshotSignature = snapshotSignature(snapshot);
      }}

    function hasMeaningfulChange(nextSnapshot) {{
      return snapshotSignature(nextSnapshot) !== lastRenderedSnapshotSignature;
    }}

    function updateGeneratedAt(snapshot) {{
      currentSnapshot = snapshot;
      const generated = document.getElementById("generated-at");
      if (generated) {{
        generated.textContent = `Manual review cockpit for AI trading decisions, pending orders, and session control. Generated ${{formatDisplayDate(snapshot.generated_at)}}.`;
      }}
    }}

    function restoreLiveStatusAfterSync() {{
      if (liveStatusResetTimer) {{
        window.clearTimeout(liveStatusResetTimer);
      }}
      liveStatusResetTimer = window.setTimeout(() => {{
        liveStatusResetTimer = null;
        renderRuntimeState();
      }}, 900);
    }}

    function showSnapshotSyncIndicator(meaningful) {{
      if (!liveStatus) return;
      liveStatus.textContent = meaningful ? "Updated just now." : "Synced.";
      restoreLiveStatusAfterSync();
    }}

    function queueSnapshotRefresh(snapshot, meaningful, force = false) {{
      if (dashboardRefreshTimer) {{
        window.clearTimeout(dashboardRefreshTimer);
      }}
      const delay = force ? 0 : meaningful ? 120 : 220;
      dashboardRefreshTimer = window.setTimeout(() => {{
        dashboardRefreshTimer = null;
        if (force || meaningful) {{
          renderSnapshot(snapshot);
        }} else {{
          updateGeneratedAt(snapshot);
        }}
        showSnapshotSyncIndicator(meaningful);
      }}, delay);
    }}

    async function postJson(url, payload, method = "POST") {{
      const response = await fetch(apiUrl(url), {{
        method,
        headers: {{ "Content-Type": "application/json" }},
        body: payload ? JSON.stringify(payload) : undefined,
      }});
      if (!response.ok) {{
        throw new Error(`Request failed: ${{response.status}}`);
      }}
      return response.json();
    }}

    async function pollForDashboardRefresh(force = false) {{
      if (!autoVisualRefresh && !force) {{
        if (liveStatus) {{
          liveStatus.textContent = "Auto visual refresh is paused. Use Refresh View when you want a stable update.";
        }}
        return;
      }}
      try {{
        const response = await fetch(apiUrl("/api/dashboard"), {{ cache: "no-store" }});
        if (!response.ok) throw new Error("dashboard fetch failed");
        const payload = await response.json();
        if (payload.generated_at && (force || payload.generated_at !== currentSnapshot.generated_at)) {{
          const meaningful = force || hasMeaningfulChange(payload) || snapshotIsStaleForRuntime();
          queueSnapshotRefresh(payload, meaningful, force);
          return;
        }}
      }} catch (error) {{
        if (liveStatus) {{
          liveStatus.textContent = "Live refresh paused. Waiting for the local server...";
        }}
      }}
    }}

    async function setOverride(symbol, action) {{
      await postJson("/api/overrides", {{ symbol, action }});
      await renderOverrides();
    }}

    async function setAiTradingEnabled(enabled) {{
      await postJson("/api/ai-trading", {{ enabled }});
      aiTradingEnabled = enabled;
      operatorNotice = enabled
        ? {{
            kind: "user-start",
            icon: "✓",
            title: "Trading turned on by user",
            message: "Confirmed. AI trading has resumed.",
          }}
        : {{
            kind: "user-stop",
            icon: "■",
            title: "User stopped next run",
            message: "Confirmed. The current run may finish, but the next run will not start.",
          }};
      renderAiTradingState();
      renderAlertList(currentSnapshot.alerts || [], currentRuntimeState.recent_logs || []);
      await renderOverrides();
      renderRuntimeState();
    }}

    async function saveDurationMinutes() {{
      const minutes = parseDurationMinutes(durationMinutesInput?.value || 15);
      if (minutes === null) {{
        operatorNotice = {{
          kind: "warning",
          icon: "!",
          title: "Run duration invalid",
          message: "Please enter a whole number of minutes greater than zero.",
        }};
        renderAlertList(currentSnapshot.alerts || [], currentRuntimeState.recent_logs || []);
        return;
      }}
      const payload = await postJson("/api/runtime-settings", {{ duration_minutes: minutes }});
      currentRuntimeState = payload.runtime || currentRuntimeState;
      durationMinutesDirty = false;
      operatorNotice = {{
        kind: "system",
        icon: "•",
        title: "Run duration saved",
        message: `Session duration set to ${{minutes}} minute(s).`,
      }};
      renderRuntimeState();
      renderAlertList(currentSnapshot.alerts || [], currentRuntimeState.recent_logs || []);
    }}

    async function startBotRun() {{
      try {{
        const payload = await postJson("/api/start-bot", {{}});
        operatorNotice = {{
          kind: "user-start",
          icon: "✓",
          title: "Bot started by user",
          message: `Trading session requested for ${{payload.duration_minutes}} minute(s).`,
        }};
        await pollRuntimeState();
      }} catch (error) {{
        operatorNotice = {{
          kind: "warning",
          icon: "!",
          title: "Bot start blocked",
          message: "The bot is already running or the local server rejected the start request.",
        }};
        renderAlertList(currentSnapshot.alerts || [], currentRuntimeState.recent_logs || []);
      }}
    }}

    async function startRunNow() {{
      try {{
        await postJson("/api/start-run-now", {{}});
        operatorNotice = {{
          kind: "user-start",
          icon: "▶",
          title: "Immediate run requested",
          message: "The next trading cycle was asked to start right away.",
        }};
        await pollRuntimeState();
      }} catch (error) {{
        operatorNotice = {{
          kind: "warning",
          icon: "!",
          title: "Run-now unavailable",
          message: "No waiting session was available to accelerate right now.",
        }};
        renderAlertList(currentSnapshot.alerts || [], currentRuntimeState.recent_logs || []);
      }}
    }}

    async function saveInvestmentPlan() {{
      const payload = await postJson("/api/investment-plan", {{
        starting_budget: parseLocaleNumber(settingsStartingBudget?.value || 0),
        cash_reserve_percent: parseLocaleNumber(settingsCashReserve?.value || 0),
        equity_allocation_percent: parseLocaleNumber(settingsEquityStash?.value || 0),
        crypto_allocation_percent: parseLocaleNumber(settingsCryptoStash?.value || 0),
      }});
      renderInvestmentPlan(payload);
      operatorNotice = {{
        kind: "system",
        icon: "•",
        title: "Investment plan saved",
        message: "Budget and stash percentages were saved. Restart the bot for the change to take effect cleanly.",
      }};
      await pollRuntimeState();
    }}

    async function transferInvestmentWallets() {{
      const payload = await postJson("/api/investment-plan/transfer", {{
        from_wallet: String(transferFromWallet?.value || "cash"),
        to_wallet: String(transferToWallet?.value || "crypto"),
        amount: parseLocaleNumber(transferAmount?.value || 0),
      }});
      renderInvestmentPlan(payload);
      operatorNotice = {{
        kind: "system",
        icon: "•",
        title: "Stash transfer saved",
        message: `Moved ${{formatMoney(payload.moved_amount || 0)}} inside the bot planning wallets. Restart the bot for the change to take effect cleanly.`,
      }};
      await pollRuntimeState();
    }}

    async function pollSessionReport() {{
      try {{
        const response = await fetch(apiUrl("/api/session-report"), {{ cache: "no-store" }});
        if (!response.ok) {{
          currentSessionReport = null;
          renderNightWatch();
          return;
        }}
        currentSessionReport = await response.json();
        renderNightWatch();
      }} catch (error) {{
        currentSessionReport = null;
        renderNightWatch();
      }}
    }}

    async function pollRuntimeState() {{
      try {{
        const response = await fetch(apiUrl("/api/runtime-state"), {{ cache: "no-store" }});
        if (!response.ok) throw new Error("runtime-state fetch failed");
          const previousLogs = currentRuntimeState.recent_logs || [];
          const payload = await response.json();
          currentRuntimeState = payload.runtime || currentRuntimeState;
          aiTradingEnabled = payload.ai_trading_enabled !== false;
          currentRuntimeMeta = {{
            session_lock_owner_pid: payload.session_lock_owner_pid ?? null,
            operator_server_lock_owner_pid: payload.operator_server_lock_owner_pid ?? null,
            operator_server_pid: payload.operator_server_pid ?? null,
          }};
            renderAiTradingState();
            renderRuntimeState();
            renderProcessStatus();
            renderLiveActivity();
            renderNightWatch();
            renderAlertList(currentSnapshot.alerts || [], currentRuntimeState.recent_logs || []);
            syncTransactionNotification(currentRuntimeState.recent_logs || [], previousLogs.length > 0);
            if (snapshotIsStaleForRuntime()) {{
              await pollForDashboardRefresh(true);
            }}
        }} catch (error) {{
        const badge = document.getElementById("runner-badge");
        if (badge) {{
          badge.className = "runner-badge blocked";
          badge.textContent = "Offline";
        }}
          if (liveStatus) {{
            liveStatus.textContent = operatorApiBase
              ? "Trying to reach the local operator server..."
              : "Runtime status is temporarily unavailable.";
          }}
          renderNightWatch();
        }}
      }}

    document.addEventListener("click", async (event) => {{
      const button = event.target.closest(".action-row button");
      if (!button) return;
      const symbol = button.parentElement.dataset.symbol;
      await setOverride(symbol, button.dataset.action);
    }});

    document.getElementById("refresh-window").addEventListener("click", async () => {{
      await pollForDashboardRefresh();
    }});
      if (fullReloadButton) {{
        fullReloadButton.addEventListener("click", () => {{
          const cacheBust = `v=${{Date.now()}}`;
          if (operatorApiBase && window.location.protocol === "file:") {{
            window.location.href = `${{apiUrl("/operator")}}?${{cacheBust}}`;
            return;
          }}
          const nextUrl = new URL(window.location.href);
          nextUrl.searchParams.set("v", String(Date.now()));
          window.location.replace(nextUrl.toString());
        }});
      }}
    if (aiMasterToggle) {{
      aiMasterToggle.addEventListener("click", async () => {{
        await setAiTradingEnabled(!aiTradingEnabled);
      }});
    }}
    if (startBotButton) {{
      startBotButton.addEventListener("click", async () => {{
        await startBotRun();
      }});
    }}
    if (startRunNowButton) {{
      startRunNowButton.addEventListener("click", async () => {{
        await startRunNow();
      }});
    }}
    if (saveDurationButton) {{
      saveDurationButton.addEventListener("click", async () => {{
        await saveDurationMinutes();
      }});
    }}
    if (durationMinutesInput) {{
      durationMinutesInput.addEventListener("input", () => {{
        durationMinutesDirty = true;
      }});
      durationMinutesInput.addEventListener("blur", () => {{
        const parsed = parseDurationMinutes(durationMinutesInput.value || "");
        if (parsed !== null && parsed === Number(currentRuntimeState.desired_session_duration_minutes || 0)) {{
          durationMinutesDirty = false;
        }}
      }});
    }}
    if (investmentPlanButton) {{
      investmentPlanButton.addEventListener("click", async () => {{
        await loadInvestmentPlan();
        openInvestmentPlanModal();
      }});
    }}
    if (investmentPlanClose) {{
      investmentPlanClose.addEventListener("click", () => {{
        closeInvestmentPlanModal();
      }});
    }}
    if (investmentPlanModal) {{
      investmentPlanModal.addEventListener("click", (event) => {{
        if (event.target === investmentPlanModal) {{
          closeInvestmentPlanModal();
        }}
      }});
    }}
    if (investmentPlanSave) {{
      investmentPlanSave.addEventListener("click", async () => {{
        await saveInvestmentPlan();
      }});
    }}
    if (transferWalletsButton) {{
      transferWalletsButton.addEventListener("click", async () => {{
        await transferInvestmentWallets();
      }});
    }}
    document.getElementById("approve-all").addEventListener("click", async () => {{
      await postJson("/api/overrides/bulk", {{
        action: "approve_ai",
        symbols: currentSnapshot.recommendations.map((rec) => rec.symbol),
      }});
      await renderOverrides();
    }});
    document.getElementById("pause-all").addEventListener("click", async () => {{
      await postJson("/api/overrides/bulk", {{
        action: "pause_auto",
        symbols: currentSnapshot.recommendations.map((rec) => rec.symbol),
      }});
      await renderOverrides();
    }});
    document.getElementById("clear-overrides").addEventListener("click", async () => {{
      await fetch(apiUrl("/api/overrides"), {{ method: "DELETE" }});
      await renderOverrides();
    }});
    if (viewToggleGroup) {{
      viewToggleGroup.addEventListener("click", (event) => {{
        const button = event.target.closest("[data-view]");
        if (!button) return;
        currentViewFilter = String(button.getAttribute("data-view") || "all");
        applyAssetViewFilter();
      }});
    }}

    renderSnapshot(currentSnapshot);
    renderOverrides();
    loadInvestmentPlan();
    renderAiTradingState();
    syncTransactionNotification(currentRuntimeState.recent_logs || [], false);
    renderMarketWatch(currentSnapshot);
    renderRecentOrderActivity(currentSnapshot);
    renderNightWatch();
    pollRuntimeState();
    pollSessionReport();
    sendHeartbeat();
    pollForDashboardRefresh(true);
    document.addEventListener("visibilitychange", () => {{
      if (document.visibilityState === "visible") {{
        sendHeartbeat();
        pollForDashboardRefresh(true);
      }}
    }});
    window.addEventListener("focus", () => {{
      sendHeartbeat();
      pollForDashboardRefresh(true);
    }});
    setInterval(sendHeartbeat, 10000);
      setInterval(pollRuntimeState, 1000);
    setInterval(pollSessionReport, 15000);
    setInterval(renderRuntimeState, 1000);
    if (autoVisualRefresh) {{
      setInterval(() => pollForDashboardRefresh(false), 5000);
      pollForDashboardRefresh(true);
    }} else if (liveStatus) {{
      liveStatus.textContent = "Auto visual refresh is paused. Runtime status still updates live.";
    }}
  </script>
</body>
</html>"""

    def _sparkline_svg(
        self,
        points: list[ChartPoint],
        *,
        stroke: str,
        markers: list[TradeMarker] | None = None,
    ) -> str:
        width = 720
        height = 160
        margin = 14
        if not points:
            return f"<svg viewBox='0 0 {width} {height}' role='img'><text x='24' y='80' fill='#6c655f'>No chart data yet.</text></svg>"

        values = [point.value for point in points]
        min_value = min(values)
        max_value = max(values)
        value_range = max(max_value - min_value, 1e-9)
        step = (width - margin * 2) / max(len(points) - 1, 1)
        coords: list[tuple[float, float]] = []
        for index, point in enumerate(points):
            x = margin + index * step
            normalized = (point.value - min_value) / value_range
            y = height - margin - normalized * (height - margin * 2)
            coords.append((x, y))
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)

        marker_nodes = ""
        if markers:
            index_by_time = {point.timestamp: idx for idx, point in enumerate(points)}
            circles = []
            for marker in markers:
                idx = index_by_time.get(marker.timestamp)
                if idx is None:
                    continue
                x, y = coords[idx]
                color = "#2f7d4c" if marker.side.lower() == "buy" else "#b33a3a"
                circles.append(
                    f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' fill='{color}' stroke='white' stroke-width='2'>"
                    f"<title>{marker.side.upper()} {marker.symbol} @ ${marker.price:.2f} - {marker.note}</title></circle>"
                )
            marker_nodes = "".join(circles)

        return f"<svg viewBox='0 0 {width} {height}' role='img'><polyline fill='none' stroke='{stroke}' stroke-width='3' points='{polyline}' />{marker_nodes}</svg>"

    @staticmethod
    def _format_display_datetime(value) -> str:
        return value.strftime("%d.%m.%Y - %H:%M:%S")

    @staticmethod
    def _event_quantity(event: RunEvent) -> float:
        quantity = event.details.get("quantity")
        if quantity is not None:
            return float(quantity)

        side = str(event.details.get("side", "")).lower()
        price = float(event.details.get("price", 0.0))
        notional = event.details.get("notional")
        if side == "buy" and notional is not None and price > 0:
            return float(notional) / price
        return 0.0
