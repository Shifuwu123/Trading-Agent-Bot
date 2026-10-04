"""
tradingbot/core/orchestrator.py

OrchestratorBot — Cerebro del sistema multi-agente.

Reemplaza al TradingBot monolítico como proceso raíz.
No opera directamente: lanza, monitorea y coordina los 4 subagentes
especializados que corren en paralelo con capital asignado por pool.

Arquitectura:
    OrchestratorBot
        ├── ScalperAgent (Tier 1)     — 50% capital — SOL/BNB/XRP/SUI/NEAR/DOGE/ADA
        ├── MomentumAgent (Tier 2)    — 40% capital — FET/TAO/WLD/STRK/QNT
        ├── SpeculativeAgent (Tier 3) — 0% inicial (Passive) — BEAMX/MUBARAK
        └── MacroTraderAgent          — 10% capital — BTC/ETH (EMA 50/200)

Decisiones aplicadas (Escenario B):
    - Capital split: 50%/40%/0%/10% (sin Tier 3 activo)
    - SpeculativeAgent: modo PASSIVE hasta comando /resume_speculative
    - MacroTrader: EMA 50/200 con filtro de volumen y zona de ruido
"""

import asyncio
import threading
from datetime import datetime
from typing import Optional

from tradingbot.utils.logger import log
from tradingbot.interfaces.telegram.notifier import TelegramNotifier
from tradingbot.market.ccxt_connector import CCXTConnector
from tradingbot.execution.portfolio_manager import DatabaseSession
from tradingbot.database.models import DigitalWallet
from tradingbot.core.config import get_settings

from agents.scalper_agent import ScalperAgent
from agents.momentum_agent import MomentumAgent
from agents.speculative_agent import SpeculativeAgent
from agents.macro_agent import MacroTraderAgent


