from datetime import datetime

from luck.backtest import BacktestBroker, bs_delta, bs_price, run_backtest
from luck.config import Config, RiskConfig, StrategyConfig
from luck.strategy import Bar


def test_bs_atm_call_positive_and_below_spot():
    p = bs_price(spot=150, strike=150, t_years=3 / 252, vol=0.9, is_call=True)
    assert 0 < p < 150


def test_bs_intrinsic_at_expiry():
    assert bs_price(160, 150, t_years=0, vol=0.9, is_call=True) == 10
    assert bs_price(140, 150, t_years=0, vol=0.9, is_call=True) == 0


def test_bs_put_call_parity_approx():
    spot, strike, t, vol = 150, 150, 3 / 252, 0.9
    call = bs_price(spot, strike, t, vol, True)
    put = bs_price(spot, strike, t, vol, False)
    # C - P = S - K (r=0); ATM => ~0
    assert abs((call - put) - (spot - strike)) < 1e-6


def test_bs_delta_signs():
    assert 0 < bs_delta(150, 150, 3 / 252, 0.9, True) < 1
    assert -1 < bs_delta(150, 150, 3 / 252, 0.9, False) < 0


def _cfg():
    return Config(
        symbol="SPCX",
        strategy=StrategyConfig(opening_range_minutes=15, breakout_buffer_pct=0.05, max_trades_per_day=4),
        risk=RiskConfig(max_premium_per_trade=5000, max_contracts=5, stop_loss_pct=0.30, take_profit_pct=0.50),
    )


def _trending_up_day():
    """OR high ~151, then a steady climb that should trigger a CALL and run."""
    bars = [
        Bar(datetime(2026, 6, 23, 9, 30), 150.5, 149.5, 150.0),
        Bar(datetime(2026, 6, 23, 9, 35), 151.0, 149.8, 150.7),
        Bar(datetime(2026, 6, 23, 9, 40), 150.9, 149.0, 150.2),
    ]
    price = 151.0
    for m in range(46, 200, 5):  # 9:46 .. ~12:00 climbing
        hh, mm = 9 + (30 + m) // 60, (30 + m) % 60
        price += 0.6
        bars.append(Bar(datetime(2026, 6, 23, hh, mm), price + 0.2, price - 0.2, price))
    return bars


def test_backtest_runs_and_takes_a_trade():
    result = run_backtest([_trending_up_day()], _cfg(), vol=0.9)
    assert result.days == 1
    assert result.trades >= 1
    # A sustained up-move on a CALL should be profitable in this model.
    assert result.total_pnl > 0


def test_backtest_flat_day_no_trade():
    flat = [
        Bar(datetime(2026, 6, 23, 9, 30), 150.2, 149.8, 150.0),
        Bar(datetime(2026, 6, 23, 9, 35), 150.2, 149.8, 150.0),
        Bar(datetime(2026, 6, 23, 9, 40), 150.2, 149.8, 150.0),
        Bar(datetime(2026, 6, 23, 9, 46), 150.1, 149.9, 150.0),
        Bar(datetime(2026, 6, 23, 10, 0), 150.1, 149.9, 150.0),
    ]
    result = run_backtest([flat], _cfg(), vol=0.9)
    assert result.trades == 0
    assert result.total_pnl == 0.0


def test_broker_reprices_with_underlying():
    bars = _trending_up_day()
    broker = BacktestBroker(bars=bars, vol=0.9)
    contract = broker.select_option("SPCX", __import__("luck.strategy", fromlist=["Side"]).Side.CALL, 0.5, "nearest")
    entry_mid = broker.option_price(contract.symbol)
    broker.i = len(bars) - 1  # jump to end of the up-trend
    assert broker.option_price(contract.symbol) > entry_mid
