"""
tradingbot/utils/notifier.py

Re-export TelegramNotifier from tradingbot.interfaces.telegram.notifier
para garantizar una única implementación institucional blindada con:
- Escapado HTML riguroso y fallback a texto plano.
- Truncamiento bajo límite de 4096 caracteres.
- Sanitización de secretos.
"""

from tradingbot.interfaces.telegram.notifier import TelegramNotifier

__all__ = ["TelegramNotifier"]
