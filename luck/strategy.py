"""Opening-Range Breakout (ORB) signal generation.

Pure, network-free logic so it can be unit-tested offline. The agent feeds it
the day's price history; it returns a directional signal (or none).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class Side(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True)
class Bar:
    """A single price observation for the underlying."""
    ts: datetime
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class OpeningRange:
    high: float
    low: float
    complete: bool


@dataclass(frozen=True)
class Signal:
    side: Side
    reference_price: float   # the breakout level that triggered
    underlying_price: float  # the price that broke it
    reason: str


# Regular US equity/options session open (Eastern). The agent is expected to
# pass timestamps already normalized to US/Eastern.
MARKET_OPEN = time(9, 30)


def compute_opening_range(bars: list[Bar], minutes: int) -> OpeningRange:
    """High/low of the first `minutes` after the open.

    `complete` is True once at least one bar exists past the window, meaning the
    range is settled and breakouts may be evaluated.
    """
    if not bars:
        return OpeningRange(high=0.0, low=0.0, complete=False)

    open_day = bars[0].ts.date()
    window_bars: list[Bar] = []
    has_post_window_bar = False
    for bar in bars:
        if bar.ts.date() != open_day:
            continue
        minutes_since_open = (
            bar.ts.hour * 60 + bar.ts.minute
        ) - (MARKET_OPEN.hour * 60 + MARKET_OPEN.minute)
        if 0 <= minutes_since_open < minutes:
            window_bars.append(bar)
        elif minutes_since_open >= minutes:
            has_post_window_bar = True

    if not window_bars:
        return OpeningRange(high=0.0, low=0.0, complete=False)

    return OpeningRange(
        high=max(b.high for b in window_bars),
        low=min(b.low for b in window_bars),
        complete=has_post_window_bar,
    )


def generate_signal(
    bars: list[Bar],
    opening_range_minutes: int,
    breakout_buffer_pct: float,
) -> Signal | None:
    """Return a breakout signal, or None if no actionable setup exists.

    - A close above the opening-range high (plus buffer) -> buy CALLs.
    - A close below the opening-range low (minus buffer)  -> buy PUTs.
    The buffer (as a fraction, e.g. 0.05 == 0.05%) filters out marginal pokes
    through the level.
    """
    rng = compute_opening_range(bars, opening_range_minutes)
    if not rng.complete or not bars:
        return None

    last = bars[-1].close
    buffer = breakout_buffer_pct / 100.0

    up_trigger = rng.high * (1 + buffer)
    down_trigger = rng.low * (1 - buffer)

    if last > up_trigger:
        return Signal(
            side=Side.CALL,
            reference_price=rng.high,
            underlying_price=last,
            reason=f"close {last:.2f} broke OR high {rng.high:.2f} (+{breakout_buffer_pct}%)",
        )
    if last < down_trigger:
        return Signal(
            side=Side.PUT,
            reference_price=rng.low,
            underlying_price=last,
            reason=f"close {last:.2f} broke OR low {rng.low:.2f} (-{breakout_buffer_pct}%)",
        )
    return None
