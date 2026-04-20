import json
from pathlib import Path

from autotrade.services.operator_window_state import OperatorWindowStateStore


def test_operator_window_state_recent_after_touch(tmp_path: Path) -> None:
    store = OperatorWindowStateStore(tmp_path / "operator_window_state.json")

    payload = store.touch()

    assert "last_seen_at" in payload
    assert store.is_recent(max_age_seconds=60) is True


def test_operator_window_state_stale_when_old_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "operator_window_state.json"
    path.write_text(json.dumps({"last_seen_at": "2020-01-01T00:00:00+00:00"}), encoding="utf-8")
    store = OperatorWindowStateStore(path)

    assert store.is_recent(max_age_seconds=60) is False
