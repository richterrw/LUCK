"""Configuration loading and the trading-mode safety gate."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LIVE_CONFIRMATION_PHRASE = "I ACCEPT LIVE TRADING RISK"


@dataclass
class StrategyConfig:
    opening_range_minutes: int = 15
    breakout_buffer_pct: float = 0.05
    max_trades_per_day: int = 4
    option_expiry: str = "nearest"
    target_delta: float = 0.50


@dataclass
class RiskConfig:
    max_premium_per_trade: float = 500.0
    max_contracts: int = 5
    stop_loss_pct: float = 0.30
    take_profit_pct: float = 0.50
    daily_loss_limit: float = 750.0
    flatten_minutes_before_close: int = 15


@dataclass
class PollingConfig:
    interval_seconds: int = 30


@dataclass
class Config:
    symbol: str = "SPCX"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)

    @property
    def is_live(self) -> bool:
        return os.environ.get("LUCK_MODE", "paper").strip().lower() == "live"


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"config section '{key}' must be a mapping")
    return value


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load and validate config from YAML, falling back to dataclass defaults."""
    path = Path(path)
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text()) or {}

    cfg = Config(
        symbol=raw.get("symbol", "SPCX"),
        strategy=StrategyConfig(**_section(raw, "strategy")),
        risk=RiskConfig(**_section(raw, "risk")),
        polling=PollingConfig(**_section(raw, "polling")),
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    r = cfg.risk
    if r.max_premium_per_trade <= 0:
        raise ValueError("risk.max_premium_per_trade must be positive")
    if r.max_contracts < 1:
        raise ValueError("risk.max_contracts must be >= 1")
    if not 0 < r.stop_loss_pct <= 1:
        raise ValueError("risk.stop_loss_pct must be in (0, 1]")
    if r.take_profit_pct <= 0:
        raise ValueError("risk.take_profit_pct must be positive")
    if r.daily_loss_limit <= 0:
        raise ValueError("risk.daily_loss_limit must be positive")
    s = cfg.strategy
    if s.opening_range_minutes < 1:
        raise ValueError("strategy.opening_range_minutes must be >= 1")
    if not 0 < s.target_delta < 1:
        raise ValueError("strategy.target_delta must be in (0, 1)")


def confirm_live_mode(input_fn=input) -> bool:
    """Require an explicit typed phrase before any real-money trading.

    Returns True only when the operator types the exact confirmation phrase.
    Kept separate from env config so live trading needs *two* deliberate acts:
    setting LUCK_MODE=live AND typing the phrase.
    """
    print("\n" + "=" * 64)
    print("  LIVE REAL-MONEY TRADING REQUESTED (LUCK_MODE=live)")
    print("  This will place REAL options orders with REAL money.")
    print("  Options can lose 100% of premium. You accept all risk.")
    print("=" * 64)
    print(f'  Type exactly:  {LIVE_CONFIRMATION_PHRASE}')
    answer = input_fn("  > ").strip()
    return answer == LIVE_CONFIRMATION_PHRASE
