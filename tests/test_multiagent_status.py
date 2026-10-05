import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

def test_base_agent_get_status():
    from agents.scalper_agent import ScalperAgent

    agent = ScalperAgent("configs/agent_scalper.yaml")
    agent._started_at = datetime.utcnow()
    agent._cycle_count = 5
    agent._assigned_capital = 10.0

    status = agent.get_status()
    assert status["agent_id"] == "scalper_t1"
    assert status["mode"] == "ACTIVE"
    assert status["trading_mode"] == "scalper"
    assert "SOL/USDT" in status["pairs"]
    assert status["cycle_count"] == 5
    assert status["assigned_capital_usd"] == 10.0
    assert "open_positions" in status
    assert "open_positions_count" in status
    assert "realized_pnl_usd" in status
    assert "unrealized_pnl_usd" in status
    assert "total_pnl_usd" in status
    assert "total_evaluations" in status
    assert "eval_counts" in status

def test_orchestrator_format_global_status_message():
    from tradingbot.core.orchestrator import OrchestratorBot

    with patch.object(OrchestratorBot, "__init__", lambda self: None):
        orch = OrchestratorBot()
        orch._started_at = datetime.utcnow()
        orch._paused = False

        from tradingbot.utils.clp_converter import CLPConverter
        orch.clp_converter = CLPConverter()

        mock_scalper = MagicMock()
        mock_scalper.get_status.return_value = {
            "agent_id": "scalper_t1",
            "agent_name": "ScalperAgent_Tier1",
            "mode": "ACTIVE",
            "trading_mode": "scalper",
            "pairs": ["SOL/USDT", "NEAR/USDT"],
            "timeframe": "1m",
            "current_timeframe": "1m",
            "capital_pool_pct": 0.50,
            "assigned_capital_usd": 9.50,
            "cycle_count": 10,
            "open_positions": [
                {
                    "symbol": "NEAR/USDT",
                    "side": "BUY",
                    "quantity": 0.20,
                    "entry_price": 5.0,
                    "current_price": 5.05,
                    "unrealized_pnl": 0.01,
                    "unrealized_pnl_pct": 1.0,
                }
            ],
            "open_positions_count": 1,
            "closed_trades_count": 1,
            "winning_trades": 1,
            "losing_trades": 0,
            "realized_pnl_usd": 0.50,
            "unrealized_pnl_usd": 0.01,
            "total_pnl_usd": 0.51,
            "total_evaluations": 20,
            "eval_counts": {"BUY": 1, "HOLD": 19},
        }

        mock_speculative = MagicMock()
        mock_speculative.get_status.return_value = {
            "agent_id": "speculative_t3",
            "agent_name": "SpeculativeAgent_Tier3",
            "mode": "PASSIVE",
            "trading_mode": "scalper",
            "pairs": ["BEAMX/USDT", "MUBARAK/USDT"],
            "timeframe": "15m",
            "current_timeframe": "15m",
            "capital_pool_pct": 0.00,
            "assigned_capital_usd": 0.0,
            "cycle_count": 0,
            "open_positions": [],
            "open_positions_count": 0,
            "closed_trades_count": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "total_pnl_usd": 0.0,
            "total_evaluations": 0,
            "eval_counts": {},
        }

        orch.agents = {
            "scalper_t1": mock_scalper,
            "speculative_t3": mock_speculative,
        }

        msg = orch.format_global_status_message(capital_usd=19.0, capital_clp=18693.0)
        assert "Estado del Bot (Multi-Agente)" in msg
        assert "ScalperAgent_Tier1" in msg
        assert "NEAR/USDT" in msg
        assert "Ganado/Perdido" in msg
        assert "Evaluaciones" in msg
        assert "SpeculativeAgent_Tier3" in msg
        assert "PASSIVE" in msg

def test_telegram_listener_subagent_keyboard():
    from tradingbot.interfaces.telegram.telegram_listener import TelegramListener

    mock_bot = MagicMock()
    mock_bot.paused = False
    mock_bot.agents = {
        "scalper_t1": MagicMock(),
        "momentum_t2": MagicMock(),
        "macro_btceth": MagicMock(),
        "speculative_t3": MagicMock(),
    }
    mock_bot.config.bot.trading_mode = "scalper"

    listener = TelegramListener(mock_bot)
    status_kb = listener._build_status_keyboard()
    assert status_kb is not None
    # 4 original rows + 2 subagent rows = 6 rows
    assert len(status_kb.inline_keyboard) == 6

    buttons = [btn for row in status_kb.inline_keyboard for btn in row]
    scalper_btn = next((b for b in buttons if b.callback_data == "agent_view:scalper_t1"), None)
    assert scalper_btn is not None
    assert "Scalper" in scalper_btn.text


