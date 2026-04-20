import json
from pathlib import Path

from autotrade.models import RunEvent
from autotrade.services.logging import StructuredLogger


def test_structured_logger_writes_json_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "runtime.jsonl"
    logger = StructuredLogger(log_path)

    logger.write_event(RunEvent(event_type="test", message="hello", details={"ok": True}))

    content = log_path.read_text(encoding="utf-8").strip()
    payload = json.loads(content)
    assert payload["event_type"] == "test"
    assert payload["details"]["ok"] is True
