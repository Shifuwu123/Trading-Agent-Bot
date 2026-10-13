"""
tests/test_swing_grid_agent.py

Pruebas automatizadas de inicialización y ciclo de vida de SwingGridAgent.
"""

from datetime import datetime
from agents.swing_grid_agent import SwingGridAgent
from tradingbot.strategies.grid_swing import GridSwingStrategy


def test_swing_grid_agent_initialization():
    agent = SwingGridAgent("configs/agent_swing_grid.yaml")
    assert agent.agent_id == "swing_grid"
    assert agent.agent_name == "SwingGridAgent"
    assert agent.capital_pool_pct == 0.20
    assert agent.config.bot.trading_mode == "target"
    assert "BNB/USDT" in agent.config.bot.trading_pairs
    assert "XRP/USDT" in agent.config.bot.trading_pairs
    assert isinstance(agent.strategy, GridSwingStrategy)


def test_swing_grid_agent_status_and_capital():
    agent = SwingGridAgent("configs/agent_swing_grid.yaml")
    agent.set_capital(3.20)
    assert agent._assigned_capital == 3.20

    agent._started_at = datetime.utcnow()
    agent._cycle_count = 12

    status = agent.get_status()
    assert status["agent_id"] == "swing_grid"
    assert status["mode"] == "ACTIVE"
    assert status["trading_mode"] == "target"
    assert status["assigned_capital_usd"] == 3.20
    assert status["capital_pool_pct"] == 0.20
    assert status["cycle_count"] == 12
    assert "BNB/USDT" in status["pairs"]
    assert "XRP/USDT" in status["pairs"]
