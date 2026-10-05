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
        """Inicia el subagente especulativo respetando el modo configurado."""
        mode = getattr(self.config.bot, "mode", "passive").lower()
        if mode == "active":
            self.paused = False
            log.info("[SpeculativeAgent] Modo ACTIVE configurado al inicio.")
        else:
            self.config.bot.mode = "passive"
            self.paused = True
            log.info("[SpeculativeAgent] Modo PASSIVE configurado al inicio.")
        super().start()

    def resume(self):
        """Override: reactiva el agente y notifica al usuario."""
        super().resume()
        self.config.bot.mode = "active"
        self.notifier.send_message(
            "⚡ <b>SpeculativeAgent Tier 3 ACTIVADO</b>\n\n"
            "El agente especulativo ha sido activado.\n"
            "Monedas: BEAMX/USDT, MUBARAK/USDT\n"
            "⚠️ <b>Alto riesgo</b> — monitorear de cerca.\n"
            "Para pausar: <code>/pause_speculative</code>"
        )

    def pause(self):
        """Override: pausa el agente especulativo y notifica."""
        super().pause()
        self.config.bot.mode = "passive"
        self.notifier.send_message(
            "⏸️ <b>SpeculativeAgent Tier 3 PAUSADO</b>\n\n"
            "El agente especulativo ha sido pausado (modo PASSIVE).\n"
            "Para reactivar: <code>/resume_speculative</code>"
        )
