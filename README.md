# LUCK — SPCX Options Day-Trading Agent

An automated agent that day-trades **SpaceX (SPCX)** options. SpaceX IPO'd on
Nasdaq on 2026-06-12; listed options began trading 2026-06-16 on Cboe/Nasdaq.

> ⚠️ **Read this first.** This software can place **real-money** orders for
> **options**, which are leveraged instruments that can lose 100% of premium
> very quickly. Automated trading can compound a bad signal or a bug into real
> losses faster than you can react. You are solely responsible for any orders
> this agent places. Start in **paper mode** (the default) and only enable live
> trading once you fully understand and accept the risk.

## What it does

- Watches the SPCX underlying during the regular session.
- Uses an **Opening-Range Breakout (ORB)** signal: after the first N minutes,
  a break above the range buys ATM **calls**, a break below buys ATM **puts**.
- Sizes each position under hard risk caps, attaches a **stop-loss** and
  **take-profit**, and **flattens everything before the close** — no overnight
  holds (true day-trading, no overnight theta/gap risk).
- A **daily-loss kill switch** halts trading for the day once a configurable
  drawdown is hit.

## Safety model

| Control | Default | Config key |
| --- | --- | --- |
| Mode | `paper` | `LUCK_MODE` env (`paper` \| `live`) |
| Live confirmation | typed phrase required | interactive at startup |
| Max premium per trade | $500 | `risk.max_premium_per_trade` |
| Max open contracts | 5 | `risk.max_contracts` |
| Per-trade stop-loss | 30% | `risk.stop_loss_pct` |
| Per-trade take-profit | 50% | `risk.take_profit_pct` |
| Daily loss kill switch | $750 | `risk.daily_loss_limit` |
| Force flatten before close | 15 min | `risk.flatten_minutes_before_close` |

Live mode requires **both** `LUCK_MODE=live` **and** typing the confirmation
phrase at startup. Without both, the agent runs against Alpaca's paper API.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your Alpaca keys
```

Get free paper-trading keys at https://alpaca.markets. Use paper keys until you
have watched the agent behave for a full session.

## Run

```bash
# Paper (default, safe):
python -m luck.main

# Dry-run a single decision against current data, no orders:
python -m luck.main --once --dry-run

# Live real-money (requires LUCK_MODE=live + typed confirmation):
LUCK_MODE=live python -m luck.main
```

## Test

```bash
pip install pytest
pytest
```

The strategy and risk logic are pure functions with no network dependency, so
the test suite runs offline.

## Disclaimer

This is software for educational and personal use. It is **not** financial
advice. Nothing here is a recommendation to buy or sell any security. Markets
carry risk of total loss. Use at your own risk.
