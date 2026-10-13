"""
tests/test_multiagent_5_agents.py

Pruebas integrales de la orquestación del sistema de 5 subagentes:
ScalperAgent, MomentumAgent, SwingGridAgent, MacroTraderAgent, SpeculativeAgent.
"""

from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from tradingbot.core.orchestrator import OrchestratorBot
from tradingbot.utils.clp_converter import CLPConverter


def test_orchestrator_initializes_5_agents():
    orch = OrchestratorBot()
    assert len(orch.agents) == 5
    assert "scalper_t1" in orch.agents
    assert "momentum_t2" in orch.agents
    assert "swing_grid" in orch.agents
    assert "macro_btceth" in orch.agents
    assert "speculative_t3" in orch.agents


def test_orchestrator_capital_pool_distribution_5_agents():
    with patch.object(OrchestratorBot, "__init__", lambda self: None):
        orch = OrchestratorBot()
        orch._fetch_total_capital = AsyncMock(return_value=16.0)

        mocks = {
            "scalper_t1": MagicMock(),
            "momentum_t2": MagicMock(),
            "swing_grid": MagicMock(),
            "macro_btceth": MagicMock(),
            "speculative_t3": MagicMock(),
        }
        for m in mocks.values():
            m.paused = False
            m.config.bot.mode = "passive"

        orch.agents = mocks

        # Escenario B (Speculative passive -> 35 / 35 / 20 / 10 / 0%)
        orch._assign_capital(16.0, scenario_a=False)
        mocks["scalper_t1"].set_capital.assert_called_with(5.60)   # 35% de 16
        mocks["momentum_t2"].set_capital.assert_called_with(5.60)  # 35% de 16
        mocks["swing_grid"].set_capital.assert_called_with(3.20)   # 20% de 16
        mocks["macro_btceth"].set_capital.assert_called_with(1.60) # 10% de 16
        mocks["speculative_t3"].set_capital.assert_called_with(0.0)# 0% de 16


def test_orchestrator_global_status_message_includes_swing_grid():
    with patch.object(OrchestratorBot, "__init__", lambda self: None):
        orch = OrchestratorBot()
        orch._started_at = datetime.utcnow()
        orch._paused = False
        orch.clp_converter = CLPConverter()

        mock_swing = MagicMock()
        mock_swing.get_status.return_value = {
            "agent_id": "swing_grid",
            "agent_name": "SwingGridAgent",
            "mode": "ACTIVE",
            "trading_mode": "target",
            "pairs": ["BNB/USDT", "XRP/USDT"],
            "timeframe": "15m",
            "current_timeframe": "15m",
            "capital_pool_pct": 0.20,
            "assigned_capital_usd": 3.20,
            "cycle_count": 8,
            "open_positions": [],
            "open_positions_count": 0,
            "closed_trades_count": 2,
            "winning_trades": 2,
            "losing_trades": 0,
            "realized_pnl_usd": 0.15,
            "unrealized_pnl_usd": 0.0,
            "total_pnl_usd": 0.15,
            "total_evaluations": 16,
            "eval_counts": {"BUY": 0, "HOLD": 16},
        }

        orch.agents = {"swing_grid": mock_swing}
        msg = orch.format_global_status_message(capital_usd=16.0, capital_clp=15200)

        assert "SwingGridAgent" in msg
        assert "🌊" in msg
        assert "Agentes Activos:</b> 1 / 1" in msg
