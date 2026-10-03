"""
Re-export TelegramListener for backward compatibility with older imports.
"""
from tradingbot.interfaces.telegram.telegram_listener import TelegramListener

__all__ = ["TelegramListener"]
