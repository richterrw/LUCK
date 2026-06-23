"""Pure option-selection logic (delta targeting).

Kept network-free so strike selection can be unit-tested offline. The broker
fetches greeks/quotes and hands them here as `OptionQuote` records.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    strike: float
    delta: float   # signed: calls positive, puts negative
    bid: float
    ask: float


def pick_closest_delta(
    quotes: list[OptionQuote], target_delta: float
) -> OptionQuote | None:
    """Pick the tradable contract whose |delta| is closest to target_delta.

    `target_delta` is a magnitude in (0, 1); a 0.50 target picks the ~ATM strike
    for either calls (delta ~ +0.50) or puts (delta ~ -0.50). Contracts with no
    ask (untradable / no quote) are skipped.
    """
    tradable = [q for q in quotes if q.ask and q.ask > 0]
    if not tradable:
        return None
    return min(tradable, key=lambda q: abs(abs(q.delta) - target_delta))
