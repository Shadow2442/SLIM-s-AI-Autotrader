from __future__ import annotations

import json
import os
from pathlib import Path


class InvestmentPlanStore:
    _DEFAULTS = {
        "starting_budget": 200.0,
        "cash_reserve_percent": 20.0,
        "crypto_allocation_percent": 50.0,
        "equity_allocation_percent": 50.0,
        "max_symbol_allocation_percent": 40.0,
        "allowed_symbols": [],
        "preferred_symbols": [],
        "avoided_symbols": [],
        "notes": "",
    }
    _WALLETS = {"cash", "crypto", "equity"}

    def __init__(self, workspace_dir: Path) -> None:
        self._workspace_dir = workspace_dir
        relative_path = os.getenv(
            "AUTOTRADE_INVESTMENT_PLAN_PATH",
            "config/investment-plan.paper.example.json",
        )
        self._path = workspace_dir / relative_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self._path.exists():
            return dict(self._DEFAULTS)
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return dict(self._DEFAULTS | payload)

    def save(self, payload: dict) -> dict:
        merged = dict(self._DEFAULTS | payload)
        self._path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        return merged

    def update_plan(
        self,
        *,
        starting_budget: float,
        cash_reserve_percent: float,
        crypto_allocation_percent: float,
        equity_allocation_percent: float,
    ) -> dict:
        current = self.load()
        starting_budget = max(1.0, float(starting_budget))
        cash_reserve_percent = max(0.0, min(100.0, float(cash_reserve_percent)))
        crypto_allocation_percent = max(0.0, float(crypto_allocation_percent))
        equity_allocation_percent = max(0.0, float(equity_allocation_percent))
        allocation_total = crypto_allocation_percent + equity_allocation_percent
        if allocation_total <= 0:
            crypto_allocation_percent = 50.0
            equity_allocation_percent = 50.0
        else:
            crypto_allocation_percent = (crypto_allocation_percent / allocation_total) * 100.0
            equity_allocation_percent = 100.0 - crypto_allocation_percent

        current.update(
            {
                "starting_budget": round(starting_budget, 2),
                "cash_reserve_percent": round(cash_reserve_percent, 2),
                "crypto_allocation_percent": round(crypto_allocation_percent, 2),
                "equity_allocation_percent": round(equity_allocation_percent, 2),
            }
        )
        return self.save(current)

    def transfer(self, *, from_wallet: str, to_wallet: str, amount: float) -> dict:
        from_wallet = str(from_wallet).strip().lower()
        to_wallet = str(to_wallet).strip().lower()
        if from_wallet not in self._WALLETS or to_wallet not in self._WALLETS or from_wallet == to_wallet:
            raise ValueError("Invalid wallet transfer selection.")
        amount = max(0.0, float(amount))
        plan = self.load()
        wallets = self.wallet_amounts(plan)
        available = wallets[f"{from_wallet}_wallet_usd"]
        move_amount = min(amount, available)
        wallets[f"{from_wallet}_wallet_usd"] -= move_amount
        wallets[f"{to_wallet}_wallet_usd"] += move_amount
        return self._plan_from_wallets(plan=plan, wallets=wallets)

    def wallet_amounts(self, plan: dict | None = None) -> dict:
        active = self.load() if plan is None else dict(self._DEFAULTS | plan)
        total = max(1.0, float(active["starting_budget"]))
        cash_wallet = total * (float(active["cash_reserve_percent"]) / 100.0)
        deployable = max(0.0, total - cash_wallet)
        crypto_wallet = deployable * (float(active["crypto_allocation_percent"]) / 100.0)
        equity_wallet = max(0.0, deployable - crypto_wallet)
        return {
            "starting_budget_usd": round(total, 2),
            "cash_wallet_usd": round(cash_wallet, 2),
            "deployable_usd": round(deployable, 2),
            "crypto_wallet_usd": round(crypto_wallet, 2),
            "equity_wallet_usd": round(equity_wallet, 2),
        }

    def build_summary(self, *, dashboard_payload: dict | None = None) -> dict:
        plan = self.load()
        wallets = self.wallet_amounts(plan)
        recommendations = list((dashboard_payload or {}).get("recommendations", []))
        open_order_details = list((dashboard_payload or {}).get("open_order_details", []))

        crypto_invested = sum(
            float(item.get("market_value", 0.0))
            for item in recommendations
            if str(item.get("asset_class")) == "crypto"
        )
        equity_invested = sum(
            float(item.get("market_value", 0.0))
            for item in recommendations
            if str(item.get("asset_class")) != "crypto"
        )
        crypto_pending = sum(
            float(item.get("notional_value", 0.0))
            for item in open_order_details
            if str(item.get("asset_class")) == "crypto"
        )
        equity_pending = sum(
            float(item.get("notional_value", 0.0))
            for item in open_order_details
            if str(item.get("asset_class")) != "crypto"
        )

        crypto_committed = crypto_invested + crypto_pending
        equity_committed = equity_invested + equity_pending
        return {
            "plan": plan,
            "wallets": {
                **wallets,
                "broker_cash_usd": round(float((dashboard_payload or {}).get("cash", 0.0)), 2),
                "crypto_invested_usd": round(crypto_invested, 2),
                "equity_invested_usd": round(equity_invested, 2),
                "crypto_pending_usd": round(crypto_pending, 2),
                "equity_pending_usd": round(equity_pending, 2),
                "crypto_committed_usd": round(crypto_committed, 2),
                "equity_committed_usd": round(equity_committed, 2),
                "crypto_available_usd": round(max(0.0, wallets["crypto_wallet_usd"] - crypto_committed), 2),
                "equity_available_usd": round(max(0.0, wallets["equity_wallet_usd"] - equity_committed), 2),
                "cash_available_to_move_usd": round(wallets["cash_wallet_usd"], 2),
            },
        }

    def _plan_from_wallets(self, *, plan: dict, wallets: dict) -> dict:
        total = max(1.0, float(wallets["starting_budget_usd"]))
        cash_wallet = max(0.0, min(total, float(wallets["cash_wallet_usd"])))
        remaining = max(0.0, total - cash_wallet)
        crypto_wallet = max(0.0, min(remaining, float(wallets["crypto_wallet_usd"])))
        equity_wallet = max(0.0, remaining - crypto_wallet)
        reserve_percent = (cash_wallet / total) * 100.0
        if remaining <= 0:
            crypto_percent = 50.0
            equity_percent = 50.0
        else:
            crypto_percent = (crypto_wallet / remaining) * 100.0
            equity_percent = 100.0 - crypto_percent

        updated = dict(plan)
        updated["cash_reserve_percent"] = round(reserve_percent, 2)
        updated["crypto_allocation_percent"] = round(crypto_percent, 2)
        updated["equity_allocation_percent"] = round(equity_percent, 2)
        return self.save(updated)
