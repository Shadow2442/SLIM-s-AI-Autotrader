from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperatorWindowStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def touch(self) -> dict:
        payload = {"last_seen_at": utc_now().isoformat()}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8-sig"))

    def is_recent(self, *, max_age_seconds: int = 45) -> bool:
        payload = self.load()
        last_seen_at = payload.get("last_seen_at")
        if not last_seen_at:
            return False
        try:
            last_seen = datetime.fromisoformat(str(last_seen_at))
        except ValueError:
            return False
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        return last_seen >= utc_now() - timedelta(seconds=max_age_seconds)
