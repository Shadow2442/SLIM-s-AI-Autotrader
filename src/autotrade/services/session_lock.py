from __future__ import annotations

import json
import os
from pathlib import Path


def _pid_is_running(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class SessionLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def owner(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def owner_pid(self) -> int | None:
        owner = self.owner() or {}
        pid = owner.get("pid")
        if isinstance(pid, int):
            return pid
        return None

    def is_active(self) -> bool:
        pid = self.owner_pid()
        if pid is None:
            return False
        return _pid_is_running(pid)

    def acquire(self, *, pid: int, metadata: dict | None = None) -> bool:
        payload = {"pid": pid, **(metadata or {})}
        for _ in range(2):
            try:
                fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if not self.is_active():
                    self.release(force=True)
                    continue
                return False
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            return True
        return False

    def release(self, *, pid: int | None = None, force: bool = False) -> None:
        if not self._path.exists():
            return
        if force:
            self._path.unlink(missing_ok=True)
            return
        owner_pid = self.owner_pid()
        if pid is not None and owner_pid is not None and pid != owner_pid:
            return
        self._path.unlink(missing_ok=True)
