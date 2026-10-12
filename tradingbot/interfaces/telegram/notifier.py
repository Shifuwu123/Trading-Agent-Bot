import html
import requests
from typing import Optional, Dict, Any
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log, sanitize_sensitive_data

class TelegramNotifier:
    """
    Notificador institucional para la API de Telegram Bot con blindaje total:
    - Escapado HTML riguroso para evitar errores de entidad XML.
    - Truncamiento inteligente bajo el límite de 4096 caracteres (margen de 3800).
    - Mecanismo de Fallback automático a texto plano en caso de HTTP 400 Bad Request.
    - Sanitización de credenciales y secretos en payloads y tracebacks.
    """
    MAX_MESSAGE_LENGTH = 3800  # Margen de seguridad sobre el límite de 4096

    def __init__(self):
        settings = get_settings()
        import os
        self.bot_token = getattr(settings, 'telegram_bot_token', os.getenv('TELEGRAM_BOT_TOKEN', ''))
        self.chat_id = getattr(settings, 'telegram_chat_id', os.getenv('TELEGRAM_CHAT_ID', ''))

        if not self.bot_token or not self.chat_id:
            log.warning("Telegram bot token or chat ID is missing. Notifications will not be sent.")

    def send_message(self, text: str, parse_mode: Optional[str] = "HTML") -> bool:
        if not self.bot_token or not self.chat_id:
            return False

        if not text:
            return False

        text_str = str(text)
        if len(text_str) > self.MAX_MESSAGE_LENGTH:
            truncated_text = text_str[:self.MAX_MESSAGE_LENGTH] + "\n... [Mensaje truncado por límite de tamaño]"
        else:
            truncated_text = text_str

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": truncated_text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except requests.HTTPError as he:
            error_detail = getattr(he.response, "text", "")
            log.warning(f"Telegram HTTP {he.response.status_code}: {sanitize_sensitive_data(error_detail)}")

            # Fallback automático a texto plano si Telegram rechaza entidades HTML
            if parse_mode == "HTML":
                log.info("Reintentando notificación en modo texto plano (fallback seguro)...")
                plain_payload = {
                    "chat_id": self.chat_id,
                    "text": sanitize_sensitive_data(truncated_text),
                }
                try:
                    retry_res = requests.post(url, json=plain_payload, timeout=10)
                    retry_res.raise_for_status()
                    return True
                except Exception as retry_err:
                    log.error(f"Fallo definitivo en fallback de Telegram: {sanitize_sensitive_data(str(retry_err))}")
                    return False
            return False
        except Exception as e:
            log.error(f"Failed to send Telegram message: {sanitize_sensitive_data(str(e))}")
            return False

    def send_trade_alert(self, trade_details: dict, capital_clp: float = None):
        """
        trade_details dictionary containing: symbol, side, amount, price, fee_usd, etc.
        """
        symbol = trade_details.get("symbol", "UNKNOWN")
        side = trade_details.get("side", "UNKNOWN")
        amount = trade_details.get("amount", 0)
        price = trade_details.get("price", 0)

        base_coin = symbol.split('/')[0] if '/' in symbol else ""
        quote_coin = symbol.split('/')[1] if '/' in symbol else "USDT"

        if "reason" in trade_details:
            msg = f"🔔 <b>Trade Closed ({html.escape(str(trade_details['reason']))})</b> 🔔\n\n"
            msg += f"<b>Symbol:</b> {html.escape(symbol)}\n"
            msg += f"<b>Side:</b> {html.escape(side)}\n"
            msg += f"<b>Amount:</b> {amount} {html.escape(base_coin)}\n"
            msg += f"<b>Price:</b> {price} {html.escape(quote_coin)}\n"

            pnl_usd = trade_details.get("pnl_usd", 0.0)
            pnl_pct = trade_details.get("pnl_pct", 0.0)
            fee_usd = trade_details.get("fee_usd")
            pnl_net_usd = trade_details.get("pnl_net_usd")
            pnl_clp = trade_details.get("pnl_clp")

            emoji = "🟢" if pnl_usd >= 0 else "🔴"
            msg += f"<b>PnL Bruto:</b> {emoji} ${pnl_usd:.2f} USD ({pnl_pct*100:.2f}%)\n"
            if fee_usd is not None and pnl_net_usd is not None:
                net_emoji = "🟢" if pnl_net_usd >= 0 else "🔴"
                msg += f"<b>Comisión Est.:</b> ${fee_usd:.4f} USD\n"
                msg += f"<b>PnL Neto:</b> {net_emoji} ${pnl_net_usd:.2f} USD\n"
            if pnl_clp is not None:
                msg += f"<b>PnL Neto CLP:</b> ${pnl_clp:,.0f} CLP\n"
        else:
            msg = "🚨 <b>Trade Executed</b> 🚨\n\n"
            msg += f"<b>Symbol:</b> {html.escape(symbol)}\n"
            msg += f"<b>Side:</b> {html.escape(side)}\n"
            msg += f"<b>Amount:</b> {amount} {html.escape(base_coin)}\n"
            msg += f"<b>Price:</b> {price} {html.escape(quote_coin)}\n"

        if capital_clp is not None:
            msg += f"\n<b>Estimated Capital:</b> ${capital_clp:,.0f} CLP"

        self.send_message(msg, parse_mode="HTML")

    def send_error_alert(self, error_msg: Any):
        """Envía una alerta crítica a Telegram sanitizando trazas y escapando HTML."""
        sanitized = sanitize_sensitive_data(str(error_msg))
        safe_msg = html.escape(sanitized)
        max_pre_len = self.MAX_MESSAGE_LENGTH - 100
        if len(safe_msg) > max_pre_len:
            safe_msg = safe_msg[:max_pre_len] + "\n... [Traceback truncado]"
        msg = f"⚠️ <b>CRITICAL ERROR</b> ⚠️\n\n<pre>{safe_msg}</pre>"
        self.send_message(msg, parse_mode="HTML")
