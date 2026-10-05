"""
agents/base_agent.py

Clase base abstracta para todos los subagentes del sistema multi-agente.
Cada subagente encapsula su propio ciclo de trading, capital y configuración.
"""
import asyncio
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from tradingbot.core.config import load_yaml_config, get_settings, AppConfig
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.market.ccxt_connector import CCXTConnector
from tradingbot.market.data_collector import DataCollector
from tradingbot.execution.order_executor import OrderExecutor
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import DigitalWallet, Trade, Portfolio, DecisionLog
from sqlalchemy import or_, func
from tradingbot.utils.logger import log
from tradingbot.utils.clp_converter import CLPConverter
from tradingbot.interfaces.telegram.notifier import TelegramNotifier


class BaseAgent(ABC):
    """
    Clase base abstracta para todos los subagentes del Orchestrator.

    Cada subagente:
    - Carga su propia configuración YAML
    - Tiene su propio scheduler independiente
    - Opera sobre un pool de capital asignado (fracción del total)
    - Reporta estado al OrchestratorBot
    - Puede ser pausado/reanudado independientemente
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config: AppConfig = load_yaml_config(config_path)
        self.settings = get_settings()

        self.agent_id: str = getattr(self.config, "agent", None) and self.config.agent.agent_id or "unknown"
        self.agent_name: str = getattr(self.config, "agent", None) and self.config.agent.name or "UnnamedAgent"
        self.capital_pool_pct: float = getattr(self.config, "agent", None) and self.config.agent.capital_pool_pct or 0.0

        self.risk_manager = RiskManager(self.config)
        self.portfolio_manager = PortfolioManager()
        self.notifier = TelegramNotifier()
        self.clp_converter = CLPConverter()

        self.strategy = self._build_strategy()

        from tradingbot.engine.trade_engine import TradeEngine
        self.trade_engine = TradeEngine(
            config=self.config,
            risk_manager=self.risk_manager,
            portfolio_manager=self.portfolio_manager,
            strategy=self.strategy,
            notifier=self.notifier,
            clp_converter=self.clp_converter,
        )

        self.scheduler = BackgroundScheduler()
        self.paused: bool = self.config.bot.mode == "passive"
        self._assigned_capital: float = 0.0
        self._started_at: datetime | None = None
        self._cycle_count: int = 0
        self._last_signal: str = "HOLD"

        log.info(f"[{self.agent_name}] Initialized | Mode: {self.config.bot.mode} | Pairs: {self.config.bot.trading_pairs}")

    @abstractmethod
    def _build_strategy(self):
        """Construye e retorna la estrategia específica del subagente."""
        pass

    def set_capital(self, amount: float):
        """Asigna el capital en USDT que puede usar este subagente."""
        self._assigned_capital = amount
        log.info(f"[{self.agent_name}] Capital asignado: ${amount:,.2f} USDT ({self.capital_pool_pct*100:.0f}% del total)")

    def _get_current_timeframe(self) -> str:
        """Determina el timeframe actual según horario configurado."""
        dt_cfg = self.config.bot.dynamic_timeframe
        if dt_cfg and dt_cfg.enabled:
            current_hour = datetime.utcnow().hour
            start_hr = dt_cfg.active_hours_utc.start
            end_hr = dt_cfg.active_hours_utc.end

            if start_hr < end_hr:
                is_active = start_hr <= current_hour < end_hr
            else:
                is_active = current_hour >= start_hr or current_hour < end_hr

            return dt_cfg.active_timeframe if is_active else dt_cfg.passive_timeframe
        return self.config.bot.timeframe

    async def _get_assigned_capital(self) -> float:
        """Retorna el capital asignado a este subagente."""
        if self._assigned_capital > 0:
            return self._assigned_capital

        # Fallback: si no se asignó capital, usar capital paper trading total
        if self.settings.paper_trading:
            try:
                from sqlalchemy import select
                async with DatabaseSession.get_async_session() as session:
                    telegram_id = str(self.settings.telegram_chat_id)
                    result = await session.execute(
                        select(DigitalWallet).filter(
                            DigitalWallet.telegram_id == telegram_id,
                            DigitalWallet.is_paper == True
                        )
                    )
                    wallet = result.scalars().first()
                    total = float(wallet.balance_usd) if wallet else 20.0
                    return total * self.capital_pool_pct
            except Exception as e:
                log.warning(f"[{self.agent_name}] Error consultando wallet: {e}")
                return 50.0 * self.capital_pool_pct
        else:
            connector = CCXTConnector()
            try:
                balance = await connector.fetch_balance()
                base = self.config.bot.base_currency
                total = float(balance[base]["free"]) if base in balance else 50.0
                return total * self.capital_pool_pct
            except Exception as e:
                log.warning(f"[{self.agent_name}] Error obteniendo balance: {e}")
                return 50.0 * self.capital_pool_pct
            finally:
                await connector.close()

    async def run_cycle(self):
        """Ciclo principal de evaluación del subagente."""
        if self.paused:
            log.info(f"[{self.agent_name}] En modo PASSIVE. Ciclo omitido.")
            return

        log.info(f"[{self.agent_name}] --- Iniciando ciclo #{self._cycle_count + 1} ---")
        connector = CCXTConnector()
        data_collector = DataCollector(connector)
        order_executor = OrderExecutor(connector)

        try:
            current_tf = self._get_current_timeframe()

            # Anti-Repainting: esperar cierre de vela
            if current_tf.endswith("m"):
                tf_mins = int(current_tf.replace("m", ""))
                current_min = datetime.utcnow().minute
                if tf_mins > 1 and current_min % tf_mins != 0:
                    log.info(f"[{self.agent_name}] Esperando cierre de vela {current_tf}. Minuto: {current_min}")
                    decisions = [
                        {"symbol": s, "decision": "HOLD", "reason": f"Waiting for {current_tf} candle close"}
                        for s in self.config.bot.trading_pairs
                    ]
                    await self.portfolio_manager.record_decisions_bulk_async(decisions)
                    return

            capital = await self._get_assigned_capital()

            # Asegurar mercados en memoria antes del gather concurrente
            await connector.ensure_markets_loaded()

            # Procesar símbolos concurrentemente
            tasks = [
                self.trade_engine.process_symbol(symbol, current_tf, capital, data_collector, order_executor)
                for symbol in self.config.bot.trading_pairs
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            bulk_decisions = []
            for result in results:
                if isinstance(result, Exception):
                    log.error(f"[{self.agent_name}] Error en gather: {result}")
                elif isinstance(result, dict):
                    bulk_decisions.append(result)

            if bulk_decisions:
                await self.portfolio_manager.record_decisions_bulk_async(bulk_decisions)

            self._cycle_count += 1

        except Exception as e:
            log.error(f"[{self.agent_name}] Error crítico en ciclo: {e}")
            self.notifier.send_error_alert(
                f"[{self.agent_name}] Error crítico en ciclo:\n{traceback.format_exc()}"
            )
        finally:
            try:
                await connector.close()
            except Exception as ce:
                log.error(f"[{self.agent_name}] Error cerrando conector: {ce}")

        log.info(f"[{self.agent_name}] --- Ciclo #{self._cycle_count} completado ---")

    def _run_cycle_sync(self):
        """Wrapper síncrono para llamar desde el scheduler."""
        try:
            asyncio.run(self.run_cycle())
        except Exception as e:
            log.error(f"[{self.agent_name}] Error en run_cycle_sync: {e}")

    def start(self):
        """Inicia el scheduler del subagente."""
        if self.config.bot.mode == "passive":
            log.info(f"[{self.agent_name}] Arrancando en modo PASSIVE (monitoring only).")
            self.paused = True
            # Enviar notificación de monitoreo activo (especialmente para Tier 3)
            self.notifier.send_message(
                f"👁️ <b>{self.agent_name}</b> iniciado en modo <b>PASSIVE</b>.\n"
                f"Monitoreando señales en: {', '.join(self.config.bot.trading_pairs)}\n"
                f"No ejecutará órdenes hasta recibir <code>/resume_{self.agent_id}</code>"
            )
        else:
            log.info(f"[{self.agent_name}] Arrancando en modo ACTIVE.")
            self.paused = False

        self._started_at = datetime.utcnow()

        # Ejecutar ciclo inicial inmediato
        self._run_cycle_sync()

        # Programar ciclos cada 1 minuto
        self.scheduler.add_job(self._run_cycle_sync, "interval", minutes=1, id=f"cycle_{self.agent_id}")
        self.scheduler.start()
        log.info(f"[{self.agent_name}] Scheduler iniciado.")

    def stop(self):
        """Detiene el scheduler del subagente."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.paused = True
        log.info(f"[{self.agent_name}] Detenido.")

    def pause(self):
        """Pausa el subagente sin detener el scheduler."""
        self.paused = True
        self.config.bot.mode = "passive"
        log.info(f"[{self.agent_name}] Pausado (modo PASSIVE).")

    def resume(self):
        """Reanuda el subagente."""
        self.paused = False
        self.config.bot.mode = "active"
        log.info(f"[{self.agent_name}] Reanudado (modo ACTIVE).")

    def get_status(self) -> dict:
        """Retorna el estado detallado del subagente para el panel y comando status."""
        mode = "PASSIVE" if self.paused else "ACTIVE"
        pairs = self.config.bot.trading_pairs or []
        trading_mode = getattr(self.config.bot, "trading_mode", "trend")
        current_tf = self._get_current_timeframe()

        open_positions = []
        unrealized_pnl_total = 0.0
        closed_trades_count = 0
        winning_trades = 0
        losing_trades = 0
        realized_pnl_usd = 0.0
        eval_counts = {"HOLD": 0, "BUY": 0, "SELL": 0, "BLOCKED": 0, "ERROR": 0}
        total_evals = 0

        session = DatabaseSession.get_session()
        try:
            # Consultar portfolio para precios actuales
            portfolio_map = {}
            p_rows = session.query(Portfolio).all()
            for p in p_rows:
                portfolio_map[p.asset] = {
                    "current_price": float(p.current_price or 0.0),
                    "unrealized_pnl": float(p.unrealized_pnl or 0.0)
                }

            # Posiciones abiertas del agente
            open_trades = session.query(Trade).filter(
                Trade.status == "OPEN",
                or_(Trade.agent_id == self.agent_id, Trade.symbol.in_(pairs))
            ).all()

            for ot in open_trades:
                base_asset = ot.symbol.split('/')[0] if '/' in ot.symbol else ot.symbol
                cur_info = portfolio_map.get(base_asset, {})
                cur_px = cur_info.get("current_price", float(ot.price_entry or 0.0))
                if cur_px == 0.0:
                    cur_px = float(ot.price_entry or 0.0)

                entry_px = float(ot.price_entry or 0.0)
                qty = float(ot.quantity or 0.0)
                if ot.side == "BUY":
                    u_pnl = (cur_px - entry_px) * qty
                else:
                    u_pnl = (entry_px - cur_px) * qty
                u_pnl_pct = (u_pnl / (entry_px * qty) * 100) if (entry_px * qty) > 0 else 0.0
                unrealized_pnl_total += u_pnl

                open_positions.append({
                    "symbol": ot.symbol,
                    "side": ot.side,
                    "quantity": qty,
                    "entry_price": entry_px,
                    "current_price": cur_px,
                    "unrealized_pnl": u_pnl,
                    "unrealized_pnl_pct": u_pnl_pct,
                    "opened_at": ot.opened_at.isoformat() if ot.opened_at else None,
                })

            # Trades cerrados del agente
            closed_trades = session.query(Trade).filter(
                Trade.status == "CLOSED",
                Trade.agent_id == self.agent_id
            ).all()
            closed_trades_count = len(closed_trades)
            for ct in closed_trades:
                pnl_val = float(ct.pnl or 0.0)
                realized_pnl_usd += pnl_val
                if pnl_val > 0:
                    winning_trades += 1
                elif pnl_val < 0:
                    losing_trades += 1

            # Evaluaciones (DecisionLog)
            if pairs:
                q_eval = session.query(DecisionLog.decision, func.count(DecisionLog.id)).filter(
                    DecisionLog.symbol.in_(pairs)
                )
                if self._started_at:
                    q_eval = q_eval.filter(DecisionLog.timestamp >= self._started_at)
                for dec, cnt in q_eval.group_by(DecisionLog.decision).all():
                    eval_counts[dec] = cnt
                    total_evals += cnt
        except Exception as e:
            log.warning(f"[{self.agent_name}] Error en get_status: {e}")
        finally:
            session.close()

        total_pnl_usd = realized_pnl_usd + unrealized_pnl_total

        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "mode": mode,
            "trading_mode": trading_mode,
            "pairs": pairs,
            "timeframe": self.config.bot.timeframe,
            "current_timeframe": current_tf,
            "capital_pool_pct": self.capital_pool_pct,
            "assigned_capital_usd": self._assigned_capital,
            "cycle_count": self._cycle_count,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "closed_trades_count": closed_trades_count,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "realized_pnl_usd": realized_pnl_usd,
            "unrealized_pnl_usd": unrealized_pnl_total,
            "total_pnl_usd": total_pnl_usd,
            "total_evaluations": total_evals,
            "eval_counts": eval_counts,
        }

