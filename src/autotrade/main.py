from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import RequestError

from autotrade.brokers.alpaca import AlpacaBrokerAdapter
from autotrade.brokers.base import BrokerAdapter
from autotrade.brokers.null import NullBrokerAdapter
from autotrade.config import load_app_config
from autotrade.models import RunEvent
from autotrade.risk.manager import RiskManager
from autotrade.services.dashboard import DashboardService
from autotrade.services.crypto_stream import CryptoStreamWatcher
from autotrade.services.event_risk import EventRiskService
from autotrade.services.logging import StructuredLogger
from autotrade.services.operator_overrides import OperatorOverrideStore
from autotrade.services.runtime_state import RuntimeStateStore
from autotrade.services.session_report import SessionReportService
from autotrade.services.session_lock import SessionLock
from autotrade.services.operator_window_state import OperatorWindowStateStore
from autotrade.services.reconciliation import ReconciliationService
from autotrade.services.trading_loop import TradingLoop
from autotrade.config import infer_symbol_asset_class


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def ensure_operator_server(*, reports_dir: Path, port: int) -> tuple[str, bool]:
    url = f"http://127.0.0.1:{port}/operator"
    server_lock = SessionLock(reports_dir / "operator_server.lock")
    if is_port_open("127.0.0.1", port):
        return url, False
    if server_lock.is_active():
        return url, False

    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    preferred_python = Path.cwd() / ".venv" / "Scripts" / "python.exe"
    python_executable = str(preferred_python if preferred_python.exists() else sys.executable)

    subprocess.Popen(
        [
            python_executable,
            "-m",
            "autotrade.operator_server",
            "--reports-dir",
            str(reports_dir),
            "--port",
            str(port),
        ],
        cwd=str(Path.cwd()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )
    return url, True


def open_operator_window(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
        return
    webbrowser.open(url)


def build_broker(config) -> BrokerAdapter:
    if config.runtime.mode == "dry_run" and (not config.api_key or not config.api_secret):
        return NullBrokerAdapter()
    return AlpacaBrokerAdapter(
        base_url=config.account_base_url,
        market_data_url=config.market_data_url,
        asset_class=config.runtime.asset_class,
        crypto_location=config.runtime.crypto_location,
        api_key=config.api_key,
        api_secret=config.api_secret,
    )


def resolve_session_duration_minutes(config, runtime_state_store: RuntimeStateStore) -> int:
    env_minutes = os.getenv("AUTOTRADE_SESSION_DURATION_MINUTES")
    if env_minutes is not None:
        try:
            return max(1, int(env_minutes))
        except ValueError:
            pass

    runtime_minutes = runtime_state_store.load().get("desired_session_duration_minutes")
    if runtime_minutes is not None:
        try:
            return max(1, int(runtime_minutes))
        except (TypeError, ValueError):
            pass

    return max(1, int(config.runtime.session_duration_minutes))


def reconciliation_plan_event(config) -> RunEvent:
    plan = config.investment_plan
    return RunEvent(
        event_type="investment_plan_snapshot",
        message="Loaded investment plan for this run.",
        details={
            "starting_budget": plan.starting_budget,
            "cash_reserve_percent": plan.cash_reserve_percent,
            "max_symbol_allocation_percent": plan.max_symbol_allocation_percent,
            "preferred_symbols": plan.preferred_symbols,
            "allowed_symbols": plan.allowed_symbols,
            "avoided_symbols": plan.avoided_symbols,
        },
    )


def paper_readiness_events(config) -> list[RunEvent]:
    events: list[RunEvent] = []
    if config.runtime.mode != "paper":
        return events

    if not config.api_key or not config.api_secret:
        events.append(
            RunEvent(
                event_type="paper_readiness_blocker",
                message="Alpaca paper credentials are missing.",
                details={
                    "missing_api_key": not bool(config.api_key),
                    "missing_api_secret": not bool(config.api_secret),
                    "hint": "Set ALPACA_API_KEY and ALPACA_API_SECRET before starting paper trading.",
                },
            )
        )

    if config.investment_plan.starting_budget <= 0:
        events.append(
            RunEvent(
                event_type="paper_readiness_blocker",
                message="Investment plan starting budget must be greater than zero.",
                details={"starting_budget": config.investment_plan.starting_budget},
            )
        )

    if not config.watchlist:
        events.append(
            RunEvent(
                event_type="paper_readiness_blocker",
                message="Watchlist is empty.",
                details={"watchlist": config.watchlist},
            )
        )

    return events


def wait_until_next_cycle(target_dt: datetime, runtime_state_store: RuntimeStateStore) -> bool:
    while True:
        remaining = (target_dt - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return False
        if runtime_state_store.consume_immediate_cycle_request():
            return True
        time.sleep(min(1.0, remaining))


def build_crypto_stream_watcher(
    *,
    config,
    runtime_state_store: RuntimeStateStore,
    override_store: OperatorOverrideStore,
) -> CryptoStreamWatcher | None:
    if not config.runtime.crypto_streaming_enabled:
        runtime_state_store.update_crypto_stream_status(
            status="disabled",
            message="Crypto stream disabled by config.",
        )
        return None
    if config.runtime.asset_class not in {"crypto", "mixed"}:
        runtime_state_store.update_crypto_stream_status(
            status="inactive",
            message="Crypto stream inactive for equity-only mode.",
        )
        return None
    crypto_symbols = [symbol for symbol in config.watchlist if infer_symbol_asset_class(symbol) == "crypto"]
    if not crypto_symbols:
        runtime_state_store.update_crypto_stream_status(
            status="inactive",
            message="No crypto symbols are active in the watchlist.",
        )
        return None
    return CryptoStreamWatcher(
        symbols=crypto_symbols,
        api_key=config.api_key,
        api_secret=config.api_secret,
        location=config.runtime.crypto_location,
        cooldown_seconds=config.runtime.crypto_stream_cooldown_seconds,
        runtime_state_store=runtime_state_store,
        override_store=override_store,
    )


def append_transaction_logs(runtime_state_store: RuntimeStateStore, events: list[RunEvent]) -> None:
    for event in events:
        if event.event_type != "order_submitted":
            continue
        details = event.details
        symbol = str(details.get("symbol", "UNKNOWN"))
        side = str(details.get("side", "buy")).lower()
        asset_class = str(details.get("asset_class", "us_equity")).replace("_", " ")
        notional = details.get("notional")
        quantity = details.get("quantity")
        price = details.get("price")

        amount_label = ""
        if quantity is not None:
            amount_label = f"{float(quantity):.6f}".rstrip("0").rstrip(".")
        elif notional is not None:
            amount_label = f"${float(notional):.2f}"

        message_parts = [f"{side.upper()} {symbol}"]
        if amount_label:
            message_parts.append(f"for {amount_label}")
        if price is not None:
            message_parts.append(f"at ${float(price):.4f}".rstrip("0").rstrip("."))
        message_parts.append(f"({asset_class})")

        runtime_state_store.append_log(
            kind="transaction",
            title=f"{side.capitalize()} transaction started",
            message=" ".join(message_parts),
        )


def record_refresh_blocked(*, runtime_state_store: RuntimeStateStore, logger: StructuredLogger, failed_stage: str) -> RunEvent:
    event = RunEvent(
        event_type="monitor_refresh_blocked",
        message="Live Alpaca paper broker connection was refused; dashboard was not refreshed.",
        details={
            "reason": "connection_refused",
            "failed_stage": failed_stage,
            "reports_refreshed": False,
        },
    )
    logger.write_event(event)
    runtime_state_store.append_log(
        kind="warning",
        title="Monitor refresh blocked",
        message=f"Live Alpaca paper broker connection was refused during {failed_stage}; dashboard was not refreshed.",
    )
    print(f"[{event.event_type}] {event.message} :: {event.details}")
    return event


def main() -> None:
    config = load_app_config(Path.cwd())
    logger = StructuredLogger(Path.cwd() / "logs" / "runtime.jsonl")
    reports_dir = Path.cwd() / "reports"
    runtime_state_store = RuntimeStateStore(reports_dir / "runtime_state.json")
    session_lock = SessionLock(reports_dir / "session.lock")
    session_reports = SessionReportService(output_dir=reports_dir)
    if not session_lock.acquire(pid=os.getpid(), metadata={"entrypoint": "autotrade.main"}):
        owner_pid = session_lock.owner_pid()
        runtime_state_store.clear_start_request()
        runtime_state_store.append_log(
            kind="warning",
            title="Session start blocked",
            message=f"Another bot session already owns the session lock{f' (PID {owner_pid})' if owner_pid else ''}.",
        )
        return
    readiness_events = paper_readiness_events(config)
    for event in readiness_events:
        logger.write_event(event)
        print(f"[{event.event_type}] {event.message} :: {event.details}")
    if readiness_events:
        session_lock.release(pid=os.getpid())
        return

    broker = build_broker(config)
    override_store = OperatorOverrideStore(reports_dir / "operator_overrides.json")
    window_state_store = OperatorWindowStateStore(reports_dir / "operator_window_state.json")
    dashboard = DashboardService(broker=broker, config=config, output_dir=reports_dir)
    event_risk = EventRiskService(config.event_risk)
    risk_manager = RiskManager(config.risk)
    loop = TradingLoop(
        config=config,
        broker=broker,
        risk_manager=risk_manager,
        logger=logger,
        override_store=override_store,
    )
    reconciliation = ReconciliationService(broker)
    crypto_stream = build_crypto_stream_watcher(
        config=config,
        runtime_state_store=runtime_state_store,
        override_store=override_store,
    )
    if os.getenv("AUTOTRADE_OPEN_OPERATOR_WINDOW", "true").strip().lower() in {"1", "true", "yes", "on"}:
        port = int(os.getenv("AUTOTRADE_OPERATOR_SERVER_PORT", "8765"))
        url, started_new_server = ensure_operator_server(reports_dir=reports_dir, port=port)
        should_reopen = not window_state_store.is_recent(
            max_age_seconds=int(os.getenv("AUTOTRADE_OPERATOR_WINDOW_HEARTBEAT_MAX_AGE", "45"))
        )
        if (
            started_new_server
            or should_reopen
            or os.getenv("AUTOTRADE_REOPEN_OPERATOR_WINDOW", "false").strip().lower() in {"1", "true", "yes", "on"}
        ):
            open_operator_window(url)

    session_minutes = resolve_session_duration_minutes(config, runtime_state_store)
    poll_interval_seconds = max(5, int(config.runtime.poll_interval_seconds))
    session_end = datetime.now(timezone.utc) + timedelta(minutes=session_minutes)
    session_started = False
    session_failed = False
    runtime_state_store.start_session(
        duration_minutes=session_minutes,
        poll_interval_seconds=poll_interval_seconds,
        bot_pid=os.getpid(),
    )
    session_started = True
    runtime_state_store.append_log(
        kind="system",
        title="Session started",
        message=f"Paper test session started for {session_minutes} minute(s).",
    )
    if crypto_stream is not None:
        crypto_stream.start()

    cycle_number = 0
    session_events: list[RunEvent] = []
    try:
        while datetime.now(timezone.utc) < session_end:
            if not override_store.ai_trading_enabled():
                event = RunEvent(
                    event_type="ai_trading_cycle_blocked",
                    message="Run can't start due to AI Trading being off.",
                    details={"enabled": False},
                )
                logger.write_event(event)
                print(f"[{event.event_type}] {event.message} :: {event.details}")
                session_events.append(event)
                runtime_state_store.append_log(
                    kind="warning",
                    title="Run can't start due to button off",
                    message="The next scheduled run was blocked because AI Trading is OFF.",
                )
                next_cycle_at = min(
                    session_end,
                    datetime.now(timezone.utc) + timedelta(seconds=poll_interval_seconds),
                )
                runtime_state_store.mark_blocked_by_ai_off(next_cycle_at=next_cycle_at.isoformat())
                wait_until_next_cycle(next_cycle_at, runtime_state_store)
                continue

            cycle_number += 1
            runtime_state_store.mark_cycle_started(cycle_number=cycle_number)
            runtime_state_store.append_log(
                kind="system",
                title=f"Cycle {cycle_number} started",
                message="Trading cycle is now running.",
            )

            startup_events = []
            startup_events.append(
                reconciliation_event := reconciliation_plan_event(config)
            )
            logger.write_event(reconciliation_event)
            print(f"[{reconciliation_event.event_type}] {reconciliation_event.message} :: {reconciliation_event.details}")
            session_events.append(reconciliation_event)

            try:
                for event in reconciliation.cleanup_duplicate_open_orders():
                    startup_events.append(event)
                    logger.write_event(event)
                    print(f"[{event.event_type}] {event.message} :: {event.details}")
                    session_events.append(event)

                for event in reconciliation.reconcile():
                    startup_events.append(event)
                    logger.write_event(event)
                    print(f"[{event.event_type}] {event.message} :: {event.details}")
                    session_events.append(event)

                for event in event_risk.collect_alerts():
                    startup_events.append(event)
                    logger.write_event(event)
                    print(f"[{event.event_type}] {event.message} :: {event.details}")
                    session_events.append(event)
            except RequestError:
                session_events.append(
                    record_refresh_blocked(
                        runtime_state_store=runtime_state_store,
                        logger=logger,
                        failed_stage="startup_refresh",
                    )
                )
                session_failed = True
                break

            try:
                run_events = loop.run_once()
            except RequestError:
                session_events.append(
                    record_refresh_blocked(
                        runtime_state_store=runtime_state_store,
                        logger=logger,
                        failed_stage="trading_loop",
                    )
                )
                session_failed = True
                break

            for event in run_events:
                print(f"[{event.event_type}] {event.message} :: {event.details}")
                session_events.append(event)
            append_transaction_logs(runtime_state_store, run_events)

            try:
                dashboard.record_trade_markers_from_events(run_events)
                snapshot = dashboard.build_snapshot(alerts=startup_events + run_events)
                json_path, html_path = dashboard.write_reports(snapshot)
            except RequestError:
                session_events.append(
                    record_refresh_blocked(
                        runtime_state_store=runtime_state_store,
                        logger=logger,
                        failed_stage="dashboard_refresh",
                    )
                )
                session_failed = True
                break
            print(f"[dashboard] Reports written :: {{'json': '{json_path}', 'html': '{html_path}'}}")

            next_cycle_at_dt = datetime.now(timezone.utc) + timedelta(seconds=poll_interval_seconds)
            has_next_cycle = next_cycle_at_dt < session_end
            runtime_state_store.mark_cycle_finished(
                cycle_number=cycle_number,
                next_cycle_at=next_cycle_at_dt.isoformat() if has_next_cycle else None,
            )
            runtime_state_store.append_log(
                kind="system",
                title=f"Cycle {cycle_number} finished",
                message="Trading cycle completed and reports were refreshed.",
            )

            if not has_next_cycle:
                break

            runtime_state_store.mark_waiting(next_cycle_at=next_cycle_at_dt.isoformat())
            forced = wait_until_next_cycle(next_cycle_at_dt, runtime_state_store)
            if forced:
                runtime_state_store.append_log(
                    kind="system",
                    title="Run started immediately",
                    message="Operator requested the next cycle to begin without waiting for the full interval.",
                )
    finally:
        if crypto_stream is not None:
            crypto_stream.stop()
        if session_started:
            runtime_state_store.finish_session()
        runtime_state_store.set_bot_process(None)
        session_lock.release(pid=os.getpid())

    if session_failed:
        return

    final_snapshot = dashboard.build_snapshot(alerts=session_events)
    session_report_json, session_report_html = session_reports.write_report(
        session_minutes=session_minutes,
        completed_cycles=cycle_number,
        alerts=session_events,
        final_snapshot=final_snapshot,
    )
    runtime_state_store.finish_session()
    runtime_state_store.append_log(
        kind="system",
        title="Session finished",
        message=f"Paper test session ended after {session_minutes} minute(s).",
    )
    runtime_state_store.append_log(
        kind="system",
        title="Session report ready",
        message=f"Saved session report to {session_report_html.name}.",
    )
    print(
        f"[session_report] Reports written :: {{'json': '{session_report_json}', 'html': '{session_report_html}'}}"
    )


if __name__ == "__main__":
    main()
