import traceback
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

    def get_open_positions_count(self) -> int:
        session = DatabaseSession.get_session()
        try:
            count = session.query(Trade).filter(Trade.status == "OPEN").count()
            return count
        finally:
            session.close()

    async def process_symbol(self, symbol: str, current_tf: str, total_capital: float, data_collector, order_executor) -> dict:
        try:
            df = await data_collector.get_historical_data(symbol=symbol, timeframe=current_tf, limit=50)
            if df.empty:
                log.warning(f"No historical data for {symbol}, skipping.")
                return {'symbol': symbol, 'decision': 'ERROR', 'reason': 'No historical data'}

            signal = self.strategy.generate_signal(df)
            current_price = float(df['close'].iloc[-1])
            self.portfolio_manager.update_asset_price(symbol, current_price)
            
            close_result = await self.manage_open_trades(symbol, current_price, signal, order_executor, total_capital)
            if close_result:
                return close_result

            if signal in ["BUY", "SELL"]:
                if signal == "SELL":
                    return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'SELL signal ignored for opening new shorts.'}
                
                log.info(f"Signal {signal} generated for {symbol}")
                current_positions = self.get_open_positions_count()
                
                session = DatabaseSession.get_session()
                open_trades = session.query(Trade).filter(Trade.status == "OPEN").all()
                session.close()
                
                open_trades_for_symbol = sum(1 for t in open_trades if t.symbol == symbol)
                is_dca = open_trades_for_symbol > 0
                
                current_exposure = sum(float(t.price_entry) * float(t.quantity) for t in open_trades if t.side == "BUY")
                exposure_pct = current_exposure / total_capital
                
                max_allowed_pct = self.config.risk.max_capital_exposure_pct
                if not is_dca:
                    max_allowed_pct -= getattr(self.config.risk, "reserve_capital_pct", 0.30)
                
                stop_loss_price = current_price * (1 - self.config.risk.max_loss_per_trade_pct)
                amount = self.risk_manager.calculate_position_size(total_capital, current_price, stop_loss_price)
                if amount <= 0: amount = 0.001

                # Cap amount to available headroom within max_allowed_pct
                remaining_capital = max(0.0, (max_allowed_pct - exposure_pct) * total_capital)
                if (amount * current_price) > remaining_capital:
                    amount = remaining_capital / current_price
                
                trade_details_str = f" | Precio: {current_price} USD | Cant: {amount:.4f}"
                
                if not self.risk_manager.can_open_position(current_positions) and not is_dca:
                    return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Max open positions reached{trade_details_str}"}
                
                # Check minimum viable trade ($5 USD) or exposure limit violation
                if (amount * current_price) < 5.0 or (exposure_pct + (amount * current_price / total_capital) > max_allowed_pct + 1e-5):
                    return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Fondo de Reserva / Capital Exposure (DCA={is_dca}){trade_details_str}"}
                
                if not self.risk_manager.check_daily_loss(0.0, total_capital):
                    return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Daily loss limit{trade_details_str}"}
                
                execution_result = await order_executor.execute_order(symbol=symbol, side=signal, amount=amount, order_type="MARKET")
                self.portfolio_manager.record_open_trade(execution_result, strategy="EMACrossover")
                
                capital_clp = self.clp_converter.convert_usd_to_clp(total_capital)
                trade_details = {"symbol": symbol, "side": signal, "amount": amount, "price": current_price}
                
                report_msg = f"Operación ejecutada: {signal} de {amount} {symbol} a {current_price} USD"
                registrar_log("REPORTE", report_msg)
                
                self.notifier.send_trade_alert(trade_details, capital_clp)
                return {'symbol': symbol, 'decision': signal, 'reason': f"Ejecutado a {current_price} USD"}
            else:
                return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'No action needed'}
        except Exception as e:
            log.error(f"Error processing {symbol}: {e}")
            self.notifier.send_error_alert(f"Error processing {symbol}:\n{traceback.format_exc()}")
            return {'symbol': symbol, 'decision': 'ERROR', 'reason': str(e)}

    async def manage_open_trades(self, symbol: str, current_price: float, current_signal: str, order_executor, total_capital: float) -> dict:
        session = DatabaseSession.get_session()
        try:
            open_trades = session.query(Trade).filter(Trade.symbol == symbol, Trade.status == "OPEN").all()
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
                    execution_result = await order_executor.execute_order(symbol=symbol, side=execution_side, amount=float(trade.quantity), order_type="MARKET")
                    
                    executed_price = execution_result.get("price", current_price)
                    execution_result["price"] = executed_price
                    closed_trade = self.portfolio_manager.record_close_trade(trade.trade_id, execution_result)
                    
                    pnl_usd = float(closed_trade.pnl) if closed_trade else 0.0
                    pnl_pct = float(closed_trade.pnl_pct) if closed_trade else 0.0
                    capital_clp = self.clp_converter.convert_usd_to_clp(total_capital)
                    
                    trade_details = {"symbol": symbol, "side": execution_side, "amount": float(trade.quantity), "price": executed_price, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct, "reason": close_reason}
                    self.notifier.send_trade_alert(trade_details, capital_clp)
                    registrar_log("REPORTE", f"Operación CERRADA: {execution_side} de {trade.quantity} {symbol} a {executed_price} USD. PnL: {pnl_usd:.2f}. Razón: {close_reason}")
                    
                    return {'symbol': symbol, 'decision': 'CLOSED', 'reason': close_reason}
        finally:
            session.close()
        return None
