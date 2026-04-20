from pathlib import Path

from autotrade.services.session_lock import SessionLock


def test_session_lock_acquire_and_release(tmp_path: Path) -> None:
    lock = SessionLock(tmp_path / "session.lock")

    assert lock.acquire(pid=111, metadata={"entrypoint": "test"}) is True
    assert lock.owner_pid() == 111

    lock.release(pid=111)
    assert lock.owner() is None


def test_session_lock_blocks_active_owner(tmp_path: Path, monkeypatch) -> None:
    lock = SessionLock(tmp_path / "session.lock")
    assert lock.acquire(pid=222) is True

    monkeypatch.setattr("autotrade.services.session_lock._pid_is_running", lambda pid: pid == 222)

    assert lock.acquire(pid=333) is False
    assert lock.owner_pid() == 222


def test_session_lock_reclaims_stale_owner(tmp_path: Path, monkeypatch) -> None:
    lock = SessionLock(tmp_path / "session.lock")
    assert lock.acquire(pid=444) is True

    monkeypatch.setattr("autotrade.services.session_lock._pid_is_running", lambda pid: False)

    assert lock.acquire(pid=555) is True
    assert lock.owner_pid() == 555
