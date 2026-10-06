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
        Obtiene el patrimonio neto total disponible (paper trading o real).
        En paper trading: Efectivo disponible + Valor de posiciones abiertas.
        En producción: Saldo total de la cuenta en el exchange.
        """
        try:
            total = await self.portfolio_manager.get_total_equity_async()
            log.info(f"[Orchestrator] Patrimonio neto total: ${total:,.2f} USDT")
            return total
        except Exception as e:
            log.warning(f"[Orchestrator] Error obteniendo capital total: {e}")
            return 50.0

    async def get_current_capital(self) -> float:
        """Helper para compatibilidad con TelegramListener."""
        return await self._fetch_total_capital()

    @property
    def trade_engine(self):
        """Helper para compatibilidad con TelegramListener: usa el primer subagente disponible."""
        if "scalper_t1" in self.agents:
            return self.agents["scalper_t1"].trade_engine
        return next(iter(self.agents.values())).trade_engine

    def _is_speculative_active(self) -> bool:
        """Determina si SpeculativeAgent Tier 3 está activo y listo para recibir capital."""
        spec = self.agents.get("speculative_t3")
        if not spec:
            return False
        return not spec.paused and getattr(spec.config.bot, "mode", "passive").lower() == "active"

    def _assign_capital(self, total_capital: float, scenario_a: bool = None):
        """
        Distribuye el capital total entre los subagentes basado en la matriz de monedas ($1 USD por par).

        Matriz Base (16 monedas):
            scalper_t1:     7 monedas (7/16 = 43.75% -> $7.00 en base $16)
            momentum_t2:    5 monedas (5/16 = 31.25% -> $5.00 en base $16)
            macro_btceth:   2 monedas (2/16 = 12.50% -> $2.00 en base $16)
            speculative_t3: 2 monedas (2/16 = 12.50% -> $2.00 en base $16)
        """
        if scenario_a is None:
            scenario_a = self._is_speculative_active()

        if scenario_a:
            capital_split = {
                "scalper_t1":     total_capital * 0.45,
                "momentum_t2":    total_capital * 0.35,
                "macro_btceth":   total_capital * 0.10,
                "speculative_t3": total_capital * 0.10,
            }
            scenario_name = "Escenario A (Speculative ACTIVO)"
        else:
            capital_split = {
                "scalper_t1":     total_capital * 0.50,
                "momentum_t2":    total_capital * 0.40,
                "macro_btceth":   total_capital * 0.10,
                "speculative_t3": 0.0,
            }
            scenario_name = "Escenario B (Speculative PASSIVE)"

        for agent_id, capital in capital_split.items():
            if agent_id in self.agents:
                self.agents[agent_id].set_capital(capital)

        log.info(
            f"[Orchestrator] Capital distribuido ({scenario_name}):\n"
            f"  ScalperAgent T1:    ${capital_split.get('scalper_t1', 0):,.2f} USDT\n"
            f"  MomentumAgent T2:   ${capital_split.get('momentum_t2', 0):,.2f} USDT\n"
            f"  SpeculativeAgent T3: ${capital_split.get('speculative_t3', 0):,.2f} USDT\n"
            f"  MacroTrader BTC/ETH: ${capital_split.get('macro_btceth', 0):,.2f} USDT"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self):
        """Inicia todos los subagentes (alias de start_all para compatibilidad)."""
        self.start_all()

    def stop(self):
        """Detiene todos los subagentes (alias de stop_all para compatibilidad)."""
        self.stop_all()

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
        is_spec_active = self._is_speculative_active()
        self._assign_capital(total_capital, scenario_a=is_spec_active)

        scenario_label = "Escenario A" if is_spec_active else "Escenario B"
        spec_desc = (
            f"${total_capital*0.10:,.2f} (10% — 🟢 ACTIVO)"
            if is_spec_active
            else "$0 (PASSIVE — activar con /resume_speculative)"
        )
        scalper_desc = f"${self.agents['scalper_t1']._assigned_capital:,.2f} ({int(self.agents['scalper_t1'].capital_pool_pct*100)}%)" if 'scalper_t1' in self.agents else ""
        momentum_desc = f"${self.agents['momentum_t2']._assigned_capital:,.2f} ({int(self.agents['momentum_t2'].capital_pool_pct*100)}%)" if 'momentum_t2' in self.agents else ""
        macro_desc = f"${self.agents['macro_btceth']._assigned_capital:,.2f} ({int(self.agents['macro_btceth'].capital_pool_pct*100)}%)" if 'macro_btceth' in self.agents else ""

        # Notificación de arranque
        self.notifier.send_message(
            "🚀 <b>Sistema Multi-Agente iniciado</b>\n\n"
            f"💰 Capital total: <b>${total_capital:,.2f} USDT</b>\n\n"
            f"📊 <b>Distribución ({scenario_label}):</b>\n"
            f"  • ScalperAgent T1: {scalper_desc}\n"
            f"  • MomentumAgent T2: {momentum_desc}\n"
            f"  • MacroTrader BTC/ETH: {macro_desc}\n"
            f"  • SpeculativeAgent T3: {spec_desc}\n\n"
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

    async def pause_agent(self, agent_id: str) -> dict:
        """Pausa un subagente (mantiene scheduler activo, omite ejecuciones)."""
        if agent_id not in self.agents:
            return {}
        self.agents[agent_id].pause()
        if agent_id == "speculative_t3":
            total = await self._fetch_total_capital()
            self._assign_capital(total, scenario_a=False)
            log.info("[Orchestrator] SpeculativeAgent T3 pausado. Capital redistribuido a Escenario B.")
        return self.agents[agent_id].get_status()

    async def resume_agent(self, agent_id: str) -> dict:
        """
        Reactiva un subagente pausado.
        Para SpeculativeAgent T3: rebalancea el capital a Escenario A (10%).
        """
        if agent_id not in self.agents:
            return {}

        self.agents[agent_id].resume()

        # Si se reactiva Tier 3, rebalancear a Escenario A
        if agent_id == "speculative_t3":
            total = await self._fetch_total_capital()
            self._assign_capital(total, scenario_a=True)
            spec_cap = total * 0.10
            log.info(
                f"[Orchestrator] SpeculativeAgent T3 activado. Capital rebalanceado a Escenario A "
                f"(${spec_cap:,.2f} USDT / 10% de ${total:,.2f})"
            )

        return self.agents[agent_id].get_status()

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
        started = getattr(self, "_started_at", None)
        status = {
            "orchestrator_started_at": started.isoformat() if started else None,
            "total_agents": len(getattr(self, "agents", {})),
            "agents": {},
        }
        for agent_id, agent in self.agents.items():
            try:
                status["agents"][agent_id] = agent.get_status()
            except Exception as e:
                status["agents"][agent_id] = {"error": str(e)}

        return status

    def format_global_status_message(self, capital_usd: float = None, capital_clp: float = None) -> str:
        """Genera el mensaje de Telegram con el panel global y detallado de cada subagente."""
        status = self.get_global_status()
        state = "Pausado ⏸️" if self.paused else "Corriendo ▶️"

        if capital_usd is None:
            try:
                capital_usd = asyncio.run(self._fetch_total_capital())
            except Exception:
                capital_usd = 50.0
        if capital_clp is None:
            capital_clp = self.clp_converter.convert_usd_to_clp(capital_usd)

        total_open_positions = 0
        active_agents = 0
        for agent_status in status["agents"].values():
            if not isinstance(agent_status, dict) or "error" in agent_status:
                continue
            total_open_positions += agent_status.get("open_positions_count", 0)
            if agent_status.get("mode") == "ACTIVE":
                active_agents += 1

        lines = [
            "📊 <b>Estado del Bot (Multi-Agente)</b>\n",
            f"• <b>Estado Global:</b> {state}",
            f"• <b>Capital Estimado:</b> ${capital_usd:,.2f} USD <i>(${capital_clp:,.0f} CLP)</i>",
            f"• <b>Posiciones Abiertas:</b> {total_open_positions}",
            f"• <b>Agentes Activos:</b> {active_agents} / {len(self.agents)}\n",
        ]

        icons = {
            "scalper_t1":     "⚡",
            "momentum_t2":    "🚀",
            "macro_btceth":   "🐋",
            "speculative_t3": "⚠️",
        }

        for agent_id, agent_status in status["agents"].items():
            if "error" in agent_status:
                lines.append(f"━━━━━━━━━━━━━━━━━━━\n{icons.get(agent_id, '❓')} <b>{agent_id}</b>: ❌ Error: {agent_status['error']}")
                continue

            icon = icons.get(agent_id, "🤖")
            agent_name = agent_status.get("agent_name", agent_id)
            mode = agent_status.get("mode", "ACTIVE")
            mode_tag = "🟢 ACTIVO" if mode == "ACTIVE" else "⏸️ PASSIVE"
            strat_mode = agent_status.get("trading_mode", "trend").upper()
            tf = agent_status.get("current_timeframe", agent_status.get("timeframe", "?"))
            capital = agent_status.get("assigned_capital_usd", 0.0)
            cap_pct = int(agent_status.get("capital_pool_pct", 0.0) * 100)

            raw_pairs = agent_status.get("pairs", [])
            pairs_short = ", ".join([p.split("/")[0] for p in raw_pairs])

            # Operando
            open_pos_list = agent_status.get("open_positions", [])
            pos_desc_list = []
            for op in open_pos_list:
                sym = op.get("symbol", "")
                qty = op.get("quantity", 0.0)
                entry_px = op.get("entry_price", 0.0)
                u_pnl = op.get("unrealized_pnl", 0.0)
                u_pct = op.get("unrealized_pnl_pct", 0.0)
                pnl_sign = "+" if u_pnl >= 0 else ""
                pos_desc_list.append(
                    f"{sym} ({qty:.4f} @ ${entry_px:,.2f} | Flotante: {pnl_sign}${u_pnl:,.2f} / {pnl_sign}{u_pct:.2f}%)"
                )

            # Ganado / Perdido
            realized_pnl = agent_status.get("realized_pnl_usd", 0.0)
            unrealized_pnl = agent_status.get("unrealized_pnl_usd", 0.0)
            total_pnl = agent_status.get("total_pnl_usd", 0.0)
            closed_count = agent_status.get("closed_trades_count", 0)
            win_count = agent_status.get("winning_trades", 0)
            loss_count = agent_status.get("losing_trades", 0)

            t_sign = "+" if total_pnl > 0 else ""
            r_sign = "+" if realized_pnl > 0 else ""
            u_sign = "+" if unrealized_pnl > 0 else ""

            if closed_count > 0:
                pnl_line = (
                    f"• <b>Ganado/Perdido:</b> {t_sign}${total_pnl:,.2f} USD "
                    f"<i>(Realizado: {r_sign}${realized_pnl:,.2f} [{win_count}W/{loss_count}L] | Flotante: {u_sign}${unrealized_pnl:,.2f})</i>"
                )
            else:
                pnl_line = (
                    f"• <b>Ganado/Perdido:</b> {t_sign}${total_pnl:,.2f} USD "
                    f"<i>(Realizado: $0.00 | Flotante: {u_sign}${unrealized_pnl:,.2f})</i>"
                )

            # Evaluaciones
            cycles = agent_status.get("cycle_count", 0)
            total_evals = agent_status.get("total_evaluations", 0)
            eval_counts = agent_status.get("eval_counts", {})

            lines.append("━━━━━━━━━━━━━━━━━━━")
            lines.append(f"{icon} <b>{agent_name}</b> ({mode_tag})")

            # 1. Operando
            if mode == "PASSIVE":
                if agent_id == "speculative_t3":
                    operando_desc = "⚪ Inactivo (Activar con /resume_speculative)"
                else:
                    operando_desc = "⏸️ Pausado (Modo PASSIVE)"
            elif not pos_desc_list:
                operando_desc = "⚪ En liquidez (Sin posiciones)"
            else:
                operando_desc = "🟢 " + ", ".join(pos_desc_list)
            lines.append(f"• <b>Operando:</b> {operando_desc}")

            # 2. Ganado / Perdido
            lines.append(pnl_line)

            # 3. Evaluaciones
            if mode == "PASSIVE" or total_evals == 0:
                lines.append("• <b>Evaluaciones:</b> 0")
            else:
                lines.append(f"• <b>Evaluaciones:</b> {total_evals:,} en {cycles} ciclos")

        lines.append("\n💡 <i>Para ver pares, estrategia y detalle de un agente, usa los botones abajo o /status_&lt;agente&gt;.</i>")
        return "\n".join(lines)

    def format_agent_detail_message(self, agent_id: str) -> str:
        """Genera el mensaje detallado para un subagente individual."""
        if agent_id not in self.agents:
            return f"❌ Agente <code>{agent_id}</code> no encontrado."

        agent = self.agents[agent_id]
        status = agent.get_status()

        icons = {
            "scalper_t1":     "⚡",
            "momentum_t2":    "🚀",
            "macro_btceth":   "🐋",
            "speculative_t3": "⚠️",
        }
        icon = icons.get(agent_id, "🤖")
        mode = status.get("mode", "ACTIVE")
        mode_tag = "🟢 ACTIVO" if mode == "ACTIVE" else "⏸️ PASSIVE"
        strat_mode = status.get("trading_mode", "trend").upper()
        tf = status.get("current_timeframe", status.get("timeframe", "?"))
        capital = status.get("assigned_capital_usd", 0.0)
        cap_pct = int(status.get("capital_pool_pct", 0.0) * 100)

        lines = [
            f"{icon} <b>Detalle del Sub-Agente: {status.get('agent_name', agent_id)}</b>\n",
            f"• <b>Estado:</b> {mode_tag}",
            f"• <b>Estrategia:</b> <code>{strat_mode}</code>",
            f"• <b>Timeframe:</b> <code>{tf}</code>",
            f"• <b>Capital Asignado:</b> ${capital:,.2f} USDT ({cap_pct}% del total)",
            f"• <b>Ciclos Ejecutados:</b> {status.get('cycle_count', 0):,}\n",
            "📋 <b>Pares Asignados:</b>",
        ]

        from tradingbot.database.models import Portfolio
        from tradingbot.execution.portfolio_manager import DatabaseSession
        session = DatabaseSession.get_session()
        try:
            portfolio_map = {p.asset: float(p.current_price or 0.0) for p in session.query(Portfolio).all()}
            for p in status.get("pairs", []):
                base = p.split("/")[0]
                px = portfolio_map.get(base, 0.0)
                px_str = f"${px:,.4f}" if px > 0 else "N/A"
                lines.append(f"  • <code>{p}</code>: {px_str}")
        finally:
            session.close()

        open_pos = status.get("open_positions", [])
        lines.append(f"\n📂 <b>Posiciones Abiertas ({len(open_pos)}):</b>")
        if not open_pos:
            lines.append("  <i>Ninguna. El agente está en liquidez 100% USDT.</i>")
        else:
            for op in open_pos:
                u_pnl = op.get("unrealized_pnl", 0.0)
                u_pct = op.get("unrealized_pnl_pct", 0.0)
                pnl_sign = "+" if u_pnl >= 0 else ""
                lines.append(
                    f"  • 🟢 <b>{op.get('symbol')}</b> ({op.get('side')}): {op.get('quantity'):.4f}\n"
                    f"    Entrada: ${op.get('entry_price'):,.2f} | Actual: ${op.get('current_price'):,.2f}\n"
                    f"    PnL Flotante: <b>{pnl_sign}${u_pnl:,.2f} USD ({pnl_sign}{u_pct:.2f}%)</b>"
                )

        realized = status.get("realized_pnl_usd", 0.0)
        unrealized = status.get("unrealized_pnl_usd", 0.0)
        total = status.get("total_pnl_usd", 0.0)
        closed_count = status.get("closed_trades_count", 0)
        win_count = status.get("winning_trades", 0)
        loss_count = status.get("losing_trades", 0)
        win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0.0

        r_sign = "+" if realized > 0 else ""
        u_sign = "+" if unrealized > 0 else ""
        t_sign = "+" if total > 0 else ""

        lines.append("\n💰 <b>Rendimiento y PnL:</b>")
        lines.append(f"  • <b>PnL Total Neto:</b> {t_sign}${total:,.2f} USD")
        lines.append(f"  • <b>Ganancias Realizadas:</b> {r_sign}${realized:,.2f} USD ({closed_count} trades)")
        lines.append(f"  • <b>Ganancias Flotantes:</b> {u_sign}${unrealized:,.2f} USD")
        lines.append(f"  • <b>Win Rate:</b> {win_rate:.1f}% ({win_count} ganados / {loss_count} perdidos)")

        eval_counts = status.get("eval_counts", {})
        total_evals = status.get("total_evaluations", 0)
        lines.append("\n📊 <b>Evaluaciones de Mercado:</b>")
        lines.append(f"  • <b>Total Evaluaciones:</b> {total_evals:,}")
        for k, v in eval_counts.items():
            if v > 0:
                lines.append(f"    └ {k}: {v:,}")

        # Billetera de Monedas del Agente ($1.00 USD Inicial por par)
        coins_breakdown = status.get("coins_breakdown", [])
        if coins_breakdown:
            lines.append("\n👝 <b>Billetera por Moneda ($1.00 USD Base / Par):</b>")
            for cb in coins_breakdown:
                sym = cb["symbol"]
                b_usd = cb["base_investment_usd"]
                c_val = cb["current_value_usd"]
                t_pnl = cb["total_pnl_usd"]
                r_pnl = cb["realized_pnl_usd"]
                u_pnl = cb["unrealized_pnl_usd"]
                pnl_s = "+" if t_pnl >= 0 else ""
                pos_indicator = "🟢 [POS]" if cb["has_open_position"] else "⚪ [LIQ]"

                lines.append(
                    f"  • {pos_indicator} <b>{sym}</b>: Balance: <b>${c_val:,.2f} USD</b> "
                    f"<i>(Base: ${b_usd:.2f} | PnL: {pnl_s}${t_pnl:,.2f})</i>"
                )

        return "\n".join(lines)

    def format_global_wallet_message(self, capital_usd: float = None, capital_clp: float = None) -> str:
        """Genera el mensaje detallado de Billetera Global y Billeteras por Subagente."""
        status = self.get_global_status()

        if capital_usd is None:
            try:
                capital_usd = asyncio.run(self._fetch_total_capital())
            except Exception:
                capital_usd = 16.0
        if capital_clp is None:
            capital_clp = self.clp_converter.convert_usd_to_clp(capital_usd)

        summary = self.portfolio_manager.get_cashflow_summary()
        liquid_balance = summary.get('balance', float(capital_usd))

        icons = {
            "scalper_t1":     "⚡",
            "momentum_t2":    "🚀",
            "macro_btceth":   "🐋",
            "speculative_t3": "⚠️",
        }

        lines = [
            "👝 <b>Billetera Digital Multi-Agente</b>\n",
            f"💵 <b>Saldo Total en Cuenta:</b> ${capital_usd:,.2f} USDT <i>(${capital_clp:,.0f} CLP)</i>",
            f"💧 <b>Liquidez Disponible:</b> ${liquid_balance:,.2f} USDT",
            f"🎯 <b>Inversión Base Matriz:</b> $16.00 USD (16 pares x $1.00 USD)\n",
            "━━━━━━━━━━━━━━━━━━━",
            "🤖 <b>Billeteras por Sub-Agente:</b>\n",
        ]

        for aid, agent_status in status["agents"].items():
            if not isinstance(agent_status, dict) or "error" in agent_status:
                continue
            icon = icons.get(aid, "🤖")
            aname = agent_status.get("agent_name", aid)
            pairs = agent_status.get("pairs", [])
            base_agent_cap = len(pairs) * 1.0
            tot_pnl = agent_status.get("total_pnl_usd", 0.0)
            r_pnl = agent_status.get("realized_pnl_usd", 0.0)
            u_pnl = agent_status.get("unrealized_pnl_usd", 0.0)
            agent_equity = base_agent_cap + tot_pnl

            pnl_sign = "+" if tot_pnl >= 0 else ""
            lines.append(f"{icon} <b>{aname}</b> ({len(pairs)} monedas):")
            lines.append(f"  • Base: <b>${base_agent_cap:,.2f} USD</b> | Saldo Actual: <b>${agent_equity:,.2f} USD</b>")
            lines.append(f"  • PnL Total: <b>{pnl_sign}${tot_pnl:,.2f} USD</b> <i>(Realizado: ${r_pnl:,.2f} | Flotante: ${u_pnl:,.2f})</i>")

            coins_bd = agent_status.get("coins_breakdown", [])
            for cb in coins_bd:
                sym = cb["symbol"]
                c_val = cb["current_value_usd"]
                c_pnl = cb["total_pnl_usd"]
                c_sign = "+" if c_pnl >= 0 else ""
                pos_tag = "🟢" if cb["has_open_position"] else "⚪"
                lines.append(f"    └ {pos_tag} <code>{sym}</code>: ${c_val:,.2f} <i>({c_sign}${c_pnl:,.2f})</i>")
            lines.append("")

        lines.append("💡 <i>Usa los botones o /agent_view:&lt;id&gt; para gestionar cada agente.</i>")
        return "\n".join(lines)

