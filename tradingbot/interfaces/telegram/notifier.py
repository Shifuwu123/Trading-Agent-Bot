import requests
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log

class TelegramNotifier:
    def __init__(self):
        settings = get_settings()
        # Get from settings, fallback to standard os.getenv if missing in EnvSettings
        import os
        self.bot_token = getattr(settings, 'telegram_bot_token', os.getenv('TELEGRAM_BOT_TOKEN', ''))
        self.chat_id = getattr(settings, 'telegram_chat_id', os.getenv('TELEGRAM_CHAT_ID', ''))
        
        if not self.bot_token or not self.chat_id:
            log.warning("Telegram bot token or chat ID is missing. Notifications will not be sent.")

    def send_message(self, text: str):
        if not self.bot_token or not self.chat_id:
            return
            
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            log.error(f"Failed to send Telegram message: {e}")

    def send_trade_alert(self, trade_details: dict, capital_clp: float = None):
        """
        trade_details dictionary containing: symbol, side, amount, price
        """
        symbol = trade_details.get("symbol", "UNKNOWN")
        side = trade_details.get("side", "UNKNOWN")
        amount = trade_details.get("amount", 0)
        price = trade_details.get("price", 0)
        
        base_coin = symbol.split('/')[0] if '/' in symbol else ""
        quote_coin = symbol.split('/')[1] if '/' in symbol else "USDT"
        
        if "reason" in trade_details:
            msg = f"🔔 <b>Trade Closed ({trade_details['reason']})</b> 🔔\n\n"
            msg += f"<b>Symbol:</b> {symbol}\n"
            msg += f"<b>Side:</b> {side}\n"
            msg += f"<b>Amount:</b> {amount} {base_coin}\n"
            msg += f"<b>Price:</b> {price} {quote_coin}\n"
            
            pnl_usd = trade_details.get("pnl_usd", 0.0)
            pnl_pct = trade_details.get("pnl_pct", 0.0)
            emoji = "🟢" if pnl_usd >= 0 else "🔴"
            msg += f"<b>PnL:</b> {emoji} ${pnl_usd:.2f} USD ({pnl_pct*100:.2f}%)\n"
        else:
            msg = f"🚨 <b>Trade Executed</b> 🚨\n\n"
            msg += f"<b>Symbol:</b> {symbol}\n"
            msg += f"<b>Side:</b> {side}\n"
            msg += f"<b>Amount:</b> {amount} {base_coin}\n"
            msg += f"<b>Price:</b> {price} {quote_coin}\n"
        
        if capital_clp is not None:
            msg += f"\n<b>Estimated Capital:</b> ${capital_clp:,.0f} CLP"
            
        self.send_message(msg)

    def send_error_alert(self, error_msg: str):
        import html
        safe_msg = html.escape(error_msg)
        msg = f"⚠️ <b>CRITICAL ERROR</b> ⚠️\n\n"
        msg += f"<pre>{safe_msg}</pre>"
        self.send_message(msg)
