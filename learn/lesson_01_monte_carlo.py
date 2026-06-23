"""Lesson 1 — Monte Carlo simulation, the actuarial workhorse.

THE IDEA
--------
An actuary's instinct for "what is this worth / what could happen?" is: simulate
it thousands of times and look at the distribution of outcomes.

We'll price a European call option two completely different ways:
  (A) the closed-form Black-Scholes formula you already wrote in luck/backtest.py
  (B) a Monte Carlo simulation
and show they AGREE. Two independent methods agreeing is how actuaries gain
confidence a model is right ("reconciliation"). That mindset matters more than
the option itself.
"""

from __future__ import annotations

import numpy as np

# Reuse YOUR own Black-Scholes function. Reusing tested code instead of
# rewriting it is itself a professional habit.
from luck.backtest import bs_price

# ---- The scenario --------------------------------------------------------- #
S0 = 150.0      # spot price today
K = 150.0       # strike (at-the-money)
VOL = 0.90      # annualized volatility (SPCX is wild)
T = 30 / 252    # time to expiry in years (30 trading days)
# NOTE: our bs_price assumes zero interest rate (r = 0), so we match that here.


def monte_carlo_call(s0, k, vol, t, n_sims, seed=0):
    """Estimate a European call price by simulating terminal prices.

    Model: under risk-neutral GBM with r=0, the terminal price is
        S_T = S0 * exp(-0.5 * vol^2 * t + vol * sqrt(t) * Z),  Z ~ Normal(0,1)
    The option pays max(S_T - K, 0) at expiry; its value today is the average
    payoff (no discounting because r=0).
    """
    rng = np.random.default_rng(seed)

    # VECTORIZATION: draw ALL random shocks at once into an array, instead of a
    # Python for-loop. This is THE habit that separates slow actuarial code from
    # fast actuarial code. n_sims numbers computed in one C-level operation.
    z = rng.standard_normal(n_sims)                       # shape (n_sims,)
    s_t = s0 * np.exp(-0.5 * vol**2 * t + vol * np.sqrt(t) * z)
    payoffs = np.maximum(s_t - k, 0.0)                    # elementwise max

    price = payoffs.mean()
    # Standard error tells us how trustworthy the estimate is — an actuary never
    # reports a number without knowing its uncertainty.
    std_err = payoffs.std(ddof=1) / np.sqrt(n_sims)
    return price, std_err


def main():
    exact = bs_price(S0, K, T, VOL, is_call=True)
    print(f"Black-Scholes (closed form):  {exact:8.4f}")
    print()
    print(f"{'sims':>10}  {'MC price':>10}  {'std err':>8}  {'diff vs BS':>10}")
    for n in (1_000, 10_000, 100_000, 1_000_000):
        mc, se = monte_carlo_call(S0, K, VOL, T, n)
        print(f"{n:>10,}  {mc:>10.4f}  {se:>8.4f}  {mc - exact:>+10.4f}")

    print()
    print("Notice: as sims grow, the MC estimate converges to the formula and")
    print("the standard error shrinks ~ 1/sqrt(n). That 1/sqrt(n) law is")
    print("everywhere in actuarial work — it's why reserving sims need to be big.")


if __name__ == "__main__":
    main()
