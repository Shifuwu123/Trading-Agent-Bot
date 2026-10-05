"""
agents/macro_agent.py

SubAgent 4: Macro Trader BTC/ETH
Monedas: BTC/USDT, ETH/USDT
Configuración: configs/agent_macro.yaml
Decisión: EMA 50/200 — Golden/Death Cross institucional (Recomendación #4)
  Alta precisión (~65-70% TP alcanzado), pocas comisiones (~2-5 señales/mes)
"""
from agents.base_agent import BaseAgent
from tradingbot.strategies.ema_macro import EMAMacroStrategy
from tradingbot.utils.logger import log


class MacroTraderAgent(BaseAgent):
    """
    SubAgent 4: Macro Trader BTC/ETH

    Operación en timeframes largos (15m/1h) con EMA 50/200.
    Golden/Death Cross institucional para BTC y ETH.
    Modo TREND: corta pérdidas rápido siguiendo tendencia macro.
    Capital: 10% del total (ambos escenarios).
    """

    def _build_strategy(self) -> EMAMacroStrategy:
        """Construye EMA 50/200 con filtros de volumen y ruido."""
        strategy_cfg = getattr(self.config, "strategies", None)
        if strategy_cfg and hasattr(strategy_cfg, "ema_macro"):
            macro_cfg = strategy_cfg.ema_macro
            fast = getattr(macro_cfg, "fast_period", 50)
            slow = getattr(macro_cfg, "slow_period", 200)
            volume_filter = getattr(macro_cfg, "volume_filter", True)
        else:
            fast, slow, volume_filter = 50, 200, True

        log.info(f"[MacroTraderAgent] Estrategia: EMA {fast}/{slow} | Volume filter: {volume_filter}")
        return EMAMacroStrategy(
            fast_period=fast,
            slow_period=slow,
            volume_filter=volume_filter,
        )
