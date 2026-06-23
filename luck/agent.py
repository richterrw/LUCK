"""The trading agent: ties strategy, risk, and broker into a decision loop."""

from __future__ import annotations

import logging

from .broker import Broker, Position
from .config import Config
from .risk import DailyRiskState, should_exit, size_position
from .strategy import generate_signal

log = logging.getLogger("luck.agent")


class Agent:
    def __init__(self, broker: Broker, cfg: Config, dry_run: bool = False):
        self.broker = broker
        self.cfg = cfg
        self.dry_run = dry_run
        self.risk_state = DailyRiskState(cfg.risk)
        self.open_positions: list[Position] = []
        # "Armed" prevents re-entering the same breakout repeatedly. We only
        # arm a new entry once price falls back inside the opening range
        # (signal clears), so each breakout produces at most one entry.
        self.armed = True

    # ------------------------------------------------------------------ #
    def step(self) -> None:
        """One evaluation cycle: manage exits, then consider a new entry."""
        if not self.broker.is_market_open():
            log.info("market closed; idle")
            return

        # 1. Forced end-of-day flatten (true day-trading: no overnight holds).
        if self.broker.minutes_to_close() <= self.cfg.risk.flatten_minutes_before_close:
            if self.open_positions:
                log.info("near close; flattening all positions")
                self._flatten_all("eod_flatten")
            return

        # 2. Manage existing positions (stop-loss / take-profit).
        self._manage_exits()

        # 3. Consider a new entry if risk budget allows.
        self._maybe_enter()

    # ------------------------------------------------------------------ #
    def _manage_exits(self) -> None:
        for pos in list(self.open_positions):
            current = self.broker.option_price(pos.symbol)
            reason = should_exit(pos.entry_price, current, self.cfg.risk)
            if reason:
                self._close(pos, reason)

    def _maybe_enter(self) -> None:
        if self.open_positions:
            return  # one position at a time keeps risk legible

        ok, why = self.risk_state.can_open_new(self.cfg.strategy.max_trades_per_day)
        if not ok:
            log.info("not opening: %s", why)
            return

        bars = self.broker.get_underlying_bars(self.cfg.symbol)
        signal = generate_signal(
            bars,
            self.cfg.strategy.opening_range_minutes,
            self.cfg.strategy.breakout_buffer_pct,
        )
        if not signal:
            self.armed = True  # price back inside range; ready for next breakout
            return
        if not self.armed:
            return  # already acted on this breakout; wait for it to reset
        log.info("signal: %s (%s)", signal.side.value.upper(), signal.reason)

        contract = self.broker.select_option(
            self.cfg.symbol, signal.side,
            self.cfg.strategy.target_delta, self.cfg.strategy.option_expiry,
        )
        if not contract:
            log.warning("no option contract found for %s", signal.side)
            return

        sizing = size_position(contract.ask, self.cfg.risk)
        if not sizing.approved:
            log.info("sizing rejected: %s", sizing.reason)
            return

        if self.dry_run:
            log.info(
                "[DRY-RUN] would BUY %d %s @ $%.2f (cost ~$%.0f) — %s",
                sizing.contracts, contract.symbol, contract.ask,
                sizing.estimated_cost, sizing.reason,
            )
            return

        pos = self.broker.buy_to_open(contract, sizing.contracts)
        self.open_positions.append(pos)
        self.armed = False  # consumed this breakout
        log.info(
            "OPENED %d %s @ $%.2f (cost ~$%.0f)",
            pos.contracts, pos.symbol, pos.entry_price, sizing.estimated_cost,
        )

    # ------------------------------------------------------------------ #
    def _close(self, pos: Position, reason: str) -> None:
        if self.dry_run:
            log.info("[DRY-RUN] would CLOSE %s (%s)", pos.symbol, reason)
            return
        pnl = self.broker.sell_to_close(pos)
        self.risk_state.record_trade(pnl)
        self.open_positions.remove(pos)
        log.info("CLOSED %s (%s) P&L=$%.2f | day P&L=$%.2f",
                 pos.symbol, reason, pnl, self.risk_state.realized_pnl)
        if self.risk_state.halted:
            log.warning("KILL SWITCH: daily loss limit reached; no new trades today")

    def _flatten_all(self, reason: str) -> None:
        for pos in list(self.open_positions):
            self._close(pos, reason)
