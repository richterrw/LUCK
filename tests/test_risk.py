from luck.config import RiskConfig
from luck.risk import DailyRiskState, should_exit, size_position


def _cfg(**kw):
    defaults = dict(
        max_premium_per_trade=500, max_contracts=5, stop_loss_pct=0.30,
        take_profit_pct=0.50, daily_loss_limit=750, flatten_minutes_before_close=15,
    )
    defaults.update(kw)
    return RiskConfig(**defaults)


def test_size_within_premium_cap():
    d = size_position(option_ask=1.00, cfg=_cfg())  # $100/contract, cap $500
    assert d.approved
    assert d.contracts == 5  # limited by max_contracts, not premium


def test_size_limited_by_premium():
    d = size_position(option_ask=2.00, cfg=_cfg(max_contracts=10))  # $200/contract
    assert d.approved
    assert d.contracts == 2  # 500 // 200
    assert d.estimated_cost == 400


def test_size_rejects_too_expensive_contract():
    d = size_position(option_ask=6.00, cfg=_cfg())  # $600 > $500 cap
    assert not d.approved
    assert d.contracts == 0


def test_size_rejects_invalid_price():
    assert not size_position(option_ask=0.0, cfg=_cfg()).approved


def test_stop_loss_triggers():
    assert should_exit(entry_price=2.0, current_price=1.39, cfg=_cfg()) == "stop_loss"


def test_take_profit_triggers():
    assert should_exit(entry_price=2.0, current_price=3.01, cfg=_cfg()) == "take_profit"


def test_hold_inside_band():
    assert should_exit(entry_price=2.0, current_price=2.1, cfg=_cfg()) is None


def test_kill_switch_trips_on_daily_loss():
    state = DailyRiskState(_cfg(daily_loss_limit=750))
    state.record_trade(-400)
    ok, _ = state.can_open_new(max_trades_per_day=10)
    assert ok
    state.record_trade(-400)  # cumulative -800 <= -750
    assert state.halted
    ok, reason = state.can_open_new(max_trades_per_day=10)
    assert not ok
    assert "halted" in reason


def test_max_trades_per_day_blocks_new_entry():
    state = DailyRiskState(_cfg())
    for _ in range(4):
        state.record_trade(10)
    ok, reason = state.can_open_new(max_trades_per_day=4)
    assert not ok
    assert "max trades" in reason
