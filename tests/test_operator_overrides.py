from pathlib import Path

from autotrade.services.operator_overrides import OperatorOverrideStore


def test_operator_override_store_round_trip(tmp_path: Path) -> None:
    store = OperatorOverrideStore(tmp_path / "operator_overrides.json")

    store.set_override("AAPL", "buy")
    store.set_bulk_override(["MSFT", "SPY"], "pause_auto")
    payload = store.load()

    assert payload["AAPL"]["action"] == "buy"
    assert payload["MSFT"]["action"] == "pause_auto"
    assert payload["SPY"]["action"] == "pause_auto"


def test_operator_override_store_clear(tmp_path: Path) -> None:
    store = OperatorOverrideStore(tmp_path / "operator_overrides.json")

    store.set_override("QQQ", "sell")
    store.clear()

    assert store.load() == {}


def test_operator_override_store_ai_trading_master_switch(tmp_path: Path) -> None:
    store = OperatorOverrideStore(tmp_path / "operator_overrides.json")

    assert store.ai_trading_enabled() is True
    store.set_ai_trading_enabled(False)

    assert store.ai_trading_enabled() is False


def test_operator_override_store_normalizes_crypto_symbols(tmp_path: Path) -> None:
    store = OperatorOverrideStore(tmp_path / "operator_overrides.json")

    store.set_override("solusd", "buy")
    payload = store.load()

    assert payload["SOL/USD"]["action"] == "buy"


def test_operator_override_store_can_clear_single_symbol(tmp_path: Path) -> None:
    store = OperatorOverrideStore(tmp_path / "operator_overrides.json")

    store.set_override("AAPL", "buy")
    store.set_override("MSFT", "sell")
    store.clear_override("AAPL")
    payload = store.load()

    assert "AAPL" not in payload
    assert payload["MSFT"]["action"] == "sell"
