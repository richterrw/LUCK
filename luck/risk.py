"""Risk management: position sizing, exit rules, and the daily kill switch.

All pure functions / simple state so they can be tested without a broker.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig


@dataclass(frozen=True)
class SizingDecision:
    contracts: int
    estimated_cost: float
    approved: bool
    reason: str


def size_position(option_ask: float, cfg: RiskConfig) -> SizingDecision:
    """Decide how many contracts to buy under the premium and contract caps.

    `option_ask` is the per-share option price; one contract = 100 shares.
    """
    if option_ask <= 0:
        return SizingDecision(0, 0.0, False, "invalid option price")

    cost_per_contract = option_ask * 100
    if cost_per_contract > cfg.max_premium_per_trade:
        return SizingDecision(
            0, 0.0, False,
            f"one contract (${cost_per_contract:.0f}) exceeds per-trade cap "
            f"(${cfg.max_premium_per_trade:.0f})",
        )

    by_premium = int(cfg.max_premium_per_trade // cost_per_contract)
    contracts = max(0, min(by_premium, cfg.max_contracts))
    if contracts < 1:
        return SizingDecision(0, 0.0, False, "sizing rounded to zero contracts")

    return SizingDecision(
        contracts=contracts,
        estimated_cost=contracts * cost_per_contract,
        approved=True,
        reason=f"{contracts} contract(s) @ ${option_ask:.2f}",
    )


def should_exit(entry_price: float, current_price: float, cfg: RiskConfig) -> str | None:
    """Return an exit reason ('stop_loss' / 'take_profit') or None to hold."""
    if entry_price <= 0:
        return None
    change = (current_price - entry_price) / entry_price
    if change <= -cfg.stop_loss_pct:
        return "stop_loss"
    if change >= cfg.take_profit_pct:
        return "take_profit"
    return None


class DailyRiskState:
    """Tracks realized P&L for the session and trips the kill switch."""

    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.realized_pnl = 0.0
        self.trades_today = 0
        self._halted = False

    def record_trade(self, pnl: float) -> None:
        self.realized_pnl += pnl
        self.trades_today += 1
        if self.realized_pnl <= -abs(self.cfg.daily_loss_limit):
            self._halted = True

    @property
    def halted(self) -> bool:
        return self._halted

    def can_open_new(self, max_trades_per_day: int) -> tuple[bool, str]:
        if self._halted:
            return False, (
                f"daily loss limit hit (realized ${self.realized_pnl:.2f} <= "
                f"-${self.cfg.daily_loss_limit:.0f}); trading halted for the day"
            )
        if self.trades_today >= max_trades_per_day:
            return False, f"max trades/day reached ({max_trades_per_day})"
        return True, "ok"
