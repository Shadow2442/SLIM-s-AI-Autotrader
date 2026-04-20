from pathlib import Path

from autotrade.services.logging import StructuredLogger
from autotrade.services.runtime_state import RuntimeStateStore
from autotrade.main import record_refresh_blocked


def test_record_refresh_blocked_logs_and_updates_runtime_state(tmp_path: Path) -> None:
    runtime_state_store = RuntimeStateStore(tmp_path / "runtime_state.json")
    logger = StructuredLogger(tmp_path / "runtime.jsonl")

    event = record_refresh_blocked(
        runtime_state_store=runtime_state_store,
        logger=logger,
        failed_stage="startup_refresh",
    )

    assert event.event_type == "monitor_refresh_blocked"
    assert event.details["failed_stage"] == "startup_refresh"
    assert runtime_state_store.load()["recent_logs"][-1]["title"] == "Monitor refresh blocked"

    log_lines = (tmp_path / "runtime.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    assert '"event_type": "monitor_refresh_blocked"' in log_lines[0]
