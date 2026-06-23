"""Backtest harness for the ORB options strategy.

Design: a `BacktestBroker` implements the same `Broker` interface the live
agent uses and prices options with Black-Scholes, so the backtest runs the
*real* `Agent` (same signal, risk, exits, EOD flatten). Only option pricing is
modeled — there is no historical options data dependency.

Caveats (read before trusting results):
- Option prices are modeled (constant IV Black-Scholes), not real fills.
- A flat per-side spread is charged; real spreads on a new, volatile listing
  can be wider and move around.
- No slippage/queue modeling beyond the spread. Treat output as a sanity check
  on the strategy's logic and parameters, not a P&L promise.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from datetime import datetime

from .agent import Agent
from .broker import OptionContract, Position
from .config import Config, load_config
from .strategy import Bar, Side

TRADING_MINUTES_PER_YEAR = 252 * 390
MARKET_OPEN_MIN = 9 * 60 + 30   # 09:30
MARKET_CLOSE_MIN = 16 * 60      # 16:00


# --------------------------------------------------------------------------- #
# Black-Scholes (r=0), pure
# --------------------------------------------------------------------------- #
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, vol: float, is_call: bool) -> float:
    """Black-Scholes price with zero rates. Returns intrinsic at/after expiry."""
    if t_years <= 0 or vol <= 0 or spot <= 0:
        intrinsic = (spot - strike) if is_call else (strike - spot)
        return max(0.0, intrinsic)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    if is_call:
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_delta(spot: float, strike: float, t_years: float, vol: float, is_call: bool) -> float:
    if t_years <= 0 or vol <= 0 or spot <= 0:
        return float(is_call)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * t_years) / (vol * sqrt_t)
    return _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0


def _minute_of_day(ts: datetime) -> int:
    return ts.hour * 60 + ts.minute


# --------------------------------------------------------------------------- #
# Backtest broker (one trading day)
# --------------------------------------------------------------------------- #
@dataclass
class _OptionState:
    strike: float
    is_call: bool


@dataclass
class BacktestBroker:
    """Drives a single day's bars and prices options via Black-Scholes."""

    bars: list[Bar]
    vol: float = 0.90                 # annualized IV assumption (volatile listing)
    trading_days_to_expiry: int = 3   # e.g. enter Tue, Fri-expiry weekly
    half_spread_pct: float = 0.01     # per-side spread on the modeled mid
    strike_increment: float = 2.5
    i: int = 0                        # current bar cursor
    _options: dict[str, _OptionState] = field(default_factory=dict)
    trade_pnls: list[float] = field(default_factory=list)

    # --- driving ---------------------------------------------------------- #
    def advance(self) -> bool:
        if self.i < len(self.bars) - 1:
            self.i += 1
            return True
        return False

    @property
    def _now(self) -> Bar:
        return self.bars[self.i]

    def _t_years(self) -> float:
        elapsed = max(0, _minute_of_day(self._now.ts) - MARKET_OPEN_MIN)
        remaining = self.trading_days_to_expiry * 390 - elapsed
        return max(remaining, 0.0) / TRADING_MINUTES_PER_YEAR

    # --- Broker interface ------------------------------------------------- #
    def get_underlying_bars(self, symbol: str) -> list[Bar]:
        return self.bars[: self.i + 1]

    def is_market_open(self) -> bool:
        return self.i < len(self.bars)

    def minutes_to_close(self) -> float:
        return float(MARKET_CLOSE_MIN - _minute_of_day(self._now.ts))

    def select_option(self, underlying, side, target_delta, expiry):
        spot = self._now.close
        is_call = side == Side.CALL
        strike = round(spot / self.strike_increment) * self.strike_increment
        symbol = f"{underlying}{self._now.ts:%y%m%d}{'C' if is_call else 'P'}{int(strike*1000):08d}"
        self._options[symbol] = _OptionState(strike=strike, is_call=is_call)
        mid = bs_price(spot, strike, self._t_years(), self.vol, is_call)
        delta = bs_delta(spot, strike, self._t_years(), self.vol, is_call)
        return OptionContract(
            symbol=symbol, strike=strike, expiry=str(self._now.ts.date()), side=side,
            ask=mid * (1 + self.half_spread_pct), bid=mid * (1 - self.half_spread_pct),
            delta=delta,
        )

    def option_price(self, symbol: str) -> float:
        opt = self._options[symbol]
        return bs_price(self._now.close, opt.strike, self._t_years(), self.vol, opt.is_call)

    def buy_to_open(self, contract, contracts):
        return Position(symbol=contract.symbol, side=contract.side, contracts=contracts,
                        entry_price=contract.ask, opened_at=self._now.ts)

    def sell_to_close(self, position):
        exit_price = self.option_price(position.symbol)
        pnl = (exit_price - position.entry_price) * position.contracts * 100
        self.trade_pnls.append(pnl)
        return pnl


