from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from autotrade.config import infer_symbol_asset_class, normalize_symbol
from autotrade.services.investment_plan_store import InvestmentPlanStore
from autotrade.services.operator_overrides import OperatorOverrideStore
from autotrade.services.runtime_state import RuntimeStateStore
from autotrade.services.operator_window_state import OperatorWindowStateStore
from autotrade.services.session_lock import SessionLock


class OperatorRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/operator", "/operator/"}:
            self._serve_file(self.server.reports_dir / "operator_window.html", "text/html; charset=utf-8")  # type: ignore[attr-defined]
            return
        if path == "/dashboard":
            self._serve_file(self.server.reports_dir / "dashboard.html", "text/html; charset=utf-8")  # type: ignore[attr-defined]
            return
        if path == "/api/overrides":
            self._send_json(  # type: ignore[attr-defined]
                {
                    "overrides": self.server.override_store.load(),
                    "ai_trading_enabled": self.server.override_store.ai_trading_enabled(),
                }
            )
            return
        if path == "/api/dashboard":
            dashboard_path = self.server.reports_dir / "dashboard.json"  # type: ignore[attr-defined]
            if dashboard_path.exists():
                self._send_json(json.loads(dashboard_path.read_text(encoding="utf-8")))
            else:
                self._send_json({"error": "dashboard_not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path == "/api/session-report":
            report_path = self.server.reports_dir / "session_report.json"  # type: ignore[attr-defined]
            if report_path.exists():
                self._send_json(json.loads(report_path.read_text(encoding="utf-8")))
            else:
                self._send_json({"error": "session_report_not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        if path == "/api/window-status":
            state = self.server.window_state_store.load()  # type: ignore[attr-defined]
            self._send_json({"window": state})
            return
        if path == "/api/runtime-state":
            self._send_json(
                {
                    "runtime": self.server.runtime_state_store.load(),  # type: ignore[attr-defined]
                    "ai_trading_enabled": self.server.override_store.ai_trading_enabled(),  # type: ignore[attr-defined]
                    "session_lock_owner_pid": self.server.session_lock.owner_pid(),  # type: ignore[attr-defined]
                    "operator_server_lock_owner_pid": self.server.server_lock.owner_pid(),  # type: ignore[attr-defined]
                    "operator_server_pid": os.getpid(),
                }
            )
            return
        if path == "/api/investment-plan":
            dashboard_payload = self._load_dashboard_payload()
            payload = self.server.investment_plan_store.build_summary(  # type: ignore[attr-defined]
                dashboard_payload=dashboard_payload
            )
            self._send_json(payload)
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json_body()
        if body is None:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/overrides":
            raw_symbol = str(body.get("symbol", "")).strip()
            symbol = normalize_symbol(raw_symbol, infer_symbol_asset_class(raw_symbol))
            action = str(body.get("action", "")).strip().lower()
            if not symbol or not action:
                self._send_json({"error": "symbol_and_action_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            overrides = self.server.override_store.set_override(symbol, action)  # type: ignore[attr-defined]
            self.server.runtime_state_store.append_log(  # type: ignore[attr-defined]
                kind="system",
                title=f"Manual {action.replace('_', ' ')} set",
                message=f"Operator set {symbol} to {action.replace('_', ' ')} for the next trading cycle.",
            )
            self._send_json({"ok": True, "overrides": overrides})
            return

        if path == "/api/overrides/bulk":
            action = str(body.get("action", "")).strip().lower()
            symbols = [
                normalize_symbol(str(symbol).strip(), infer_symbol_asset_class(str(symbol).strip()))
                for symbol in body.get("symbols", [])
                if str(symbol).strip()
            ]
            if not symbols or not action:
                self._send_json({"error": "symbols_and_action_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            overrides = self.server.override_store.set_bulk_override(symbols, action)  # type: ignore[attr-defined]
            self.server.runtime_state_store.append_log(  # type: ignore[attr-defined]
                kind="system",
                title="Bulk override saved",
                message=f"Applied {action.replace('_', ' ')} to {len(symbols)} assets.",
            )
            self._send_json({"ok": True, "overrides": overrides})
            return

        if path == "/api/window-heartbeat":
            payload = self.server.window_state_store.touch()  # type: ignore[attr-defined]
            self._send_json({"ok": True, "window": payload})
            return

        if path == "/api/ai-trading":
            enabled = body.get("enabled")
            if not isinstance(enabled, bool):
                self._send_json({"error": "enabled_boolean_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            overrides = self.server.override_store.set_ai_trading_enabled(enabled)  # type: ignore[attr-defined]
            self.server.runtime_state_store.append_log(  # type: ignore[attr-defined]
                kind="user-start" if enabled else "user-stop",
                title="Trading turned on by user" if enabled else "User stopped next run",
                message="AI trading has been enabled for the next scheduled run."
                if enabled
                else "The current run may finish, but the next scheduled run will not start.",
            )
            self._send_json({"ok": True, "overrides": overrides, "ai_trading_enabled": enabled})
            return

        if path == "/api/runtime-settings":
            minutes = body.get("duration_minutes")
            if not isinstance(minutes, int):
                self._send_json({"error": "duration_minutes_integer_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            state = self.server.runtime_state_store.set_desired_duration_minutes(minutes)  # type: ignore[attr-defined]
            self.server.runtime_state_store.append_log(  # type: ignore[attr-defined]
                kind="system",
                title="Run duration saved",
                message=f"Session duration was set to {max(1, int(minutes))} minute(s) by user.",
            )
            self._send_json({"ok": True, "runtime": state})
            return

        if path == "/api/investment-plan":
            try:
                plan = self.server.investment_plan_store.update_plan(  # type: ignore[attr-defined]
                    starting_budget=float(body.get("starting_budget", 0.0)),
                    cash_reserve_percent=float(body.get("cash_reserve_percent", 0.0)),
                    crypto_allocation_percent=float(body.get("crypto_allocation_percent", 0.0)),
                    equity_allocation_percent=float(body.get("equity_allocation_percent", 0.0)),
                )
            except (TypeError, ValueError):
                self._send_json({"error": "invalid_investment_plan_payload"}, status=HTTPStatus.BAD_REQUEST)
                return
            self.server.runtime_state_store.append_log(  # type: ignore[attr-defined]
                kind="system",
                title="Investment plan saved",
                message=(
                    f"Budget updated to ${plan['starting_budget']:.2f} with "
                    f"{plan['cash_reserve_percent']:.2f}% cash reserve, "
                    f"{plan['crypto_allocation_percent']:.2f}% crypto stash, and "
                    f"{plan['equity_allocation_percent']:.2f}% equity stash. "
                    "Changes apply on the next fresh bot start."
                ),
            )
            payload = self.server.investment_plan_store.build_summary(  # type: ignore[attr-defined]
                dashboard_payload=self._load_dashboard_payload()
            )
            self._send_json({"ok": True, **payload})
            return

        if path == "/api/investment-plan/transfer":
            try:
                before_summary = self.server.investment_plan_store.build_summary(  # type: ignore[attr-defined]
                    dashboard_payload=self._load_dashboard_payload()
                )
                from_wallet = str(body.get("from_wallet", ""))
                to_wallet = str(body.get("to_wallet", ""))
                requested_amount = float(body.get("amount", 0.0))
                plan = self.server.investment_plan_store.transfer(  # type: ignore[attr-defined]
                    from_wallet=from_wallet,
                    to_wallet=to_wallet,
                    amount=requested_amount,
                )
            except (TypeError, ValueError):
                self._send_json({"error": "invalid_transfer_payload"}, status=HTTPStatus.BAD_REQUEST)
                return
            available_key = f"{from_wallet.strip().lower()}_wallet_usd"
            available_before = float(before_summary.get("wallets", {}).get(available_key, 0.0))
            moved_amount = min(max(0.0, requested_amount), available_before)
            self.server.runtime_state_store.append_log(  # type: ignore[attr-defined]
                kind="system",
                title="Stash transfer saved",
                message=(
                    f"Moved ${moved_amount:.2f} from "
                    f"{from_wallet.capitalize()} to "
                    f"{to_wallet.capitalize()} inside the bot planning wallets. "
                    "Changes apply on the next fresh bot start."
                ),
            )
            payload = self.server.investment_plan_store.build_summary(  # type: ignore[attr-defined]
                dashboard_payload=self._load_dashboard_payload()
            )
            self._send_json({"ok": True, **payload, "plan": plan, "moved_amount": moved_amount})
            return

        if path == "/api/start-bot":
            runtime_state_store = self.server.runtime_state_store  # type: ignore[attr-defined]
            session_lock = self.server.session_lock  # type: ignore[attr-defined]
            if session_lock.is_active():
                owner_pid = session_lock.owner_pid()
                runtime_state_store.append_log(
                    kind="warning",
                    title="Start blocked: bot already running",
                    message=f"Ignored start request because the session lock is already held{f' by PID {owner_pid}' if owner_pid else ''}.",
                )
                self._send_json({"error": "bot_already_running"}, status=HTTPStatus.CONFLICT)
                return
            if not runtime_state_store.claim_start_request():
                runtime_state_store.append_log(
                    kind="warning",
                    title="Start blocked: bot already running",
                    message="Ignored repeated start request because a bot session is already active or launching.",
                )
                self._send_json({"error": "bot_already_running"}, status=HTTPStatus.CONFLICT)
                return
            runtime = runtime_state_store.load()
            minutes = max(1, int(runtime.get("desired_session_duration_minutes", 15)))
            try:
                process = launch_bot_process(
                    workspace_dir=self.server.reports_dir.parent,  # type: ignore[attr-defined]
                    duration_minutes=minutes,
                )
                runtime_state_store.set_bot_process(process.pid)
                runtime_state_store.append_log(
                    kind="system",
                    title="Bot started by user",
                    message=f"Trading bot launch requested for a {minutes}-minute session.",
                )
                self._send_json({"ok": True, "pid": process.pid, "duration_minutes": minutes})
            except Exception:
                runtime_state_store.clear_start_request()
                raise
            return

        if path == "/api/start-run-now":
            runtime_state_store = self.server.runtime_state_store  # type: ignore[attr-defined]
            state = runtime_state_store.load()
            if not state.get("session_active"):
                self._send_json({"error": "session_not_active"}, status=HTTPStatus.CONFLICT)
                return
            if state.get("cycle_running"):
                self._send_json({"error": "cycle_already_running"}, status=HTTPStatus.CONFLICT)
                return
            state = runtime_state_store.request_immediate_cycle()
            runtime_state_store.append_log(
                kind="system",
                title="Immediate run requested",
                message="Operator requested the next trading cycle to start immediately.",
            )
            self._send_json({"ok": True, "runtime": state})
            return

        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def _load_dashboard_payload(self) -> dict:
        dashboard_path = self.server.reports_dir / "dashboard.json"  # type: ignore[attr-defined]
        if not dashboard_path.exists():
            return {}
        try:
            return json.loads(dashboard_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/overrides":
            self.server.override_store.clear()  # type: ignore[attr-defined]
            self._send_json({"ok": True, "overrides": {}})
            return
        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": "file_not_found", "path": str(path)}, status=HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: dict, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)


def run_server(*, reports_dir: Path, port: int) -> None:
    server_lock = SessionLock(reports_dir / "operator_server.lock")
    pid = os.getpid()
    if not server_lock.acquire(
        pid=pid,
        metadata={
            "entrypoint": "autotrade.operator_server",
            "port": port,
        },
    ):
        print(f"[operator_server] Another operator server already owns {reports_dir}.")
        return

    server = ThreadingHTTPServer(("127.0.0.1", port), OperatorRequestHandler)
    server.reports_dir = reports_dir  # type: ignore[attr-defined]
    server.override_store = OperatorOverrideStore(reports_dir / "operator_overrides.json")  # type: ignore[attr-defined]
    server.runtime_state_store = RuntimeStateStore(reports_dir / "runtime_state.json")  # type: ignore[attr-defined]
    server.window_state_store = OperatorWindowStateStore(reports_dir / "operator_window_state.json")  # type: ignore[attr-defined]
    server.investment_plan_store = InvestmentPlanStore(reports_dir.parent)  # type: ignore[attr-defined]
    server.session_lock = SessionLock(reports_dir / "session.lock")  # type: ignore[attr-defined]
    server.server_lock = server_lock  # type: ignore[attr-defined]
    print(f"[operator_server] Serving {reports_dir} on http://127.0.0.1:{port}/operator")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        server_lock.release(pid=pid, force=True)


def launch_bot_process(*, workspace_dir: Path, duration_minutes: int):
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

    preferred_python = workspace_dir / ".venv" / "Scripts" / "python.exe"
    python_executable = str(preferred_python if preferred_python.exists() else sys.executable)
    env = os.environ.copy()
    env["AUTOTRADE_SESSION_DURATION_MINUTES"] = str(max(1, int(duration_minutes)))
    return subprocess.Popen(
        [python_executable, "-m", "autotrade.main"],
        cwd=str(workspace_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo,
        env=env,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Autotrade operator window locally.")
    parser.add_argument("--reports-dir", default=str(Path.cwd() / "reports"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run_server(reports_dir=Path(args.reports_dir), port=args.port)


if __name__ == "__main__":
    main()
