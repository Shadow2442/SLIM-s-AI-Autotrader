from pathlib import Path

from autotrade.services.runtime_state import RuntimeStateStore


def test_runtime_state_store_tracks_session_and_logs(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime_state.json")

    state = store.start_session(duration_minutes=15, poll_interval_seconds=300)
    assert state["session_active"] is True
    assert state["status"] == "starting"

    state = store.mark_cycle_started(cycle_number=1)
    assert state["cycle_running"] is True
    assert state["status"] == "running"

    state = store.append_log(kind="warning", title="User stopped next run", message="Next run will be blocked.")
    assert state["recent_logs"][-1]["title"] == "User stopped next run"

    state = store.set_desired_duration_minutes(22)
    assert state["desired_session_duration_minutes"] == 22

    state = store.request_immediate_cycle()
    assert state["force_cycle_requested"] is True
    assert store.consume_immediate_cycle_request() is True
    assert store.consume_immediate_cycle_request() is False

    state = store.mark_blocked_by_ai_off(next_cycle_at="2026-04-16T21:00:00+00:00")
    assert state["status"] == "blocked_off"

    state = store.finish_session()
    assert state["session_active"] is False
    assert state["cycle_running"] is False
    assert state["bot_pid"] is None
    assert state["status"] == "finished"


def test_runtime_state_claim_start_request_blocks_duplicates(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime_state.json")

    assert store.claim_start_request() is True
    assert store.claim_start_request() is False

    state = store.clear_start_request()
    assert state["launch_pending"] is False
    assert store.claim_start_request() is True


def test_runtime_state_start_session_clears_stale_logs_and_cycle_timestamps(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path / "runtime_state.json")

    store.append_log(kind="warning", title="Old warning", message="should be cleared")
    state = store.mark_cycle_started(cycle_number=3)
    assert state["last_cycle_started_at"] is not None
    state = store.mark_cycle_finished(cycle_number=3, next_cycle_at="2026-04-20T05:00:00+00:00")
    assert state["last_cycle_finished_at"] is not None

    restarted = store.start_session(duration_minutes=240, poll_interval_seconds=30, bot_pid=12345)

    assert restarted["recent_logs"] == []
    assert restarted["last_cycle_started_at"] is None
    assert restarted["last_cycle_finished_at"] is None
    assert restarted["session_finished_at"] is None
    assert restarted["current_cycle"] == 0
    assert restarted["completed_cycles"] == 0
    assert restarted["desired_session_duration_minutes"] == 240
    assert restarted["bot_pid"] == 12345
