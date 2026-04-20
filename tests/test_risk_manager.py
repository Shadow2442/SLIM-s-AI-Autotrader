from autotrade.config import RiskConfig
from autotrade.models import AccountSnapshot, PositionSnapshot, Signal
from autotrade.risk.manager import RiskManager


def make_config() -> RiskConfig:
    return RiskConfig(
        max_notional_per_trade=25.0,
        max_open_positions=2,
        max_trades_per_session=3,
        max_daily_loss=50.0,
        allow_fractional=True,
        allowed_order_types=["market", "limit"],
    )


def test_blocks_when_kill_switch_enabled() -> None:
    manager = RiskManager(make_config())
    decision = manager.evaluate(
        Signal(symbol="SPY", action="BUY", confidence=0.6, reason="test", notional=10.0),
        account=AccountSnapshot(equity=1000.0, buying_power=1000.0, cash=1000.0),
        open_positions=[],
        kill_switch=True,
    )
    assert not decision.approved


def test_blocks_when_exceeding_position_limit() -> None:
    manager = RiskManager(make_config())
    decision = manager.evaluate(
        Signal(symbol="SPY", action="BUY", confidence=0.6, reason="test", notional=10.0),
        account=AccountSnapshot(equity=1000.0, buying_power=1000.0, cash=1000.0),
        open_positions=[
            PositionSnapshot(symbol="AAPL", quantity=1, market_value=100),
            PositionSnapshot(symbol="MSFT", quantity=1, market_value=100),
        ],
        kill_switch=False,
    )
    assert not decision.approved


def test_approves_small_trade_with_buying_power() -> None:
    manager = RiskManager(make_config())
    decision = manager.evaluate(
        Signal(symbol="SPY", action="BUY", confidence=0.6, reason="test", notional=10.0),
        account=AccountSnapshot(equity=1000.0, buying_power=1000.0, cash=1000.0),
        open_positions=[],
        kill_switch=False,
    )
    assert decision.approved
