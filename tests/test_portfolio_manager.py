import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Portfolio, Trade, DigitalWallet, CashFlow, Base

def test_portfolio_unrealized_pnl_calculation():
    pm = PortfolioManager()
    session = DatabaseSession.get_session()
    try:
        # Clear or create test portfolio
        session.query(Portfolio).filter(Portfolio.asset == "TESTCOIN").delete()
        session.commit()

        # Simulate BUY order
        pm._update_portfolio_entry(session, "TESTCOIN/USDT", "BUY", 2.0, 100.0, is_paper=True)
        session.commit()

        item = session.query(Portfolio).filter(Portfolio.asset == "TESTCOIN", Portfolio.is_paper == True).first()
        assert item is not None
        assert float(item.quantity) == 2.0
        assert float(item.avg_price) == 100.0
        assert float(item.current_price) == 100.0
        assert float(item.unrealized_pnl) == 0.0

        # Update price higher (price goes to 150)
        pm.update_asset_price("TESTCOIN/USDT", 150.0, is_paper=True)
        
        session.refresh(item)
        assert float(item.current_price) == 150.0
        # Unrealized PnL: (150 - 100) * 2 = 100 USD
        assert float(item.unrealized_pnl) == 100.0

        # Update price lower (price goes to 80)
        pm.update_asset_price("TESTCOIN/USDT", 80.0, is_paper=True)
        session.refresh(item)
        assert float(item.current_price) == 80.0
        # Unrealized PnL: (80 - 100) * 2 = -40 USD
        assert float(item.unrealized_pnl) == -40.0

        # Cleanup
        session.delete(item)
        session.commit()
    finally:
        session.close()

def test_get_cashflow_summary_includes_unrealized():
    pm = PortfolioManager()
    summary = pm.get_cashflow_summary()
    assert "realized_pnl" in summary
    assert "unrealized_pnl" in summary
    assert "pnl" in summary
    assert "roi_pct" in summary
    assert summary["pnl"] == summary["realized_pnl"] + summary["unrealized_pnl"]

def test_telegram_listener_keyboards():
    from tradingbot.interfaces.telegram.telegram_listener import TelegramListener
    mock_bot = MagicMock()
    mock_bot.paused = False
    mock_bot.config.bot.trading_mode = "scalper"

    listener = TelegramListener(mock_bot)
    status_kb = listener._build_status_keyboard()
    assert status_kb is not None
    assert len(status_kb.inline_keyboard) == 4
    
    # Check that wallet button is present in status keyboard
    buttons = [btn for row in status_kb.inline_keyboard for btn in row]
    wallet_btn = next((b for b in buttons if b.callback_data == "nav:wallet"), None)
    assert wallet_btn is not None
    assert "Billetera" in wallet_btn.text

    modes_kb = listener._build_modes_keyboard()
    assert modes_kb is not None
    assert len(modes_kb.inline_keyboard) == 2

    stats_kb = listener._build_stats_keyboard(hours=6)
    assert stats_kb is not None

    cashflow_kb = listener._build_cashflow_keyboard()
    assert cashflow_kb is not None
    cf_buttons = [btn for row in cashflow_kb.inline_keyboard for btn in row]
    assert any(b.callback_data == "nav:wallet" for b in cf_buttons)

    wallet_kb = listener._build_wallet_keyboard()
    assert wallet_kb is not None
    w_buttons = [btn for row in wallet_kb.inline_keyboard for btn in row]
    assert any(b.callback_data == "nav:cashflow" for b in w_buttons)

def test_telegram_listener_separate_cashflow_and_wallet():
    from tradingbot.interfaces.telegram.telegram_listener import TelegramListener
    mock_bot = MagicMock()
    mock_bot.paused = False
    mock_bot.config.bot.trading_mode = "trend"
    mock_bot.portfolio_manager.get_cashflow_summary.return_value = {
        "balance": 9500.0,
        "deposits": 0.0,
        "expenses": 0.0,
        "withdrawals": 0.0,
        "realized_pnl": 50.0,
        "unrealized_pnl": -20.0,
        "pnl": 30.0,
        "roi_pct": 0.3
    }
    mock_bot.portfolio_manager.get_portfolio_summary.return_value = [
        {
            "asset": "BTC",
            "quantity": 0.05,
            "avg_price": 60000.0,
            "current_price": 61000.0,
            "unrealized_pnl": 50.0
        }
    ]

    listener = TelegramListener(mock_bot)
    cf_msg, cf_kb = listener._get_cashflow_payload()
    assert "Reporte Financiero (Flujo de Caja)" in cf_msg
    assert "Detalle de tu Billetera" not in cf_msg

    w_msg, w_kb = listener._get_wallet_payload()
    assert "Detalle de tu Billetera (Holdings)" in w_msg
    assert "BTC" in w_msg
    assert "Reporte Financiero" not in w_msg

@pytest.mark.asyncio
async def test_telegram_async_commands_and_callbacks():
    from unittest.mock import AsyncMock
    from tradingbot.interfaces.telegram.telegram_listener import TelegramListener

    mock_bot = MagicMock()
    mock_bot.paused = False
    mock_bot.config.bot.trading_mode = "trend"
    mock_bot.portfolio_manager.get_cashflow_summary.return_value = {
        "balance": 10000.0,
        "deposits": 0.0,
        "expenses": 0.0,
        "withdrawals": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "pnl": 0.0,
        "roi_pct": 0.0
    }
    mock_bot.portfolio_manager.get_portfolio_summary.return_value = []

    listener = TelegramListener(mock_bot)
    listener.allowed_chat_id = "12345"

    # Mock Update and Context for cashflow_command
    update = MagicMock()
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await listener.cashflow_command(update, context)
    # Must reply exactly once with cashflow message
    assert update.message.reply_text.call_count == 1
    call_args = update.message.reply_text.call_args[0][0]
    assert "Reporte Financiero" in call_args
    assert "Detalle de tu Billetera" not in call_args

    # Mock Update and Context for wallet_command
    update.message.reply_text.reset_mock()
    await listener.wallet_command(update, context)
    assert update.message.reply_text.call_count == 1
    call_args = update.message.reply_text.call_args[0][0]
    assert "Detalle de tu Billetera" in call_args
    assert "Reporte Financiero" not in call_args

    # Mock callback_handler for nav:wallet
    cb_update = MagicMock()
    cb_update.effective_chat.id = 12345
    cb_update.callback_query.data = "nav:wallet"
    cb_update.callback_query.answer = AsyncMock()
    cb_update.callback_query.edit_message_text = AsyncMock()

    await listener.callback_handler(cb_update, context)
    assert cb_update.callback_query.edit_message_text.call_count == 1
    edit_text = cb_update.callback_query.edit_message_text.call_args[0][0]
    assert "Detalle de tu Billetera" in edit_text

    # Mock callback_handler for nav:cashflow
    cb_update.callback_query.data = "nav:cashflow"
    cb_update.callback_query.edit_message_text.reset_mock()
    cb_update.callback_query.message.reply_text = AsyncMock()

    await listener.callback_handler(cb_update, context)
    assert cb_update.callback_query.edit_message_text.call_count == 1
    edit_text = cb_update.callback_query.edit_message_text.call_args[0][0]
    assert "Reporte Financiero" in edit_text
    # Ensure no second message was sent via reply_text
    assert cb_update.callback_query.message.reply_text.call_count == 0


