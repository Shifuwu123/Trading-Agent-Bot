"""
agents/scalper_agent.py

SubAgent 1: Scalper Tier 1
Monedas: SOL, BNB, XRP (anclas) + SUI, NEAR, DOGE, ADA (momentum)
Configuración: configs/agent_scalper.yaml
Decisión: Opción A — Portafolio Equilibrado (Recomendación #1)
"""
from agents.base_agent import BaseAgent
from tradingbot.strategies.ema_crossover import EMACrossoverStrategy
from tradingbot.utils.logger import log


class ScalperAgent(BaseAgent):
    """
    SubAgent 1: Scalper Tier 1

    Operación en timeframes cortos (1m/5m) con EMA 9/21.
    Mezcla activos ancla de alta liquidez con momentum leaders.
    Capital: 50% del total (Escenario B).
    """

    def _build_strategy(self) -> EMACrossoverStrategy:
        """Construye EMA 9/21 para scalping en timeframes cortos."""
        strategy_cfg = getattr(self.config, "strategies", None)
        if strategy_cfg and hasattr(strategy_cfg, "ema_crossover"):
            ema_cfg = strategy_cfg.ema_crossover
            fast = getattr(ema_cfg, "fast_period", 9)
            slow = getattr(ema_cfg, "slow_period", 21)
        else:
            fast, slow = 9, 21

        log.info(f"[ScalperAgent] Estrategia: EMA {fast}/{slow}")
        return EMACrossoverStrategy(fast_period=fast, slow_period=slow)
