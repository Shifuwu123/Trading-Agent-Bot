"""
agents/speculative_agent.py

SubAgent 3: Especulativo Tier 3
Monedas: BEAMX, MUBARAK (anomalías de alto riesgo)
Configuración: configs/agent_speculative.yaml
Decisión: Inicia en modo PASSIVE (Recomendación #3)
  Control humano sobre activos manipulables por ballenas.
  Activar con /resume_speculative desde Telegram.
"""
from agents.base_agent import BaseAgent
from tradingbot.strategies.ema_crossover import EMACrossoverStrategy
from tradingbot.utils.logger import log


class SpeculativeAgent(BaseAgent):
    """
    SubAgent 3: Especulativo Tier 3

    Operación en timeframes largos (15m) con EMA 21/55.
    Inicia SIEMPRE en modo PASSIVE para control humano.
    Activos con alta manipulación por ballenas.
    Capital: 0% inicial (Escenario B), se activa con Escenario A.
    """

    def _build_strategy(self) -> EMACrossoverStrategy:
        """Construye EMA 21/55 para filtrar ruido especulativo."""
        strategy_cfg = getattr(self.config, "strategies", None)
        if strategy_cfg and hasattr(strategy_cfg, "ema_crossover"):
            ema_cfg = strategy_cfg.ema_crossover
            fast = getattr(ema_cfg, "fast_period", 21)
            slow = getattr(ema_cfg, "slow_period", 55)
        else:
            fast, slow = 21, 55

        log.info(f"[SpeculativeAgent] Estrategia: EMA {fast}/{slow} (modo conservador)")
        return EMACrossoverStrategy(fast_period=fast, slow_period=slow)

    def start(self):
        """Override: fuerza modo PASSIVE independientemente del config."""
        # El Tier 3 SIEMPRE arranca en PASSIVE (Recomendación #3)
        self.config.bot.mode = "passive"
        self.paused = True
        log.info("[SpeculativeAgent] Forzado a modo PASSIVE al inicio (Recomendación #3).")
        super().start()

    def resume(self):
        """Override: notifica al usuario cuando se activa manualmente."""
        super().resume()
        self.notifier.send_message(
            "⚡ <b>SpeculativeAgent Tier 3 ACTIVADO</b>\n\n"
            "El agente especulativo ha sido activado manualmente.\n"
            "Monedas: BEAMX/USDT, MUBARAK/USDT\n"
            "⚠️ <b>Alto riesgo</b> — monitorear de cerca.\n"
            "Para pausar: <code>/pause_speculative</code>"
        )
