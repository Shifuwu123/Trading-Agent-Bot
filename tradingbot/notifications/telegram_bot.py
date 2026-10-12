"""
tradingbot/notifications/telegram_bot.py

Módulo legado de notificaciones por Telegram.
La implementación institucional activa se encuentra en tradingbot.interfaces.telegram.notifier.TelegramNotifier.
"""
from tradingbot.interfaces.telegram.notifier import TelegramNotifier

__all__ = ["TelegramNotifier"]
