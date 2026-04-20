from pathlib import Path

from autotrade.services.crypto_stream import CryptoStreamWatcher
from autotrade.services.operator_overrides import OperatorOverrideStore
from autotrade.services.runtime_state import RuntimeStateStore


def test_crypto_stream_reconnect_warning_is_rate_limited(tmp_path: Path) -> None:
    watcher = CryptoStreamWatcher(
        symbols=["BTC/USD"],
        api_key="key",
        api_secret="secret",
        location="us",
        cooldown_seconds=5,
        runtime_state_store=RuntimeStateStore(tmp_path / "runtime_state.json"),
        override_store=OperatorOverrideStore(tmp_path / "operator_overrides.json"),
    )

    assert watcher._should_log_reconnect_warning() is True  # noqa: SLF001
    assert watcher._should_log_reconnect_warning() is False  # noqa: SLF001

    watcher._last_reconnect_log_at -= 31.0  # noqa: SLF001

    assert watcher._should_log_reconnect_warning() is True  # noqa: SLF001
