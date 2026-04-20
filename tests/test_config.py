import json
import subprocess
from pathlib import Path

from autotrade.config import infer_symbol_asset_class, load_app_config, normalize_symbol, validate_asset_class
from autotrade.main import ensure_operator_server, paper_readiness_events, resolve_session_duration_minutes
from autotrade.services.runtime_state import RuntimeStateStore


def test_environment_overrides_runtime_mode(monkeypatch) -> None:
    root = Path.cwd()
    monkeypatch.setenv("AUTOTRADE_MODE", "dry_run")
    monkeypatch.setenv("AUTOTRADE_DRY_RUN", "true")
    monkeypatch.setenv("AUTOTRADE_ASSET_CLASS", "us_equity")
    monkeypatch.setenv("AUTOTRADE_CRYPTO_LOCATION", "us")
    monkeypatch.setenv("AUTOTRADE_CONFIG_PATH", "config/runtime.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_RISK_PATH", "config/risk.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_STRATEGY_PATH", "config/strategy.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_WATCHLIST_PATH", "config/watchlist.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_INVESTMENT_PLAN_PATH", "config/investment-plan.paper.example.json")

    config = load_app_config(root)

    assert config.runtime.mode == "dry_run"
    assert config.runtime.asset_class == "us_equity"
    assert config.runtime.crypto_location == "us"
    assert config.runtime.dry_run is True
    assert config.strategy.fast_window == 5
    assert config.strategy.breakout_lookback == 10
    assert config.strategy.stop_loss_percent == 3.0
    assert config.investment_plan.starting_budget == 10000.0
    assert config.investment_plan.crypto_allocation_percent == 50.0
    assert config.investment_plan.equity_allocation_percent == 50.0


