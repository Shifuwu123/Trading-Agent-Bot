"""
agents/momentum_agent.py

SubAgent 2: Momentum Tier 2
Monedas: FET, TAO, WLD, STRK, QNT (AI + Layer 2 narratives)
Configuración: configs/agent_momentum.yaml
"""
from agents.base_agent import BaseAgent
from tradingbot.strategies.ema_crossover import EMACrossoverStrategy
from tradingbot.utils.logger import log


class MomentumAgent(BaseAgent):
    """
    SubAgent 2: Momentum Tier 2

    Operación en timeframes medios (5m/15m) con EMA 9/21.
    Enfocado en activos de narrativa AI y Layer 2 de alta volatilidad.
    Modo TARGET: solo cierra en ganancias, no corta por señal de reversión.
    Capital: 40% del total (Escenario B).
    """

    def _build_strategy(self) -> EMACrossoverStrategy:
        """Construye EMA 9/21 para momentum en timeframes medios."""
        strategy_cfg = getattr(self.config, "strategies", None)
        if strategy_cfg and hasattr(strategy_cfg, "ema_crossover"):
            ema_cfg = strategy_cfg.ema_crossover
            fast = getattr(ema_cfg, "fast_period", 9)
            slow = getattr(ema_cfg, "slow_period", 21)
        else:
            fast, slow = 9, 21

        log.info(f"[MomentumAgent] Estrategia: EMA {fast}/{slow}")
        return EMACrossoverStrategy(fast_period=fast, slow_period=slow)
