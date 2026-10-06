import os
import asyncio
import traceback
from datetime import datetime
import ccxt
from sqlalchemy import select, func
from tradingbot.core.config import AppConfig
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Trade
from tradingbot.utils.logger import log, registrar_log

class TradeEngine:
    def __init__(
        self,
        config: AppConfig,
        risk_manager: RiskManager,
        portfolio_manager: PortfolioManager,
        strategy,
        notifier,
        clp_converter
    ):
        self.config = config
        self.risk_manager = risk_manager
        self.portfolio_manager = portfolio_manager
        self.strategy = strategy
        self.notifier = notifier
        self.clp_converter = clp_converter
        self._trade_lock = asyncio.Lock()

    def generate_coin_loss_report(self, agent_id: str, symbol: str, base_usd: float, realized_pnl: float, closed_trades: list) -> str:
        """Genera un informe técnico forense en Markdown cuando una moneda agota sus fondos."""
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_symbol = symbol.replace('/', '_')
        report_filename = f"informe_perdida_{agent_id}_{safe_symbol}_{timestamp_str}.md"
        report_path = os.path.join("/home/shifu/documentos-agy", report_filename)

        lines = [
            f"# Informe Forense: Agotamiento de Fondos en {symbol}",
            f"",
            f"**Fecha y Hora:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"**Sub-Agente:** `{agent_id}`  ",
            f"**Activo:** `{symbol}`  ",
            f"**Inversión Inicial Asignada:** ${base_usd:.2f} USD  ",
            f"**PnL Acumulado Realizado:** ${realized_pnl:.2f} USD  ",
            f"**Estado en Tabla de Funcionamiento:** 🔴 **OFF (Detenida)**  ",
            f"",
            f"---",
            f"",
            f"## 1. Resumen de la Desconexión",
            f"El saldo asignado para `{symbol}` ha llegado a **$0.00 USD** (o saldo negativo de ${realized_pnl:.2f} USD) debido a pérdidas acumuladas.",
            f"La celda `({agent_id}, {symbol})` en la Tabla de Funcionamiento ha pasado automáticamente a **OFF**, bloqueando cualquier nueva compra.",
            f"",
            f"## 2. Historial de Operaciones del Activo",
            f"",
            f"| Trade ID | Lado | Cantidad | Precio Entrada | Precio Salida | PnL (USD) | PnL (%) | Estrategia | Fecha Cierre |",
            f"|---|---|---|---|---|---|---|---|---|"
        ]

        for t in closed_trades:
            tid = getattr(t, "trade_id", "N/A")
            side = getattr(t, "side", "N/A")
            qty = float(getattr(t, "quantity", 0.0) or 0.0)
            p_in = float(getattr(t, "price_entry", 0.0) or 0.0)
            p_out = float(getattr(t, "price_exit", 0.0) or 0.0)
            pnl = float(getattr(t, "pnl", 0.0) or 0.0)
            pnl_pct = float(getattr(t, "pnl_pct", 0.0) or 0.0) * 100
            strat = getattr(t, "strategy", "N/A")
            c_at = getattr(t, "closed_at", "N/A")
            lines.append(f"| `{tid}` | {side} | {qty:.6f} | ${p_in:,.4f} | ${p_out:,.4f} | ${pnl:.4f} | {pnl_pct:.2f}% | {strat} | {c_at} |")

        lines.extend([
            f"",
            f"---",
            f"## 3. Acciones Recomendadas",
            f"1. Para reanudar operaciones en `{symbol}`, asigne nuevo capital desde la interfaz o base de datos.",
            f"2. Audite las condiciones de mercado del par en el dataset histórico de velas `candles`."
        ])

        os.makedirs("/home/shifu/documentos-agy", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path

    def get_open_positions_count(self) -> int:
        session = DatabaseSession.get_session()
        try:
            count = session.query(Trade).filter(Trade.status == "OPEN").count()
            return count
        finally:
            session.close()

    async def get_open_positions_count_async(self) -> int:
        async with DatabaseSession.get_async_session() as session:
            result = await session.execute(select(Trade).filter(Trade.status == "OPEN"))
            return len(result.scalars().all())

    async def process_symbol(self, symbol: str, current_tf: str, total_capital: float, data_collector, order_executor) -> dict:
        try:
            agent_id = getattr(self.config, "agent", None) and getattr(self.config.agent, "agent_id", "legacy") or "legacy"
            slow_period = getattr(self.strategy, "slow_period", 21)
            limit = max(50, slow_period + 50)
            df = await data_collector.get_historical_data(symbol=symbol, timeframe=current_tf, limit=limit)
            if df.empty:
                log.warning(f"No historical data for {symbol}, skipping.")
                return {'symbol': symbol, 'decision': 'ERROR', 'reason': 'No historical data'}

            signal = self.strategy.generate_signal(df)
            current_price = float(df['close'].iloc[-1])
            await self.portfolio_manager.update_asset_price_async(symbol, current_price)
            
            close_result = await self.manage_open_trades(symbol, current_price, signal, order_executor, total_capital, agent_id)
            if close_result:
                return close_result

            if signal in ["BUY", "SELL"]:
                if signal == "SELL":
                    return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'SELL signal ignored for opening new shorts.'}
                
                log.info(f"Signal {signal} generated for {symbol}")
                
                async with self._trade_lock:
                    async with DatabaseSession.get_async_session() as session:
                        result = await session.execute(select(Trade).filter(Trade.status == "OPEN"))
                        open_trades = result.scalars().all()
                        
                        # Consultar PnL realizado para esta moneda en este agente
                        pnl_res = await session.execute(
                            select(func.sum(Trade.pnl)).filter(
                                Trade.status == "CLOSED",
                                Trade.symbol == symbol,
                                Trade.agent_id == agent_id
                            )
                        )
                        coin_realized_pnl = float(pnl_res.scalar() or 0.0)
                    
                    # Validación de Fondo Individual por Moneda ($1.00 USD base)
                    base_coin_usd = 1.0
                    coin_balance = base_coin_usd + coin_realized_pnl
                    if coin_balance <= 0.0:
                        log.warning(f"[{agent_id}] Fondo de {symbol} agotado (${coin_balance:.2f} USD). Estado: OFF.")
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Fondo agotado (${coin_balance:.2f} USD) | Estado OFF"}

                    current_positions = len(open_trades)
                    open_trades_for_symbol = sum(1 for t in open_trades if t.symbol == symbol)
                    
                    # Si ya existe una posición abierta para este símbolo, no duplicar compras
                    if open_trades_for_symbol > 0:
                        return {'symbol': symbol, 'decision': 'HOLD', 'reason': f"Posición ya abierta para {symbol} (esperando TP/SL)"}

                    # Validar límite de posiciones abiertas concurrentes
                    if not self.risk_manager.can_open_position(current_positions):
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Límite de posiciones abiertas alcanzado ({current_positions}/{self.config.risk.max_open_positions})"}

                    available_cash = await self.portfolio_manager.get_liquid_cash_async()
                    total_equity = await self.portfolio_manager.get_total_equity_async()
                    if total_equity <= 0:
                        total_equity = total_capital
                    
                    min_order_usd = getattr(self.config.risk, "min_order_usd", 1.0)
                    
                    # Presupuesto para la orden: menor entre el saldo individual de la moneda y la liquidez global
                    order_usd = min(coin_balance, available_cash)
                    if order_usd < min_order_usd:
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Saldo insuficiente (${order_usd:.2f} USD < mín ${min_order_usd:.2f} USD)"}

                    amount = order_usd / current_price

                    if not self.risk_manager.check_daily_loss(0.0, total_equity):
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': "Límite de pérdida diaria alcanzado"}

                    execution_result = await order_executor.execute_order(
                        symbol=symbol, side=signal, amount=amount, order_type="MARKET", price=current_price
                    )
                    await self.portfolio_manager.record_open_trade_async(
                        execution_result, 
                        strategy=getattr(self.strategy, "name", "EMACrossover"),
                        agent_id=agent_id
                    )
                    
                    capital_clp = self.clp_converter.convert_usd_to_clp(total_equity)
                    trade_details = {"symbol": symbol, "side": signal, "amount": amount, "price": current_price}
                    
                    report_msg = f"Operación ejecutada: {signal} de {amount:.4f} {symbol} a {current_price} USD (${order_usd:.2f} USD)"
                    registrar_log("REPORTE", report_msg)
                    
                    self.notifier.send_trade_alert(trade_details, capital_clp)
                    return {'symbol': symbol, 'decision': signal, 'reason': f"Ejecutado a {current_price} USD (${order_usd:.2f} USD)"}
            else:
                return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'No action needed'}
        except (ccxt.RequestTimeout, ccxt.NetworkError, TimeoutError) as ne:
            log.warning(f"Error transitorio de red/timeout procesando {symbol}: {ne}")
            return {'symbol': symbol, 'decision': 'HOLD', 'reason': f"Network timeout transitorio ({type(ne).__name__})"}
        except Exception as e:
            log.error(f"Error processing {symbol}: {e}")
            self.notifier.send_error_alert(f"Error processing {symbol}:\n{traceback.format_exc()}")
            return {'symbol': symbol, 'decision': 'ERROR', 'reason': str(e)}

    async def manage_open_trades(self, symbol: str, current_price: float, current_signal: str, order_executor, total_capital: float, agent_id: str = "legacy") -> dict:
        async with DatabaseSession.get_async_session() as session:
            result = await session.execute(
                select(Trade).filter(Trade.symbol == symbol, Trade.status == "OPEN")
            )
            open_trades = result.scalars().all()
        
        if not open_trades: return None
            
        tp_pct = self.config.risk.default_take_profit_pct
        sl_pct = self.config.risk.max_loss_per_trade_pct
        trading_mode = getattr(self.config.bot, "trading_mode", "trend")
        
        for trade in open_trades:
            should_close = False
            close_reason = ""
            
            if trade.side == "BUY":
                current_tp_pct = tp_pct
                if trading_mode == "scalper":
                    current_tp_pct = 0.005
                    
                if current_price >= float(trade.price_entry) * (1 + current_tp_pct):
                    should_close, close_reason = True, f"Take Profit (+{current_tp_pct*100:.1f}%)"
                elif current_price <= float(trade.price_entry) * (1 - sl_pct) and trading_mode not in ["target", "scalper"]:
                    should_close, close_reason = True, f"Stop Loss (-{sl_pct*100:.1f}%)"
                elif current_signal == "SELL" and trading_mode not in ["target", "scalper"]:
                    should_close, close_reason = True, "Reversión de Estrategia"
                    
            if should_close:
                execution_side = "SELL" if trade.side == "BUY" else "BUY"
                execution_result = await order_executor.execute_order(
                    symbol=symbol, side=execution_side, amount=float(trade.quantity), order_type="MARKET", price=current_price
                )
                
                executed_price = execution_result.get("price", current_price)
                execution_result["price"] = executed_price
                closed_trade = await self.portfolio_manager.record_close_trade_async(trade.trade_id, execution_result)
                
                pnl_usd = float(closed_trade.pnl) if closed_trade else 0.0
                pnl_pct = float(closed_trade.pnl_pct) if closed_trade else 0.0
                capital_clp = self.clp_converter.convert_usd_to_clp(total_capital)
                
                trade_details = {"symbol": symbol, "side": execution_side, "amount": float(trade.quantity), "price": executed_price, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct, "reason": close_reason}
                self.notifier.send_trade_alert(trade_details, capital_clp)
                registrar_log("REPORTE", f"Operación CERRADA: {execution_side} de {trade.quantity} {symbol} a {executed_price} USD. PnL: {pnl_usd:.2f}. Razón: {close_reason}")
                
                # Verificación de agotamiento de fondo tras el cierre
                try:
                    async with DatabaseSession.get_async_session() as session:
                        pnl_res = await session.execute(
                            select(func.sum(Trade.pnl)).filter(
                                Trade.status == "CLOSED",
                                Trade.symbol == symbol,
                                Trade.agent_id == agent_id
                            )
                        )
                        updated_pnl = float(pnl_res.scalar() or 0.0)
                        updated_balance = 1.0 + updated_pnl

                        if updated_balance <= 0.0:
                            trades_res = await session.execute(
                                select(Trade).filter(
                                    Trade.status == "CLOSED",
                                    Trade.symbol == symbol,
                                    Trade.agent_id == agent_id
                                ).order_by(Trade.closed_at.desc())
                            )
                            closed_history = trades_res.scalars().all()
                            report_path = self.generate_coin_loss_report(agent_id, symbol, 1.0, updated_pnl, closed_history)
                            
                            alert_msg = (
                                f"🔴 <b>MONEDA DETENIDA (ESTADO OFF): {symbol}</b>\n\n"
                                f"⚠️ El fondo asignado a <code>{symbol}</code> en <b>{agent_id}</b> se ha agotado.\n"
                                f"💰 <b>Saldo Final:</b> ${updated_balance:.2f} USD (PnL: ${updated_pnl:.2f} USD)\n"
                                f"🛑 <b>Acción:</b> Estado cambiado automáticamente a <b>OFF</b> en la Tabla de Funcionamiento.\n"
                                f"📄 <b>Informe forense generado en:</b> <code>{report_path}</code>"
                            )
                            self.notifier.send_message(alert_msg)
                            registrar_log("ALERTA", f"Moneda {symbol} en {agent_id} agotada (${updated_balance:.2f}). Pasada a OFF.")
                except Exception as ex:
                    log.warning(f"Error verificando balance de moneda tras cierre: {ex}")

                return {'symbol': symbol, 'decision': 'CLOSED', 'reason': close_reason}
        return None