def test_paper_readiness_blocks_missing_credentials(monkeypatch) -> None:
    root = Path.cwd() / ".pytest_paper_readiness"
    root.mkdir(exist_ok=True)
    config_dir = root / "config"
    config_dir.mkdir(exist_ok=True)
    for name in [
        "runtime.paper.example.json",
        "risk.paper.example.json",
        "strategy.paper.example.json",
        "watchlist.paper.example.json",
        "investment-plan.paper.example.json",
        "event-risk.example.json",
    ]:
        source = Path.cwd() / "config" / name
        (config_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("AUTOTRADE_MODE", "paper")
    monkeypatch.setenv("AUTOTRADE_CONFIG_PATH", "config/runtime.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_RISK_PATH", "config/risk.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_STRATEGY_PATH", "config/strategy.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_WATCHLIST_PATH", "config/watchlist.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_INVESTMENT_PLAN_PATH", "config/investment-plan.paper.example.json")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    config = load_app_config(root)

    events = paper_readiness_events(config)

    assert any(event.event_type == "paper_readiness_blocker" for event in events)


def test_load_app_config_reads_local_env_file(tmp_path: Path, monkeypatch) -> None:
    for name in [
        "AUTOTRADE_MODE",
        "AUTOTRADE_DRY_RUN",
        "AUTOTRADE_CONFIG_PATH",
        "AUTOTRADE_ASSET_CLASS",
        "AUTOTRADE_CRYPTO_LOCATION",
        "AUTOTRADE_RISK_PATH",
        "AUTOTRADE_STRATEGY_PATH",
        "AUTOTRADE_WATCHLIST_PATH",
        "AUTOTRADE_INVESTMENT_PLAN_PATH",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
    ]:
        monkeypatch.delenv(name, raising=False)

    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "AUTOTRADE_MODE=paper",
                "AUTOTRADE_ASSET_CLASS=crypto",
                "AUTOTRADE_CRYPTO_LOCATION=us",
                "AUTOTRADE_CONFIG_PATH=config/runtime.paper.example.json",
                "AUTOTRADE_RISK_PATH=config/risk.paper.example.json",
                "AUTOTRADE_STRATEGY_PATH=config/strategy.paper.example.json",
                "AUTOTRADE_WATCHLIST_PATH=config/watchlist.paper.example.json",
                "AUTOTRADE_INVESTMENT_PLAN_PATH=config/investment-plan.paper.example.json",
                "ALPACA_API_KEY=test_key",
                "ALPACA_API_SECRET=test_secret",
            ]
        ),
        encoding="utf-8",
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in [
        "runtime.paper.example.json",
        "risk.paper.example.json",
        "strategy.paper.example.json",
        "watchlist.paper.example.json",
        "investment-plan.paper.example.json",
        "event-risk.example.json",
    ]:
        source = Path.cwd() / "config" / name
        (config_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    config = load_app_config(tmp_path)

    assert config.runtime.mode == "paper"
    assert config.runtime.asset_class == "crypto"
    assert config.runtime.crypto_location == "us"
    assert config.api_key == "test_key"
    assert config.api_secret == "test_secret"


def test_ensure_operator_server_uses_hidden_windows_process(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    monkeypatch.setattr("autotrade.main.is_port_open", lambda host, port: False)

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

        class DummyProcess:
            pass

        return DummyProcess()

    monkeypatch.setattr("autotrade.main.subprocess.Popen", fake_popen)

    url, started = ensure_operator_server(reports_dir=tmp_path, port=8765)

    assert started is True
    assert url == "http://127.0.0.1:8765/operator"
    assert captured["kwargs"]["stdout"] is not None
    assert captured["kwargs"]["stderr"] is not None
    assert captured["kwargs"]["startupinfo"] is not None
    assert (
        captured["kwargs"]["creationflags"] & getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ) == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_ensure_operator_server_respects_existing_server_lock(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("autotrade.main.is_port_open", lambda host, port: False)
    (tmp_path / "operator_server.lock").write_text(
        '{"entrypoint":"autotrade.operator_server","pid":999}',
        encoding="utf-8",
    )
    monkeypatch.setattr("autotrade.services.session_lock._pid_is_running", lambda pid: pid == 999)

    def fake_popen(*args, **kwargs):
        raise AssertionError("Popen should not be called when operator server lock is active")

    monkeypatch.setattr("autotrade.main.subprocess.Popen", fake_popen)

    url, started = ensure_operator_server(reports_dir=tmp_path, port=8765)

    assert started is False
    assert url == "http://127.0.0.1:8765/operator"


def test_validate_asset_class_accepts_mixed() -> None:
    validate_asset_class("mixed")


def test_normalize_symbol_formats_crypto_pairs() -> None:
    assert normalize_symbol("solusd", "crypto") == "SOL/USD"
    assert normalize_symbol("BTC/USD", "crypto") == "BTC/USD"
    assert infer_symbol_asset_class("SOLUSD") == "crypto"


def test_load_app_config_backfills_stash_defaults(tmp_path: Path, monkeypatch) -> None:
    for name in [
        "AUTOTRADE_MODE",
        "AUTOTRADE_DRY_RUN",
        "AUTOTRADE_CONFIG_PATH",
        "AUTOTRADE_ASSET_CLASS",
        "AUTOTRADE_CRYPTO_LOCATION",
        "AUTOTRADE_RISK_PATH",
        "AUTOTRADE_STRATEGY_PATH",
        "AUTOTRADE_WATCHLIST_PATH",
        "AUTOTRADE_INVESTMENT_PLAN_PATH",
        "ALPACA_API_KEY",
        "ALPACA_API_SECRET",
    ]:
        monkeypatch.delenv(name, raising=False)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in [
        "runtime.paper.example.json",
        "risk.paper.example.json",
        "strategy.paper.example.json",
        "watchlist.paper.example.json",
        "event-risk.example.json",
    ]:
        source = Path.cwd() / "config" / name
        (config_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    legacy_plan = {
        "starting_budget": 50.0,
        "cash_reserve_percent": 10.0,
        "max_symbol_allocation_percent": 25.0,
        "allowed_symbols": ["BTC/USD"],
        "preferred_symbols": ["BTC/USD"],
        "avoided_symbols": [],
        "notes": "legacy plan",
    }
    (config_dir / "investment-plan.legacy.json").write_text(
        json.dumps(legacy_plan),
        encoding="utf-8",
    )

    monkeypatch.setenv("AUTOTRADE_CONFIG_PATH", "config/runtime.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_RISK_PATH", "config/risk.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_STRATEGY_PATH", "config/strategy.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_WATCHLIST_PATH", "config/watchlist.paper.example.json")
    monkeypatch.setenv("AUTOTRADE_INVESTMENT_PLAN_PATH", "config/investment-plan.legacy.json")

    config = load_app_config(tmp_path)

    assert config.investment_plan.crypto_allocation_percent == 50.0
    assert config.investment_plan.equity_allocation_percent == 50.0


def test_resolve_session_duration_prefers_runtime_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AUTOTRADE_SESSION_DURATION_MINUTES", raising=False)
    store = RuntimeStateStore(tmp_path / "runtime_state.json")
    store.set_desired_duration_minutes(240)
    config = load_app_config(Path.cwd())

    minutes = resolve_session_duration_minutes(config, store)

    assert minutes == 240


def test_resolve_session_duration_prefers_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOTRADE_SESSION_DURATION_MINUTES", "180")
    store = RuntimeStateStore(tmp_path / "runtime_state.json")
    store.set_desired_duration_minutes(240)
    config = load_app_config(Path.cwd())

    minutes = resolve_session_duration_minutes(config, store)

    assert minutes == 180
