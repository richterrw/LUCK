"""Broker abstraction.

`Broker` is the interface the agent uses. `AlpacaBroker` talks to Alpaca's
paper or live API (alpaca-py imported lazily). `SimulatedBroker` is a fully
offline fill simulator used for `--dry-run`, tests, and local development.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .selection import OptionQuote, pick_closest_delta
from .strategy import Bar, Side


@dataclass
class Position:
    symbol: str          # full OCC option symbol
    side: Side
    contracts: int
    entry_price: float   # per-share premium paid
    opened_at: datetime


@dataclass
class OptionContract:
    symbol: str          # OCC symbol, e.g. SPCX260619C00150000
    strike: float
    expiry: str
    side: Side
    ask: float
    bid: float
    delta: float


class Broker(Protocol):
    def get_underlying_bars(self, symbol: str) -> list[Bar]: ...
    def select_option(self, underlying: str, side: Side, target_delta: float, expiry: str) -> OptionContract | None: ...
    def buy_to_open(self, contract: OptionContract, contracts: int) -> Position: ...
    def sell_to_close(self, position: Position) -> float: ...
    def option_price(self, symbol: str) -> float: ...
    def is_market_open(self) -> bool: ...
    def minutes_to_close(self) -> float: ...


# --------------------------------------------------------------------------- #
# Offline simulator
# --------------------------------------------------------------------------- #
@dataclass
class SimulatedBroker:
    """In-memory broker for dry-runs and tests. No network, no money."""

    bars: list[Bar] = field(default_factory=list)
    chain: list[OptionContract] = field(default_factory=list)
    market_open: bool = True
    mins_to_close: float = 120.0
    _prices: dict[str, float] = field(default_factory=dict)
    closed_pnl: float = 0.0

    def get_underlying_bars(self, symbol: str) -> list[Bar]:
        return list(self.bars)

    def select_option(self, underlying, side, target_delta, expiry):
        candidates = [c for c in self.chain if c.side == side]
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c.delta - target_delta))

    def buy_to_open(self, contract, contracts):
        self._prices[contract.symbol] = contract.ask
        return Position(
            symbol=contract.symbol, side=contract.side, contracts=contracts,
            entry_price=contract.ask, opened_at=datetime.now(),
        )

    def sell_to_close(self, position):
        exit_price = self._prices.get(position.symbol, position.entry_price)
        pnl = (exit_price - position.entry_price) * position.contracts * 100
        self.closed_pnl += pnl
        return pnl

    def option_price(self, symbol):
        return self._prices.get(symbol, 0.0)

    def set_option_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def is_market_open(self):
        return self.market_open

    def minutes_to_close(self):
        return self.mins_to_close


# --------------------------------------------------------------------------- #
# Alpaca (real paper / live)
# --------------------------------------------------------------------------- #
class AlpacaBroker:
    """Wraps Alpaca trading + market data. `live=False` uses the paper API."""

    def __init__(self, live: bool):
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical.stock import StockHistoricalDataClient
            from alpaca.data.historical.option import OptionHistoricalDataClient
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "alpaca-py is not installed. Run: pip install -r requirements.txt"
            ) from exc

        key = os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError(
                "ALPACA_API_KEY / ALPACA_SECRET_KEY not set (see .env.example)"
            )

        self.live = live
        self.trading = TradingClient(key, secret, paper=not live)
        self._stock_data = StockHistoricalDataClient(key, secret)
        self._option_data = OptionHistoricalDataClient(key, secret)

    # The methods below are thin adapters over alpaca-py. They are intentionally
    # not exercised by the offline test suite; integration testing requires
    # live/paper credentials and a market data subscription.
    def get_underlying_bars(self, symbol: str) -> list[Bar]:  # pragma: no cover
        from datetime import timedelta, timezone
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        start = datetime.now(timezone.utc) - timedelta(hours=8)
        req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute, start=start)
        resp = self._stock_data.get_stock_bars(req)
        out: list[Bar] = []
        for b in resp.data.get(symbol, []):
            out.append(Bar(ts=b.timestamp, high=b.high, low=b.low, close=b.close))
        return out

    def select_option(self, underlying, side, target_delta, expiry):  # pragma: no cover
        from alpaca.trading.requests import GetOptionContractsRequest
        from alpaca.trading.enums import ContractType, AssetStatus

        ctype = ContractType.CALL if side == Side.CALL else ContractType.PUT
        req = GetOptionContractsRequest(
            underlying_symbols=[underlying], status=AssetStatus.ACTIVE, type=ctype, limit=500,
        )
        contracts = self.trading.get_option_contracts(req).option_contracts or []
        if not contracts:
            return None

        # Restrict to the nearest expiry (intraday / 0DTE-style trading).
        contracts.sort(key=lambda c: c.expiration_date)
        nearest_exp = contracts[0].expiration_date
        same_exp = [c for c in contracts if c.expiration_date == nearest_exp]

        # Narrow to strikes within a band around spot to bound the snapshot
        # request, then pick by real delta from option greeks.
        und = self._last_underlying_price(underlying)
        same_exp.sort(key=lambda c: abs(float(c.strike_price) - und))
        candidates = same_exp[:25]

        quotes = self._snapshot_quotes([c.symbol for c in candidates], candidates)
        chosen = pick_closest_delta(quotes, target_delta)
        if chosen is None:
            # Greeks/quotes unavailable (e.g. no OPRA subscription): fall back to
            # the nearest-strike contract and a delta proxy so the agent still
            # functions, but log nothing here — caller decides.
            fallback = candidates[0]
            bid, ask = self._latest_quote(fallback.symbol)
            return OptionContract(
                symbol=fallback.symbol, strike=float(fallback.strike_price),
                expiry=str(nearest_exp), side=side, ask=ask, bid=bid, delta=target_delta,
            )
        return OptionContract(
            symbol=chosen.symbol, strike=chosen.strike, expiry=str(nearest_exp),
            side=side, ask=chosen.ask, bid=chosen.bid, delta=chosen.delta,
        )

    def _last_underlying_price(self, symbol):  # pragma: no cover
        from alpaca.data.requests import StockLatestTradeRequest
        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        return self._stock_data.get_stock_latest_trade(req)[symbol].price

    def _snapshot_quotes(self, symbols, contracts):  # pragma: no cover
        """Fetch per-contract greeks + quotes and return OptionQuote records.

        Returns [] if the snapshot endpoint yields no greeks (which triggers the
        strike-proxy fallback in the caller).
        """
        from alpaca.data.requests import OptionSnapshotRequest

        strike_by_symbol = {c.symbol: float(c.strike_price) for c in contracts}
        try:
            snaps = self._option_data.get_option_snapshot(
                OptionSnapshotRequest(symbol_or_symbols=symbols)
            )
        except Exception:
            return []

        out: list[OptionQuote] = []
        for sym, snap in (snaps or {}).items():
            greeks = getattr(snap, "greeks", None)
            quote = getattr(snap, "latest_quote", None)
            if greeks is None or quote is None or greeks.delta is None:
                continue
            out.append(OptionQuote(
                symbol=sym, strike=strike_by_symbol.get(sym, 0.0),
                delta=greeks.delta, bid=quote.bid_price, ask=quote.ask_price,
            ))
        return out

    def _latest_quote(self, option_symbol):  # pragma: no cover
        from alpaca.data.requests import OptionLatestQuoteRequest
        req = OptionLatestQuoteRequest(symbol_or_symbols=option_symbol)
        q = self._option_data.get_option_latest_quote(req)[option_symbol]
        return q.bid_price, q.ask_price

    def buy_to_open(self, contract, contracts):  # pragma: no cover
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        order = MarketOrderRequest(
            symbol=contract.symbol, qty=contracts,
            side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        )
        self.trading.submit_order(order)
        return Position(
            symbol=contract.symbol, side=contract.side, contracts=contracts,
            entry_price=contract.ask, opened_at=datetime.now(),
        )

    def sell_to_close(self, position):  # pragma: no cover
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        order = MarketOrderRequest(
            symbol=position.symbol, qty=position.contracts,
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        )
        self.trading.submit_order(order)
        exit_price = self.option_price(position.symbol)
        return (exit_price - position.entry_price) * position.contracts * 100

    def option_price(self, symbol):  # pragma: no cover
        from alpaca.data.requests import OptionLatestQuoteRequest
        req = OptionLatestQuoteRequest(symbol_or_symbols=symbol)
        q = self._option_data.get_option_latest_quote(req)[symbol]
        return (q.bid_price + q.ask_price) / 2 if q.bid_price else q.ask_price

    def is_market_open(self):  # pragma: no cover
        return self.trading.get_clock().is_open

    def minutes_to_close(self):  # pragma: no cover
        clock = self.trading.get_clock()
        delta = clock.next_close - clock.timestamp
        return delta.total_seconds() / 60