# --------------------------------------------------------------------------- #
# Runner + results
# --------------------------------------------------------------------------- #
@dataclass
class BacktestResult:
    days: int = 0
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    daily_pnls: list[float] = field(default_factory=list)
    trade_pnls: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def avg_trade(self) -> float:
        return self.total_pnl / self.trades if self.trades else 0.0

    @property
    def best_day(self) -> float:
        return max(self.daily_pnls) if self.daily_pnls else 0.0

    @property
    def worst_day(self) -> float:
        return min(self.daily_pnls) if self.daily_pnls else 0.0

    @property
    def max_drawdown(self) -> float:
        """Largest peak-to-trough drop of the cumulative daily equity curve."""
        peak = 0.0
        equity = 0.0
        dd = 0.0
        for p in self.daily_pnls:
            equity += p
            peak = max(peak, equity)
            dd = min(dd, equity - peak)
        return dd

    def summary(self) -> str:
        return (
            "Backtest results\n"
            f"  days traded     : {self.days}\n"
            f"  trades          : {self.trades}\n"
            f"  win rate        : {self.win_rate:.0%}\n"
            f"  total P&L       : ${self.total_pnl:,.2f}\n"
            f"  avg / trade     : ${self.avg_trade:,.2f}\n"
            f"  best / worst day: ${self.best_day:,.2f} / ${self.worst_day:,.2f}\n"
            f"  max drawdown    : ${self.max_drawdown:,.2f}"
        )


def run_backtest(
    days: list[list[Bar]],
    cfg: Config,
    vol: float = 0.90,
    trading_days_to_expiry: int = 3,
    half_spread_pct: float = 0.01,
) -> BacktestResult:
    """Run the real Agent over each day's bars with a Black-Scholes broker."""
    result = BacktestResult()
    for day_bars in days:
        if not day_bars:
            continue
        broker = BacktestBroker(
            bars=day_bars, vol=vol, trading_days_to_expiry=trading_days_to_expiry,
            half_spread_pct=half_spread_pct,
        )
        agent = Agent(broker, cfg)
        agent.step()                    # evaluate first bar
        while broker.advance():
            agent.step()
        # Ensure nothing is left open at the synthetic day's end.
        agent._flatten_all("backtest_eod")

        day_pnl = sum(broker.trade_pnls)
        result.days += 1
        result.daily_pnls.append(day_pnl)
        result.total_pnl += day_pnl
        for p in broker.trade_pnls:
            result.trades += 1
            result.trade_pnls.append(p)
            if p > 0:
                result.wins += 1
    return result


# --------------------------------------------------------------------------- #
# CSV loading + CLI
# --------------------------------------------------------------------------- #
def load_bars_csv(path: str) -> list[list[Bar]]:
    """Load minute bars from CSV (header: timestamp,high,low,close), grouped by date.

    `timestamp` must be ISO-8601 in market (Eastern) wall-clock time.
    """
    import csv

    by_date: dict = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            ts = datetime.fromisoformat(row["timestamp"])
            bar = Bar(ts=ts, high=float(row["high"]), low=float(row["low"]),
                      close=float(row["close"]))
            by_date.setdefault(ts.date(), []).append(bar)
    return [sorted(b, key=lambda x: x.ts) for _, b in sorted(by_date.items())]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the SPCX ORB options strategy")
    parser.add_argument("--data", required=True, help="CSV: timestamp,high,low,close (ET)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--iv", type=float, default=0.90, help="annualized implied vol assumption")
    parser.add_argument("--dte", type=int, default=3, help="trading days to option expiry")
    parser.add_argument("--spread", type=float, default=0.01, help="per-side spread fraction")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    days = load_bars_csv(args.data)
    result = run_backtest(days, cfg, vol=args.iv,
                          trading_days_to_expiry=args.dte, half_spread_pct=args.spread)
    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
