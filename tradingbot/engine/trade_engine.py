import os
import asyncio
import traceback
from datetime import datetime
from typing import Optional, Dict
import ccxt
from sqlalchemy import select, func
from tradingbot.core.config import AppConfig
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Trade
from tradingbot.services.market_bias_service import BTCMarketBiasFilter
from tradingbot.utils.logger import log, registrar_log
from tradingbot.utils.tz import now_chile, format_chile, format_chile_human

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
        self._trade_lock: Optional[asyncio.Lock] = None
        self._trade_lock_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Filtro Macro de Tendencia BTC
        bias_cfg = getattr(self.config.risk, "market_bias", None)
        self.market_bias_filter = BTCMarketBiasFilter(config=bias_cfg)
        
        # Tracker de ciclos consecutivos para el Seguro de Salida por Tiempo (Safe Time-Stop)
        self.time_stop_tracker: Dict[str, int] = {}

    @property
    def trade_lock(self) -> asyncio.Lock:
        """Retorna un Lock de asyncio asociado dinámicamente al event loop activo actual."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._trade_lock is None or self._trade_lock_loop is not current_loop:
            self._trade_lock = asyncio.Lock()
            self._trade_lock_loop = current_loop
        return self._trade_lock

    def generate_coin_loss_report(self, agent_id: str, symbol: str, base_usd: float, realized_pnl: float, closed_trades: list) -> str:
        """Genera un informe técnico forense en Markdown cuando una moneda agota sus fondos."""
        now_dt = now_chile()
        timestamp_str = now_dt.strftime('%Y%m%d_%H%M%S')
        safe_symbol = symbol.replace('/', '_')
        report_filename = f"informe_perdida_{agent_id}_{safe_symbol}_{timestamp_str}.md"
        report_path = os.path.join("/home/shifu/documentos-agy", report_filename)

        lines = [
            f"# Informe Forense: Agotamiento de Fondos en {symbol}",
            f"",
            f"**Fecha y Hora:** {format_chile_human(now_dt)}  ",
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
            f"| Trade ID | Lado | Cantidad | Precio Entrada | Precio Salida | PnL (USD) | PnL (%) | Estrategia | Fecha Cierre (Chile) |",
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
            c_at_str = format_chile(c_at) if c_at != "N/A" else "N/A"
            lines.append(f"| `{tid}` | {side} | {qty:.6f} | ${p_in:,.4f} | ${p_out:,.4f} | ${pnl:.4f} | {pnl_pct:.2f}% | {strat} | {c_at_str} |")

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

    async def process_symbol(self, symbol: str, current_tf: str, total_capital: float, data_collector, order_executor, agent_id: Optional[str] = None) -> dict:
        try:
            if not agent_id:
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
            
            # 1. Gestionar salidas de posiciones abiertas (TP, SL, Safe Time-Stop)
            close_result = await self.manage_open_trades(symbol, current_price, signal, order_executor, total_capital, agent_id)
            if close_result:
                return close_result

            # 2. Evaluación de nuevas señales y Micro DCA
            if signal == "SELL":
                return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'SELL signal ignored for opening new shorts.'}

            async with self.trade_lock:
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
                open_trades_for_symbol = [t for t in open_trades if t.symbol == symbol]

                available_cash = await self.portfolio_manager.get_liquid_cash_async()
                total_equity = await self.portfolio_manager.get_total_equity_async()
                if total_equity <= 0:
                    total_equity = total_capital

                coin_reserve_pct = getattr(self.config.risk, "coin_reserve_pct", 0.25)
                max_coin_order_pct = getattr(self.config.risk, "max_coin_order_pct", 1.0 - coin_reserve_pct)
                full_coin_alloc = round(coin_balance * max_coin_order_pct, 4)
                min_order_usd = getattr(self.config.risk, "min_order_usd", 0.10)

                micro_dca_cfg = getattr(self.config.risk, "micro_dca", None)
                is_dca_enabled = micro_dca_cfg and getattr(micro_dca_cfg, "enabled", True)

                # Si ya existe una posición abierta para este símbolo:
                if open_trades_for_symbol:
                    existing_trade = open_trades_for_symbol[0]
                    dca_step = getattr(existing_trade, "dca_step", 1) or 1

                    # Evaluar gatillo de Tramo 2 en Pullback (Order Splitting / Micro DCA)
                    if is_dca_enabled and dca_step == 1:
                        entry_price = float(existing_trade.price_entry)
                        price_drop = (entry_price - current_price) / entry_price if entry_price > 0 else 0.0
                        pullback_min = getattr(micro_dca_cfg, "pullback_min_pct", 0.006)
                        pullback_max = getattr(micro_dca_cfg, "pullback_max_pct", 0.025)

                        if pullback_min <= price_drop <= pullback_max:
                            tranche_2_pct = getattr(micro_dca_cfg, "pullback_tranche_pct", 0.4667)
                            order_usd_2 = min(round(full_coin_alloc * tranche_2_pct, 4), available_cash)

                            if order_usd_2 >= min_order_usd:
                                amount_2 = order_usd_2 / current_price
                                log.info(f"[{agent_id}] Gatillando Micro DCA Tramo 2/2 en {symbol} (${order_usd_2:.2f} USD a ${current_price:,.4f}, pullback {price_drop*100:.2f}%)")

                                exec_res_2 = await order_executor.execute_order(
                                    symbol=symbol, side="BUY", amount=amount_2, order_type="MARKET", price=current_price
                                )

                                updated_trade = await self.portfolio_manager.consolidate_dca_position_async(
                                    existing_trade.trade_id, exec_res_2, dca_step=2
                                )

                                new_avg = float(updated_trade.price_entry) if updated_trade else current_price
                                capital_clp = self.clp_converter.convert_usd_to_clp(total_equity)
                                trade_details = {
                                    "symbol": symbol,
                                    "side": "BUY (Micro DCA 2/2)",
                                    "amount": amount_2,
                                    "price": current_price,
                                    "avg_price": new_avg
                                }

                                report_msg = (
                                    f"⚡ Entrada Escalonada Tramo 2/2 ejecutada: {amount_2:.4f} {symbol} a ${current_price:,.4f} "
                                    f"(${order_usd_2:.2f} USD). Nuevo precio promedio: ${new_avg:,.4f} (-{price_drop*100:.2f}% vs entrada 1)"
                                )
                                registrar_log("REPORTE", report_msg)
                                self.notifier.send_trade_alert(trade_details, capital_clp)
                                return {'symbol': symbol, 'decision': 'BUY_DCA_2', 'reason': f"Micro DCA Tramo 2 a ${current_price:,.4f} (Avg: ${new_avg:,.4f})"}

                    return {'symbol': symbol, 'decision': 'HOLD', 'reason': f"Posición ya abierta para {symbol} (DCA paso {dca_step})"}

                # Si NO hay posición abierta y la señal es BUY:
                if signal == "BUY":
                    log.info(f"Signal {signal} generated for {symbol}")

                    # Filtro de Tendencia Macro para Altcoins (BTC Market Bias Filter)
                    if symbol != "BTC/USDT":
                        bias_cfg = getattr(self.config.risk, "market_bias", None)
                        if bias_cfg and getattr(bias_cfg, "enabled", True):
                            bias, bias_reason = await self.market_bias_filter.get_btc_bias(data_collector)
                            if bias == "BEARISH":
                                log.warning(f"[{agent_id}] Compra en {symbol} bloqueada por BTC Market Bias: {bias_reason}")
                                return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"BTC Macro Bias Bearish ({bias_reason})"}

                    # Validar límite de posiciones abiertas concurrentes
                    if not self.risk_manager.can_open_position(current_positions):
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Límite de posiciones abiertas alcanzado ({current_positions}/{self.config.risk.max_open_positions})"}

                    # Asignar presupuesto para Tramo 1 (Order Splitting) o entrada estándar
                    if is_dca_enabled:
                        tranche_1_pct = getattr(micro_dca_cfg, "initial_tranche_pct", 0.5333)
                        order_usd = min(round(full_coin_alloc * tranche_1_pct, 4), available_cash)
                        dca_step = 1
                    else:
                        order_usd = min(full_coin_alloc, available_cash)
                        dca_step = 1

                    if order_usd < min_order_usd:
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Saldo insuficiente (${order_usd:.2f} USD < mín ${min_order_usd:.2f} USD)"}

                    amount = order_usd / current_price

                    if not self.risk_manager.check_daily_loss(0.0, total_equity):
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': "Límite de pérdida diaria alcanzado"}

                    execution_result = await order_executor.execute_order(
                        symbol=symbol, side=signal, amount=amount, order_type="MARKET", price=current_price
                    )
                    strat_name = str(getattr(self.strategy, "name", "EMACrossover"))
                    if "Mock" in strat_name:
                        strat_name = "EMACrossover"
                    await self.portfolio_manager.record_open_trade_async(
                        execution_result, 
                        strategy=strat_name,
                        agent_id=agent_id,
                        dca_step=dca_step
                    )
                    
                    capital_clp = self.clp_converter.convert_usd_to_clp(total_equity)
                    dca_label = f"{signal} (Micro DCA 1/2)" if is_dca_enabled else signal
                    trade_details = {"symbol": symbol, "side": dca_label, "amount": amount, "price": current_price}
                    
                    dca_info = f" [Micro DCA Tramo 1/2: {tranche_1_pct*100:.0f}%]" if is_dca_enabled else ""
                    report_msg = f"Operación ejecutada: {dca_label}{dca_info} de {amount:.4f} {symbol} a {current_price} USD (${order_usd:.2f} USD)"
                    registrar_log("REPORTE", report_msg)
                    
                    self.notifier.send_trade_alert(trade_details, capital_clp)
                    return {'symbol': symbol, 'decision': 'BUY_DCA_1' if is_dca_enabled else signal, 'reason': f"Ejecutado{dca_info} a {current_price} USD (${order_usd:.2f} USD)"}

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
            price_entry = float(trade.price_entry)
            
            opened_at = trade.opened_at or datetime.utcnow()
            now = datetime.utcnow()
            duration_minutes = (now - opened_at).total_seconds() / 60.0
            
            if trade.side == "BUY":
                pnl_pct = (current_price - price_entry) / price_entry if price_entry > 0 else 0.0

                # 1. Hard Stop Loss de Emergencia Absoluta (Flash Crash Protection)
                ts_cfg = getattr(self.config.risk, "time_stop", None)
                hard_sl_pct = getattr(ts_cfg, "hard_stop_loss_pct", 0.045) if ts_cfg else 0.045
                if pnl_pct <= -hard_sl_pct:
                    should_close, close_reason = True, f"Hard Stop Loss Emergencia (-{hard_sl_pct*100:.1f}%)"
                
                # 2. Take Profit Estándar
                current_tp_pct = tp_pct
                if trading_mode == "scalper":
                    current_tp_pct = 0.005 # +0.5%
                    
                if not should_close and current_price >= price_entry * (1 + current_tp_pct):
                    should_close, close_reason = True, f"Take Profit (+{current_tp_pct*100:.1f}%)"
                    self.time_stop_tracker.pop(trade.trade_id, None)

                # 3. Stop Loss y Reversión en modos tradicionales (trend)
                elif not should_close and current_price <= price_entry * (1 - sl_pct) and trading_mode not in ["target", "scalper"]:
                    should_close, close_reason = True, f"Stop Loss (-{sl_pct*100:.1f}%)"
                elif not should_close and current_signal == "SELL" and trading_mode not in ["target", "scalper"]:
                    should_close, close_reason = True, "Reversión de Estrategia"

                # 4. Salida por Tiempo con Seguro Multi-Ciclo en Scalper (Safe Time-Stop)
                elif not should_close and trading_mode == "scalper" and ts_cfg and getattr(ts_cfg, "enabled", True):
                    min_duration = getattr(ts_cfg, "min_duration_minutes", 120)
                    consecutive_req = getattr(ts_cfg, "consecutive_cycles_required", 3)
                    
                    if duration_minutes >= min_duration:
                        if pnl_pct < 0:
                            # Posición en pérdida tras superar el tiempo de maduración
                            c_count = self.time_stop_tracker.get(trade.trade_id, 0) + 1
                            self.time_stop_tracker[trade.trade_id] = c_count
                            log.info(
                                f"[{trade.symbol}] Safe Time-Stop evaluando trade {trade.trade_id} "
                                f"({duration_minutes:.0f}m activa): ciclo {c_count}/{consecutive_req} en pérdida ({pnl_pct*100:.2f}%)"
                            )
                            if c_count >= consecutive_req:
                                should_close = True
                                close_reason = f"Safe Time-Stop ({int(duration_minutes)}m + {c_count}x Confirmado, PnL {pnl_pct*100:.2f}%)"
                                self.time_stop_tracker.pop(trade.trade_id, None)
                        else:
                            # Rebote a zona positiva o empate: Reset del seguro para permitir alcanzar Take Profit
                            if trade.trade_id in self.time_stop_tracker:
                                log.info(f"[{trade.symbol}] Safe Time-Stop: Rebote detectado (PnL {pnl_pct*100:.2f}%). Seguro reseteado.")
                                self.time_stop_tracker.pop(trade.trade_id, None)
                    
            if should_close:
                self.time_stop_tracker.pop(trade.trade_id, None)
                execution_side = "SELL" if trade.side == "BUY" else "BUY"
                execution_result = await order_executor.execute_order(
                    symbol=symbol, side=execution_side, amount=float(trade.quantity), order_type="MARKET", price=current_price
                )
                
                executed_price = execution_result.get("price", current_price)
                execution_result["price"] = executed_price
                execution_result["reason"] = close_reason
                closed_trade = await self.portfolio_manager.record_close_trade_async(trade.trade_id, execution_result, exit_reason=close_reason)
                
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
