"""Generate synthetic SPCX minute bars for trying the backtester.

NOT real market data — a random-walk with occasional intraday trends so you can
see the backtest produce trades. Replace with real bars (timestamp,high,low,
close in ET) before drawing any conclusions.

    python examples/generate_sample_data.py > examples/sample_spcx_minutes.csv
    python -m luck.backtest --data examples/sample_spcx_minutes.csv
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

random.seed(42)

START_PRICE = 150.0
DAYS = 10
SESSION_MINUTES = 390  # 09:30 -> 16:00


def main() -> None:
    print("timestamp,high,low,close")
    price = START_PRICE
    day = datetime(2026, 6, 16, 9, 30)  # first options session
    for _ in range(DAYS):
        # Each day gets a random drift so some days trend (ORB-friendly).
        drift = random.uniform(-0.04, 0.04)
        ts = day
        for _ in range(SESSION_MINUTES):
            shock = random.gauss(0, 0.18)
            price = max(1.0, price + drift + shock)
            high = price + abs(random.gauss(0, 0.12))
            low = price - abs(random.gauss(0, 0.12))
            print(f"{ts.isoformat()},{high:.2f},{low:.2f},{price:.2f}")
            ts += timedelta(minutes=1)
        day = (day + timedelta(days=1)).replace(hour=9, minute=30)


if __name__ == "__main__":
    main()
