import pytest
import time
from unittest.mock import MagicMock, AsyncMock
from tradingbot.interfaces.telegram.telegram_listener import TelegramListener
from tradingbot.core.orchestrator import OrchestratorBot

@pytest.mark.asyncio
async def test_order_confirmation_flow():
    """Verifica que /buy genere confirmación interactiva y callback ejecute la orden."""
    bot = OrchestratorBot()
    # Mock CCXTConnector and executor
    listener = TelegramListener(bot)
    listener.allowed_chat_id = "12345"

    # 1. Simular mensaje /buy SOL/USDT 0.05
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["SOL/USDT", "0.05"]

    await listener.buy_command(update, context)

    # Verificar que se creó una orden pendiente y se respondió con teclado
    assert len(listener._pending_orders) == 1
    order_key = next(iter(listener._pending_orders.keys()))
    pending = listener._pending_orders[order_key]
    assert pending["symbol"] == "SOL/USDT"
    assert pending["side"] == "BUY"
    assert pending["amount"] == 0.05

    # Verificar llamada a reply_text con mensaje de confirmación
    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Confirmación Requerida" in args[0]
    assert "reply_markup" in kwargs

    # 2. Simular Callback de Cancelación
    query_cancel = MagicMock()
    query_cancel.data = f"order_cancel:{order_key}"
    query_cancel.answer = AsyncMock()
    query_cancel.edit_message_text = AsyncMock()
    cb_update_cancel = MagicMock()
    cb_update_cancel.callback_query = query_cancel
    cb_update_cancel.effective_chat.id = 12345

    await listener.callback_handler(cb_update_cancel, context)
    assert len(listener._pending_orders) == 0
    query_cancel.edit_message_text.assert_called_once()
    assert "cancelada por el usuario" in query_cancel.edit_message_text.call_args[0][0]
