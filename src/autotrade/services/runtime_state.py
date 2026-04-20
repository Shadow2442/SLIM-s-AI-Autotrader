from __future__ import annotations

import os
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            if not self._path.exists():
                return self._default_state()
            payload = json.loads(self._path.read_text(encoding="utf-8-sig"))
            state = self._default_state()
            state.update(payload)
            state["recent_logs"] = list(payload.get("recent_logs", []))[-40:]
            return state

    def save(self, payload: dict) -> dict:
        with self._lock:
            self._path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return payload

    def start_session(self, *, duration_minutes: int, poll_interval_seconds: int, bot_pid: int | None = None) -> dict:
        now = datetime.now(timezone.utc)
        payload = self.load()
        payload.update(
            {
                "session_active": True,
                "cycle_running": False,
                "status": "starting",
                "session_started_at": now.isoformat(),
                "session_end_at": (now + timedelta(minutes=duration_minutes)).isoformat(),
                "session_finished_at": None,
                "poll_interval_seconds": poll_interval_seconds,
                "next_cycle_at": now.isoformat(),
                "current_cycle": 0,
                "completed_cycles": 0,
                "last_cycle_started_at": None,
                "last_cycle_finished_at": None,
                "desired_session_duration_minutes": duration_minutes,
                "bot_pid": bot_pid if bot_pid is not None else payload.get("bot_pid"),
                "launch_pending": False,
                "recent_logs": [],
            }
        )
        return self.save(payload)

    def mark_cycle_started(self, *, cycle_number: int) -> dict:
        payload = self.load()
        payload.update(
            {
                "session_active": True,
                "cycle_running": True,
                "status": "running",
                "current_cycle": cycle_number,
                "last_cycle_started_at": utc_now_iso(),
                "next_cycle_at": None,
            }
        )
        return self.save(payload)

    def mark_cycle_finished(self, *, cycle_number: int, next_cycle_at: str | None = None) -> dict:
        payload = self.load()
        payload.update(
            {
                "session_active": True,
                "cycle_running": False,
                "status": "waiting" if next_cycle_at else "completed",
                "current_cycle": cycle_number,
                "completed_cycles": max(int(payload.get("completed_cycles", 0)), cycle_number),
                "last_cycle_finished_at": utc_now_iso(),
                "next_cycle_at": next_cycle_at,
            }
        )
        return self.save(payload)

    def mark_waiting(self, *, next_cycle_at: str) -> dict:
        payload = self.load()
        payload.update(
            {
                "session_active": True,
                "cycle_running": False,
                "status": "waiting",
                "next_cycle_at": next_cycle_at,
                "force_cycle_requested": False,
            }
        )
        return self.save(payload)

    def mark_blocked_by_ai_off(self, *, next_cycle_at: str | None = None) -> dict:
        payload = self.load()
        payload.update(
            {
                "session_active": True,
                "cycle_running": False,
                "status": "blocked_off",
                "next_cycle_at": next_cycle_at,
            }
        )
        return self.save(payload)

    def finish_session(self) -> dict:
        payload = self.load()
        payload.update(
            {
                "session_active": False,
                "cycle_running": False,
                "status": "finished",
                "next_cycle_at": None,
                "session_finished_at": utc_now_iso(),
                "bot_pid": None,
                "launch_pending": False,
            }
        )
        return self.save(payload)

    def set_desired_duration_minutes(self, minutes: int) -> dict:
        payload = self.load()
        payload["desired_session_duration_minutes"] = max(1, int(minutes))
        return self.save(payload)

    def set_bot_process(self, pid: int | None) -> dict:
        payload = self.load()
        payload["bot_pid"] = pid
        return self.save(payload)

    def claim_start_request(self) -> bool:
        payload = self.load()
        if payload.get("launch_pending"):
            return False
        if payload.get("session_active"):
            return False
        pid = payload.get("bot_pid")
        if isinstance(pid, int) and pid > 0 and self.bot_process_running():
            return False
        payload["launch_pending"] = True
        payload["status"] = "launching"
        payload["next_cycle_at"] = None
        self.save(payload)
        return True

    def clear_start_request(self) -> dict:
        payload = self.load()
        payload["launch_pending"] = False
        if not payload.get("session_active") and payload.get("status") == "launching":
            payload["status"] = "idle"
        return self.save(payload)

    def update_crypto_stream_status(
        self,
        *,
        status: str,
        message: str,
        symbol: str | None = None,
        price: float | None = None,
    ) -> dict:
        payload = self.load()
        payload.update(
            {
                "crypto_stream_status": status,
                "crypto_stream_message": message,
                "crypto_stream_symbol": symbol,
                "crypto_stream_price": price,
                "crypto_stream_updated_at": utc_now_iso(),
            }
        )
        return self.save(payload)

    def request_immediate_cycle(self) -> dict:
        payload = self.load()
        payload["force_cycle_requested"] = True
        payload["force_cycle_requested_at"] = utc_now_iso()
        return self.save(payload)

    def consume_immediate_cycle_request(self) -> bool:
        payload = self.load()
        if not payload.get("force_cycle_requested"):
            return False
        payload["force_cycle_requested"] = False
        payload["force_cycle_requested_at"] = None
        self.save(payload)
        return True

    def bot_process_running(self) -> bool:
        payload = self.load()
        pid = payload.get("bot_pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def append_log(self, *, kind: str, title: str, message: str) -> dict:
        payload = self.load()
        logs = list(payload.get("recent_logs", []))
        logs.append(
            {
                "kind": kind,
                "title": title,
                "message": message,
                "created_at": utc_now_iso(),
            }
        )
        payload["recent_logs"] = logs[-40:]
        return self.save(payload)

    @staticmethod
    def _default_state() -> dict:
        return {
            "session_active": False,
            "cycle_running": False,
            "status": "idle",
            "session_started_at": None,
            "session_end_at": None,
            "session_finished_at": None,
            "last_cycle_started_at": None,
            "last_cycle_finished_at": None,
            "next_cycle_at": None,
            "poll_interval_seconds": 0,
            "desired_session_duration_minutes": 15,
            "current_cycle": 0,
            "completed_cycles": 0,
            "bot_pid": None,
            "launch_pending": False,
            "force_cycle_requested": False,
            "force_cycle_requested_at": None,
            "crypto_stream_status": "inactive",
            "crypto_stream_message": "",
            "crypto_stream_symbol": None,
            "crypto_stream_price": None,
            "crypto_stream_updated_at": None,
            "recent_logs": [],
        }