class OrchestratorBot:
    """
    Orquestador principal del sistema multi-agente de trading.

    Responsabilidades:
    - Inicializar y configurar los 4 subagentes con su capital asignado
    - Distribuir el capital total según el Escenario B (sin Tier 3 inicial)
    - Proveer comandos de control por subagente (start/stop/pause/resume)
    - Exponer el estado global del sistema para el panel de Telegram
    - Manejar el ciclo de vida completo del sistema

    Capital Split (Escenario B — activo):
        scalper_t1:    50% del capital total
        momentum_t2:   40% del capital total
        macro_btceth:  10% del capital total
        speculative_t3: 0% inicial (PASSIVE, se activa manualmente)
    """

    # Rutas de configuración de cada subagente
    AGENT_CONFIGS = {
        "scalper_t1":     "configs/agent_scalper.yaml",
        "momentum_t2":    "configs/agent_momentum.yaml",
        "speculative_t3": "configs/agent_speculative.yaml",
        "macro_btceth":   "configs/agent_macro.yaml",
    }

    def __init__(self):
        self.settings = get_settings()
        self.notifier = TelegramNotifier()
        self._started_at: Optional[datetime] = None
        self._paused: bool = False  # Estado global del orchestrator

        from tradingbot.core.config import load_yaml_config
        from tradingbot.execution.portfolio_manager import PortfolioManager
        from tradingbot.utils.clp_converter import CLPConverter
        self.config = load_yaml_config("config.yaml")
        self.portfolio_manager = PortfolioManager()
        self.clp_converter = CLPConverter()

        log.info("[Orchestrator] Inicializando OrchestratorBot (Sistema Multi-Agente v1)")

        # Inicializar subagentes
        self.agents = {
            "scalper_t1":     ScalperAgent(self.AGENT_CONFIGS["scalper_t1"]),
            "momentum_t2":    MomentumAgent(self.AGENT_CONFIGS["momentum_t2"]),
            "speculative_t3": SpeculativeAgent(self.AGENT_CONFIGS["speculative_t3"]),
            "macro_btceth":   MacroTraderAgent(self.AGENT_CONFIGS["macro_btceth"]),
        }

        log.info(f"[Orchestrator] {len(self.agents)} subagentes inicializados.")

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool):
        self._paused = value
        for aid, agent in self.agents.items():
            if value:
                agent.pause()
            else:
                if aid == "speculative_t3" and agent.capital_pool_pct == 0.0 and agent._assigned_capital == 0:
                    continue
                agent.resume()
        log.info(f"[Orchestrator] Estado global de pausa cambiado a: {value}")

    # ─────────────────────────────────────────────────────────────────────────
    # Capital Management
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_total_capital(self) -> float:
        """
        Obtiene el capital total disponible (paper trading o real).

        En paper trading: consulta la DigitalWallet del usuario.
        En producción: consulta el balance real de Binance.
        """
        if self.settings.paper_trading:
            try:
                from sqlalchemy import select
                async with DatabaseSession.get_async_session() as session:
                    telegram_id = str(self.settings.telegram_chat_id) or "default"
                    result = await session.execute(
                        select(DigitalWallet).filter(
                            DigitalWallet.telegram_id == telegram_id,
                            DigitalWallet.is_paper == True
                        )
                    )
                    wallet = result.scalars().first()
                    total = float(wallet.balance_usd) if wallet else 20.0
                    log.info(f"[Orchestrator] Capital total (paper): ${total:,.2f} USDT")
                    return total
            except Exception as e:
                log.warning(f"[Orchestrator] Error obteniendo capital paper: {e}")
                return 20.0
        else:
            connector = CCXTConnector()
            try:
                balance = await connector.fetch_balance()
                base = "USDT"
                total = float(balance[base]["free"]) if base in balance else 20.0
                log.info(f"[Orchestrator] Capital total (real): ${total:,.2f} USDT")
                return total
            except Exception as e:
                log.warning(f"[Orchestrator] Error obteniendo capital real: {e}")
                return 20.0
            finally:
                await connector.close()

    async def get_current_capital(self) -> float:
        """Helper para compatibilidad con TelegramListener."""
        return await self._fetch_total_capital()

    @property
    def trade_engine(self):
        """Helper para compatibilidad con TelegramListener: usa el primer subagente disponible."""
        if "scalper_t1" in self.agents:
            return self.agents["scalper_t1"].trade_engine
        return next(iter(self.agents.values())).trade_engine

    def _assign_capital(self, total_capital: float):
        """
        Distribuye el capital total entre los subagentes según Escenario B.

        Escenario B (sin Tier 3 activo):
            scalper_t1:    50% → mayor exposición en el de mejor perfil riesgo/retorno
            momentum_t2:   40% → alto potencial con volatilidad narrativa AI/L2
            speculative_t3: 0% → inicia PASSIVE, se activa manualmente vía Telegram
            macro_btceth:  10% → guardián de valor, pocas operaciones de alta precisión
        """
        capital_split = {
            "scalper_t1":     total_capital * 0.50,
            "momentum_t2":    total_capital * 0.40,
            "speculative_t3": 0.0,   # Tier 3 inicia en PASSIVE sin capital asignado
            "macro_btceth":   total_capital * 0.10,
        }

        for agent_id, capital in capital_split.items():
            self.agents[agent_id].set_capital(capital)

        log.info(
            f"[Orchestrator] Capital distribuido (Escenario B):\n"
            f"  ScalperAgent T1:    ${capital_split['scalper_t1']:,.2f} USDT (50%)\n"
            f"  MomentumAgent T2:   ${capital_split['momentum_t2']:,.2f} USDT (40%)\n"
            f"  SpeculativeAgent T3: $0.00 USDT (0% — PASSIVE)\n"
            f"  MacroTrader BTC/ETH: ${capital_split['macro_btceth']:,.2f} USDT (10%)"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start_all(self):
        """
        Inicia el sistema completo:
        1. Obtiene capital total
        2. Distribuye capital entre subagentes
        3. Arranca cada subagente en su propio thread
        """
        self._started_at = datetime.utcnow()
        log.info("[Orchestrator] === INICIANDO SISTEMA MULTI-AGENTE ===")

        # Obtener capital y distribuir
        total_capital = asyncio.run(self._fetch_total_capital())
        self._assign_capital(total_capital)

        # Notificación de arranque
        self.notifier.send_message(
            "🚀 <b>Sistema Multi-Agente iniciado</b>\n\n"
            f"💰 Capital total: <b>${total_capital:,.2f} USDT</b>\n\n"
            "📊 <b>Distribución (Escenario B):</b>\n"
            f"  • ScalperAgent T1: ${total_capital*0.50:,.2f} (50%)\n"
            f"  • MomentumAgent T2: ${total_capital*0.40:,.2f} (40%)\n"
            f"  • MacroTrader BTC/ETH: ${total_capital*0.10:,.2f} (10%)\n"
            f"  • SpeculativeAgent T3: $0 (PASSIVE — activar con /resume_speculative)\n\n"
            "Use /status para ver el estado global."
        )

        # Arrancar cada subagente en thread independiente
        for agent_id, agent in self.agents.items():
            thread = threading.Thread(
                target=agent.start,
                name=f"agent-{agent_id}",
                daemon=True
            )
            thread.start()
            log.info(f"[Orchestrator] Thread iniciado para {agent_id}")

        log.info("[Orchestrator] === TODOS LOS SUBAGENTES EN EJECUCIÓN ===")

    def stop_all(self):
        """Detiene todos los subagentes limpiamente."""
        log.info("[Orchestrator] Deteniendo todos los subagentes...")
        for agent_id, agent in self.agents.items():
            try:
                agent.stop()
                log.info(f"[Orchestrator] {agent_id} detenido.")
            except Exception as e:
                log.error(f"[Orchestrator] Error deteniendo {agent_id}: {e}")

        self.notifier.send_message("🛑 <b>Sistema Multi-Agente detenido.</b>")

    # ─────────────────────────────────────────────────────────────────────────
    # Per-Agent Control
    # ─────────────────────────────────────────────────────────────────────────

    def stop_agent(self, agent_id: str):
        """Detiene un subagente específico sin afectar el resto."""
        if agent_id not in self.agents:
            log.warning(f"[Orchestrator] Agent '{agent_id}' no encontrado.")
            return
        self.agents[agent_id].stop()
        log.info(f"[Orchestrator] {agent_id} detenido manualmente.")

    def pause_agent(self, agent_id: str):
        """Pausa un subagente (mantiene scheduler activo, omite ejecuciones)."""
        if agent_id not in self.agents:
            return
        self.agents[agent_id].pause()

    def resume_agent(self, agent_id: str):
        """
        Reactiva un subagente pausado.
        Para SpeculativeAgent T3: asigna su capital (10%) antes de reanudar.
        """
        if agent_id not in self.agents:
            return

        # Si es Tier 3 y capital es 0, asignar capital del pool
        if agent_id == "speculative_t3" and self.agents[agent_id]._assigned_capital == 0:
            total = asyncio.run(self._fetch_total_capital())
            speculative_capital = total * 0.10
            self.agents[agent_id].set_capital(speculative_capital)
            log.info(
                f"[Orchestrator] SpeculativeAgent T3 activado con "
                f"${speculative_capital:,.2f} USDT (10% del capital total)"
            )

        self.agents[agent_id].resume()

    async def execute_manual_order(self, symbol: str, side: str, amount: float):
        """
        Ejecuta una orden manual (/buy o /sell) y la concilia en la base de datos
        asociándola al subagente que cubre el par (o 'manual').
        """
        from tradingbot.execution.order_executor import OrderExecutor
        from tradingbot.database.models import Trade
        from sqlalchemy import select

        connector = CCXTConnector()
        executor = OrderExecutor(connector)
        try:
            res = await executor.execute_order(symbol, side, amount, "MARKET")

            target_agent_id = "manual"
            for aid, agent in self.agents.items():
                if symbol in agent.config.bot.trading_pairs:
                    target_agent_id = aid
                    break

            async with DatabaseSession.get_async_session() as session:
                opposite_side = "BUY" if side == "SELL" else "SELL"
                result = await session.execute(
                    select(Trade).filter(
                        Trade.symbol == symbol,
                        Trade.status == "OPEN",
                        Trade.side == opposite_side
                    )
                )
                open_trades = result.scalars().all()

            if open_trades and side == "SELL":
                remaining = amount
                for ot in open_trades:
                    if remaining <= 0:
                        break
                    await self.portfolio_manager.record_close_trade_async(ot.trade_id, res)
                    remaining -= float(ot.quantity)
            else:
                await self.portfolio_manager.record_open_trade_async(
                    res,
                    strategy=f"MANUAL_{side}",
                    agent_id=target_agent_id
                )
            return res
        finally:
            await connector.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Status & Reporting
    # ─────────────────────────────────────────────────────────────────────────

    def get_global_status(self) -> dict:
        """
        Retorna el estado global del sistema para el panel de Telegram.
        Incluye estado de cada subagente, capital asignado y ciclos ejecutados.
        """
        status = {
            "orchestrator_started_at": self._started_at.isoformat() if self._started_at else None,
            "total_agents": len(self.agents),
            "agents": {},
        }
        for agent_id, agent in self.agents.items():
            try:
                status["agents"][agent_id] = agent.get_status()
            except Exception as e:
                status["agents"][agent_id] = {"error": str(e)}

        return status

    def format_global_status_message(self) -> str:
        """Genera el mensaje de Telegram con el panel global del sistema."""
        status = self.get_global_status()
        uptime = ""
        if self._started_at:
            delta = datetime.utcnow() - self._started_at
            hours, rem = divmod(int(delta.total_seconds()), 3600)
            mins, secs = divmod(rem, 60)
            uptime = f"{hours}h {mins}m {secs}s"

        lines = [
            "🧠 <b>Sistema Multi-Agente — Estado Global</b>",
            f"⏱️ Uptime: <code>{uptime}</code>\n",
        ]

        icons = {
            "scalper_t1":     "📡",
            "momentum_t2":    "🚀",
            "speculative_t3": "⚠️",
            "macro_btceth":   "🐋",
        }

        for agent_id, agent_status in status["agents"].items():
            if "error" in agent_status:
                lines.append(f"{icons.get(agent_id, '❓')} <b>{agent_id}</b>: ❌ Error")
                continue

            mode_emoji = "🟢" if agent_status["mode"] == "ACTIVE" else "⏸️"
            capital = agent_status.get("assigned_capital_usd", 0)
            cycles = agent_status.get("cycle_count", 0)
            pairs = ", ".join(agent_status.get("pairs", []))
            tf = agent_status.get("timeframe", "?")
            positions = agent_status.get("open_positions", 0)

            lines.append(
                f"{icons.get(agent_id, '❓')} <b>{agent_status['agent_name']}</b>\n"
                f"   {mode_emoji} {agent_status['mode']} | 💵 ${capital:,.0f} | "
                f"🔄 {cycles} ciclos | 📂 {positions} pos\n"
                f"   📊 {tf} | {pairs}"
            )

        lines.append("\n<i>Use /status_scalper, /status_momentum, /status_macro para detalle.</i>")
        return "\n".join(lines)
