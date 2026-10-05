import asyncio
import traceback
import ccxt
from sqlalchemy import select
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
            slow_period = getattr(self.strategy, "slow_period", 21)
            limit = max(50, slow_period + 50)
            df = await data_collector.get_historical_data(symbol=symbol, timeframe=current_tf, limit=limit)
            if df.empty:
                log.warning(f"No historical data for {symbol}, skipping.")
                return {'symbol': symbol, 'decision': 'ERROR', 'reason': 'No historical data'}

            signal = self.strategy.generate_signal(df)
            current_price = float(df['close'].iloc[-1])
            await self.portfolio_manager.update_asset_price_async(symbol, current_price)
            
            close_result = await self.manage_open_trades(symbol, current_price, signal, order_executor, total_capital)
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
                    
                    current_exposure = sum(float(t.price_entry) * float(t.quantity) for t in open_trades if t.side == "BUY")
                    exposure_pct = current_exposure / total_equity if total_equity > 0 else 0.0
                    
                    max_allowed_pct = max(0.05, self.config.risk.max_capital_exposure_pct - getattr(self.config.risk, "reserve_capital_pct", 0.30))
                    
                    # Dimensionamiento por ranura (slot)
                    max_positions = max(1, getattr(self.config.risk, "max_open_positions", 10))
                    slot_budget = (total_equity * max_allowed_pct) / max_positions
                    min_order_usd = getattr(self.config.risk, "min_order_usd", 1.0 if self.portfolio_manager.settings.paper_trading else 5.0)

                    # Verificar límite de exposición de capital (preservando fondo de reserva)
                    remaining_exposure_capital = max(0.0, (max_allowed_pct - exposure_pct) * total_equity)
                    if remaining_exposure_capital < min_order_usd:
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Límite de exposición alcanzado ({exposure_pct:.1%}/{max_allowed_pct:.1%}) | Reserva protegida"}

                    # Verificar efectivo líquido disponible en billetera
                    if available_cash < min_order_usd:
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Efectivo insuficiente (${available_cash:.2f} USD < mín ${min_order_usd:.2f} USD)"}

                    # Asignar presupuesto de orden: menor entre slot, margen de exposición y efectivo libre
                    target_order_usd = max(slot_budget, min_order_usd)
                    order_usd = min(target_order_usd, remaining_exposure_capital, available_cash)
                    if order_usd < min_order_usd:
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Fondos insuficientes (${order_usd:.2f} USD < mín ${min_order_usd:.2f} USD)"}

                    amount = order_usd / current_price

                    if not self.risk_manager.check_daily_loss(0.0, total_equity):
                        return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': "Límite de pérdida diaria alcanzado"}

                    execution_result = await order_executor.execute_order(
                        symbol=symbol, side=signal, amount=amount, order_type="MARKET", price=current_price
                    )
                    agent_id = getattr(self.config, "agent", None) and getattr(self.config.agent, "agent_id", "legacy") or "legacy"
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

    async def manage_open_trades(self, symbol: str, current_price: float, current_signal: str, order_executor, total_capital: float) -> dict:
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
                
                return {'symbol': symbol, 'decision': 'CLOSED', 'reason': close_reason}
        return None
