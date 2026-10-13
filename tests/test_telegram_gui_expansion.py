"""
tests/test_telegram_gui_expansion.py

Pruebas de la interfaz GUI y botones interactivos de Telegram para el nuevo agente Swing/Grid.
"""

from unittest.mock import MagicMock
from tradingbot.interfaces.telegram.telegram_listener import TelegramListener


def test_telegram_status_keyboard_has_swing_grid_button():
    mock_bot = MagicMock()
    mock_bot.paused = False
    mock_bot.agents = {
        "scalper_t1": MagicMock(),
        "momentum_t2": MagicMock(),
        "swing_grid": MagicMock(),
        "macro_btceth": MagicMock(),
        "speculative_t3": MagicMock(),
    }
    mock_bot.config.bot.trading_mode = "scalper"

    listener = TelegramListener(mock_bot)
    keyboard = listener._build_status_keyboard()

    all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for btn in all_buttons]

    assert "agent_view:scalper_t1" in callbacks
    assert "agent_view:momentum_t2" in callbacks
    assert "agent_view:swing_grid" in callbacks
    assert "agent_view:macro_btceth" in callbacks
    assert "agent_view:speculative_t3" in callbacks

    swing_btn = next(b for b in all_buttons if b.callback_data == "agent_view:swing_grid")
    assert "🌊" in swing_btn.text
    assert "Swing" in swing_btn.text


def test_telegram_wallet_keyboard_has_swing_grid_button():
    mock_bot = MagicMock()
    mock_bot.agents = {
        "scalper_t1": MagicMock(),
        "momentum_t2": MagicMock(),
        "swing_grid": MagicMock(),
        "macro_btceth": MagicMock(),
        "speculative_t3": MagicMock(),
    }

    listener = TelegramListener(mock_bot)
    keyboard = listener._build_wallet_keyboard()

    all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    callbacks = [btn.callback_data for btn in all_buttons]

    assert "agent_view:swing_grid" in callbacks


def test_telegram_agent_detail_keyboard_for_swing_grid():
    mock_agent = MagicMock()
    mock_agent.paused = False

    mock_bot = MagicMock()
    mock_bot.agents = {"swing_grid": mock_agent}

    listener = TelegramListener(mock_bot)
    kb_active = listener._build_agent_detail_keyboard("swing_grid")
    callbacks_active = [btn.callback_data for row in kb_active.inline_keyboard for btn in row]

    assert "agent_view:swing_grid" in callbacks_active
    assert "agent_pause:swing_grid" in callbacks_active

    mock_agent.paused = True
    kb_paused = listener._build_agent_detail_keyboard("swing_grid")
    callbacks_paused = [btn.callback_data for row in kb_paused.inline_keyboard for btn in row]

    assert "agent_resume:swing_grid" in callbacks_paused
