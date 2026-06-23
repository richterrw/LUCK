from datetime import datetime

from luck.agent import Agent
from luck.broker import OptionContract, SimulatedBroker
from luck.config import Config, RiskConfig, StrategyConfig
from luck.strategy import Bar, Side


def _bar(hour, minute, high, low, close):
    return Bar(ts=datetime(2026, 6, 23, hour, minute), high=high, low=low, close=close)


def _breakout_bars():
    return [
        _bar(9, 30, 150.5, 149.5, 150.0),
        _bar(9, 35, 151.0, 149.8, 150.7),
        _bar(9, 40, 150.9, 149.0, 150.2),
        _bar(9, 46, 152.0, 151.5, 151.9),  # upside breakout -> CALL
    ]


def _cfg():
    return Config(
        symbol="SPCX",
        strategy=StrategyConfig(opening_range_minutes=15, breakout_buffer_pct=0.05, max_trades_per_day=4),
        risk=RiskConfig(max_premium_per_trade=500, max_contracts=5, stop_loss_pct=0.30, take_profit_pct=0.50),
    )


def _call_chain():
    return [OptionContract(symbol="SPCX260626C00150000", strike=150, expiry="2026-06-26",
                           side=Side.CALL, ask=2.0, bid=1.9, delta=0.5)]


def test_agent_opens_on_breakout():
    broker = SimulatedBroker(bars=_breakout_bars(), chain=_call_chain(), mins_to_close=120)
    agent = Agent(broker, _cfg())
    agent.step()
    assert len(agent.open_positions) == 1
    assert agent.open_positions[0].side == Side.CALL


def test_agent_takes_profit():
    broker = SimulatedBroker(bars=_breakout_bars(), chain=_call_chain(), mins_to_close=120)
    agent = Agent(broker, _cfg())
    agent.step()  # opens at 2.0
    sym = agent.open_positions[0].symbol
    broker.set_option_price(sym, 3.1)  # +55% -> take profit
    agent.step()
    assert not agent.open_positions
    assert agent.risk_state.realized_pnl > 0


def test_agent_flattens_near_close():
    broker = SimulatedBroker(bars=_breakout_bars(), chain=_call_chain(), mins_to_close=120)
    agent = Agent(broker, _cfg())
    agent.step()
    assert agent.open_positions
    broker.mins_to_close = 10  # inside flatten window
    agent.step()
    assert not agent.open_positions


def test_dry_run_places_no_orders():
    broker = SimulatedBroker(bars=_breakout_bars(), chain=_call_chain(), mins_to_close=120)
    agent = Agent(broker, _cfg(), dry_run=True)
    agent.step()
    assert not agent.open_positions
