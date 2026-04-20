import json
from pathlib import Path

from autotrade.services.investment_plan_store import InvestmentPlanStore


def test_investment_plan_store_builds_wallet_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOTRADE_INVESTMENT_PLAN_PATH", "config/investment-plan.paper.example.json")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "investment-plan.paper.example.json").write_text(
        json.dumps(
            {
                "starting_budget": 200.0,
                "cash_reserve_percent": 20.0,
                "crypto_allocation_percent": 75.0,
                "equity_allocation_percent": 25.0,
                "max_symbol_allocation_percent": 40.0,
                "allowed_symbols": ["BTC/USD", "AAPL"],
                "preferred_symbols": ["BTC/USD"],
                "avoided_symbols": [],
                "notes": "test plan",
            }
        ),
        encoding="utf-8",
    )
    store = InvestmentPlanStore(tmp_path)

    summary = store.build_summary(
        dashboard_payload={
            "cash": 999.0,
            "recommendations": [
                {"asset_class": "crypto", "market_value": 70.0},
                {"asset_class": "us_equity", "market_value": 25.0},
            ],
            "open_order_details": [
                {"asset_class": "crypto", "notional_value": 10.0},
                {"asset_class": "us_equity", "notional_value": 5.0},
            ],
        }
    )

    assert summary["wallets"]["crypto_wallet_usd"] == 120.0
    assert summary["wallets"]["equity_wallet_usd"] == 40.0
    assert summary["wallets"]["crypto_committed_usd"] == 80.0
    assert summary["wallets"]["equity_committed_usd"] == 30.0


def test_investment_plan_store_transfer_rebalances_wallets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOTRADE_INVESTMENT_PLAN_PATH", "config/investment-plan.paper.example.json")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "investment-plan.paper.example.json").write_text(
        json.dumps(
            {
                "starting_budget": 200.0,
                "cash_reserve_percent": 20.0,
                "crypto_allocation_percent": 75.0,
                "equity_allocation_percent": 25.0,
                "max_symbol_allocation_percent": 40.0,
                "allowed_symbols": [],
                "preferred_symbols": [],
                "avoided_symbols": [],
                "notes": "test plan",
            }
        ),
        encoding="utf-8",
    )
    store = InvestmentPlanStore(tmp_path)

    updated = store.transfer(from_wallet="cash", to_wallet="crypto", amount=20.0)

    assert updated["cash_reserve_percent"] == 10.0
    assert updated["crypto_allocation_percent"] == 77.78
    assert updated["equity_allocation_percent"] == 22.22
