from datetime import datetime

from luck.strategy import Bar, Side, compute_opening_range, generate_signal


def _bar(hour, minute, high, low, close):
    return Bar(ts=datetime(2026, 6, 23, hour, minute), high=high, low=low, close=close)


def _opening_range_bars():
    # 9:30-9:44 form a 15-min opening range high=151, low=149.
    return [
        _bar(9, 30, 150.5, 149.5, 150.0),
        _bar(9, 35, 151.0, 149.8, 150.7),
        _bar(9, 40, 150.9, 149.0, 150.2),
    ]


def test_opening_range_incomplete_without_post_window_bar():
    rng = compute_opening_range(_opening_range_bars(), minutes=15)
    assert not rng.complete


def test_opening_range_high_low():
    bars = _opening_range_bars() + [_bar(9, 46, 151.2, 150.8, 151.1)]
    rng = compute_opening_range(bars, minutes=15)
    assert rng.complete
    assert rng.high == 151.0
    assert rng.low == 149.0


def test_call_signal_on_upside_breakout():
    bars = _opening_range_bars() + [_bar(9, 46, 152.0, 151.5, 151.9)]
    sig = generate_signal(bars, opening_range_minutes=15, breakout_buffer_pct=0.05)
    assert sig is not None
    assert sig.side == Side.CALL


def test_put_signal_on_downside_breakout():
    bars = _opening_range_bars() + [_bar(9, 46, 149.0, 148.0, 148.2)]
    sig = generate_signal(bars, opening_range_minutes=15, breakout_buffer_pct=0.05)
    assert sig is not None
    assert sig.side == Side.PUT


def test_no_signal_inside_range():
    bars = _opening_range_bars() + [_bar(9, 46, 150.5, 150.0, 150.3)]
    sig = generate_signal(bars, opening_range_minutes=15, breakout_buffer_pct=0.05)
    assert sig is None


def test_buffer_blocks_marginal_break():
    # Close 151.05 is above OR high 151.0 but inside a 0.1% buffer (151.151).
    bars = _opening_range_bars() + [_bar(9, 46, 151.1, 150.9, 151.05)]
    sig = generate_signal(bars, opening_range_minutes=15, breakout_buffer_pct=0.1)
    assert sig is None