@pytest.mark.asyncio
async def test_orchestrator_resume_and_pause_speculative():
    from tradingbot.core.orchestrator import OrchestratorBot

    with patch.object(OrchestratorBot, "__init__", lambda self: None):
        orch = OrchestratorBot()
        orch._fetch_total_capital = AsyncMock(return_value=50.0)

        mock_scalper = MagicMock()
        mock_scalper.capital_pool_pct = 0.50
        mock_momentum = MagicMock()
        mock_momentum.capital_pool_pct = 0.40
        mock_macro = MagicMock()
        mock_macro.capital_pool_pct = 0.10
        mock_spec = MagicMock()
        mock_spec.capital_pool_pct = 0.00
        mock_spec.paused = True
        mock_spec.config.bot.mode = "passive"
        mock_spec.get_status.return_value = {
            "agent_id": "speculative_t3",
            "agent_name": "SpeculativeAgent_Tier3",
            "mode": "ACTIVE",
            "trading_mode": "scalper",
            "assigned_capital_usd": 5.0,
            "capital_pool_pct": 0.10,
        }

        orch.agents = {
            "scalper_t1": mock_scalper,
            "momentum_t2": mock_momentum,
            "macro_btceth": mock_macro,
            "speculative_t3": mock_spec,
        }

        # Resume speculative
        status = await orch.resume_agent("speculative_t3")
        mock_spec.resume.assert_called_once()
        assert status["mode"] == "ACTIVE"
        # Check Escenario A capital distribution
        mock_scalper.set_capital.assert_called_with(22.5)  # 45% of 50
        mock_momentum.set_capital.assert_called_with(17.5) # 35% of 50
        mock_spec.set_capital.assert_called_with(5.0)      # 10% of 50
        mock_macro.set_capital.assert_called_with(5.0)     # 10% of 50

        # Pause speculative
        mock_spec.get_status.return_value["mode"] = "PASSIVE"
        p_status = await orch.pause_agent("speculative_t3")
        mock_spec.pause.assert_called_once()
        assert p_status["mode"] == "PASSIVE"
        # Check Escenario B capital distribution
        mock_scalper.set_capital.assert_called_with(25.0)  # 50% of 50
        mock_momentum.set_capital.assert_called_with(20.0) # 40% of 50
        mock_spec.set_capital.assert_called_with(0.0)      # 0% of 50


@pytest.mark.asyncio
async def test_telegram_listener_resume_and_pause_mode_reporting():
    from tradingbot.interfaces.telegram.telegram_listener import TelegramListener

    mock_bot = MagicMock()
    mock_bot.resume_agent = AsyncMock(return_value={
        "agent_id": "speculative_t3",
        "agent_name": "SpeculativeAgent_Tier3",
        "mode": "ACTIVE",
        "trading_mode": "scalper",
        "timeframe": "15m",
        "current_timeframe": "15m",
        "assigned_capital_usd": 5.0,
        "capital_pool_pct": 0.10,
    })
    mock_bot.pause_agent = AsyncMock(return_value={
        "agent_id": "speculative_t3",
        "agent_name": "SpeculativeAgent_Tier3",
        "mode": "PASSIVE",
        "trading_mode": "scalper",
        "timeframe": "15m",
        "current_timeframe": "15m",
        "assigned_capital_usd": 0.0,
        "capital_pool_pct": 0.00,
    })

    listener = TelegramListener(mock_bot)
    listener.verify_user = AsyncMock(return_value=True)

    # Test resume_agent_command
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await listener.resume_agent_command(update, context, "speculative_t3")
    mock_bot.resume_agent.assert_called_once_with("speculative_t3")
    args, kwargs = update.message.reply_text.call_args
    sent_text = args[0]
    assert "reanudado con éxito" in sent_text
    assert "Modo en que quedó:" in sent_text
    assert "ACTIVE" in sent_text
    assert "$5.00 USDT" in sent_text

    # Test pause_agent_command
    update.message.reply_text.reset_mock()
    await listener.pause_agent_command(update, context, "speculative_t3")
    mock_bot.pause_agent.assert_called_once_with("speculative_t3")
    args, kwargs = update.message.reply_text.call_args
    sent_text = args[0]
    assert "pausado con éxito" in sent_text
    assert "Modo en que quedó:" in sent_text
    assert "PASSIVE" in sent_text

