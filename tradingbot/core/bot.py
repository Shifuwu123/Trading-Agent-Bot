import time
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from tradingbot.core.config import load_yaml_config, get_settings, AppConfig
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.market.ccxt_connector import CCXTConnector
from tradingbot.market.data_collector import DataCollector
from tradingbot.strategies.ema_crossover import EMACrossoverStrategy
from tradingbot.execution.order_executor import OrderExecutor
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Trade
from tradingbot.utils.logger import log, registrar_log
from tradingbot.utils.notifier import TelegramNotifier
from tradingbot.utils.clp_converter import CLPConverter
import traceback

class TradingBot:
    def __init__(self, config_path: str = "config.yaml"):
        self.config: AppConfig = load_yaml_config(config_path)
        self.settings = get_settings()
        
        self.risk_manager = RiskManager(self.config)
        self.strategy = EMACrossoverStrategy()
        self.portfolio_manager = PortfolioManager()
        
        self.notifier = TelegramNotifier()
        self.clp_converter = CLPConverter()
        
        self.scheduler = BackgroundScheduler()
        self.paused = False
        log.info("TradingBot initialized with all components.")

    def get_open_positions_count(self) -> int:
        session = DatabaseSession.get_session()
        try:
            count = session.query(Trade).filter(Trade.status == "OPEN").count()
            return count
        finally:
            session.close()

    async def get_current_capital(self) -> float:
        if self.settings.paper_trading:
            from tradingbot.database.models import DigitalWallet
            session = DatabaseSession.get_session()
            try:
                telegram_id = str(self.settings.telegram_chat_id)
                wallet = session.query(DigitalWallet).filter(
                    DigitalWallet.telegram_id == telegram_id,
                    DigitalWallet.is_paper == True
                ).first()
                if wallet:
                    return float(wallet.balance_usd)
                return 10000.0
            except Exception as e:
                log.warning(f"Error querying DigitalWallet: {e}")
                return 10000.0
            finally:
                session.close()
        else:
            connector = CCXTConnector()
            try:
                balance = await connector.fetch_balance()
                base = self.config.bot.base_currency
                if base in balance and 'free' in balance[base]:
                    return float(balance[base]['free'])
                return 1000.0
            except Exception as e:
                log.warning(f"Could not fetch balance for capital, defaulting to 1000.0. Error: {e}")
                return 1000.0
            finally:
                await connector.close()

    def _get_current_timeframe(self) -> str:
        dt_cfg = self.config.bot.dynamic_timeframe
        if dt_cfg and dt_cfg.enabled:
            current_hour = datetime.utcnow().hour
            start_hr = dt_cfg.active_hours_utc.start
            end_hr = dt_cfg.active_hours_utc.end
            
            is_active = False
            if start_hr < end_hr:
                is_active = start_hr <= current_hour < end_hr
            else:
                is_active = current_hour >= start_hr or current_hour < end_hr
                
            return dt_cfg.active_timeframe if is_active else dt_cfg.passive_timeframe
        
        return self.config.bot.timeframe

    async def process_symbol(self, symbol: str, current_tf: str, total_capital: float, data_collector, order_executor) -> dict:
        try:
            df = await data_collector.get_historical_data(
                symbol=symbol, 
                timeframe=current_tf, 
                limit=50
            )
            if df.empty:
                log.warning(f"No historical data for {symbol}, skipping.")
                return {'symbol': symbol, 'decision': 'ERROR', 'reason': 'No historical data'}

            signal = self.strategy.generate_signal(df)
            current_price = float(df['close'].iloc[-1])
            
            # Manage open trades first! (Take Profit, Stop Loss, Reversals)
            close_result = await self.manage_open_trades(symbol, current_price, signal, order_executor)
            if close_result:
                # If a trade was closed, we return to avoid opening a new one in the exact same tick.
                return close_result

            if signal in ["BUY", "SELL"]:
                if signal == "SELL":
                    # We are currently running a Long-Only spot strategy. 
                    # SELL signals are exclusively used to close LONG positions (handled by manage_open_trades).
                    # We do not open new SHORT positions.
                    return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'SELL signal ignored for opening new shorts.'}
                
                log.info(f"Signal {signal} generated for {symbol}")
                
                current_positions = self.get_open_positions_count()
                
                session = DatabaseSession.get_session()
                open_trades = session.query(Trade).filter(Trade.status == "OPEN").all()
                session.close()
                
                open_trades_for_symbol = sum(1 for t in open_trades if t.symbol == symbol)
                is_dca = open_trades_for_symbol > 0
                
                current_exposure = sum(float(t.price_entry) * float(t.quantity) for t in open_trades)
                exposure_pct = current_exposure / total_capital
                
                max_allowed_pct = self.config.risk.max_capital_exposure_pct
                if not is_dca:
                    max_allowed_pct -= getattr(self.config.risk, "reserve_capital_pct", 0.30)
                
                stop_loss_price = current_price * (1 - self.config.risk.max_loss_per_trade_pct)
                amount = self.risk_manager.calculate_position_size(total_capital, current_price, stop_loss_price)
                if amount <= 0:
                    amount = 0.001
                
                trade_details_str = f" | Precio: {current_price} USD | Cant: {amount:.4f}"
                
                if not self.risk_manager.can_open_position(current_positions) and not is_dca:
                    log.info(f"Risk limits prevent opening new position for {symbol}")
                    return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Max open positions reached{trade_details_str}"}
                
                if exposure_pct + (amount * current_price / total_capital) > max_allowed_pct:
                    return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Fondo de Reserva / Capital Exposure (DCA={is_dca}){trade_details_str}"}
                
                if not self.risk_manager.check_daily_loss(0.0, total_capital):
                    return {'symbol': symbol, 'decision': 'BLOCKED', 'reason': f"Daily loss limit{trade_details_str}"}

                
                execution_result = await order_executor.execute_order(
                    symbol=symbol,
                    side=signal,
                    amount=amount,
                    order_type="MARKET"
                )

                self.portfolio_manager.record_open_trade(execution_result, strategy="EMACrossover")
                
                capital_clp = self.clp_converter.convert_usd_to_clp(total_capital)
                trade_details = {
                    "symbol": symbol,
                    "side": signal,
                    "amount": amount,
                    "price": current_price
                }
                
                report_msg = f"Operación ejecutada: {signal} de {amount} {symbol} a {current_price} USD"
                registrar_log("REPORTE", report_msg)
                
                self.notifier.send_trade_alert(trade_details, capital_clp)
                return {'symbol': symbol, 'decision': signal, 'reason': f"Ejecutado a {current_price} USD"}
            else:
                log.info(f"Signal is {signal} for {symbol}, no action taken.")
                return {'symbol': symbol, 'decision': 'HOLD', 'reason': 'No action needed'}
                
        except Exception as e:
            log.error(f"Error processing {symbol}: {e}")
            self.notifier.send_error_alert(f"Error processing {symbol}:\n{traceback.format_exc()}")
            return {'symbol': symbol, 'decision': 'ERROR', 'reason': str(e)}

    async def manage_open_trades(self, symbol: str, current_price: float, current_signal: str, order_executor) -> dict:
        """
        Manages open trades for a symbol, checking for Take Profit, Stop Loss, or Reversal signals.
        Returns a dict with closing details if a trade was closed, else None.
        """
        session = DatabaseSession.get_session()
        try:
            open_trades = session.query(Trade).filter(
                Trade.symbol == symbol,
                Trade.status == "OPEN"
            ).all()
            
            if not open_trades:
                return None
                
            tp_pct = self.config.risk.default_take_profit_pct
            sl_pct = self.config.risk.max_loss_per_trade_pct
            
            trading_mode = getattr(self.config.bot, "trading_mode", "trend")
            
            for trade in open_trades:
                should_close = False
                close_reason = ""
                
                if trade.side == "BUY":
                    # Ajuste del Take Profit dinámico según el modo
                    current_tp_pct = tp_pct
                    if trading_mode == "scalper":
                        current_tp_pct = 0.005 # 0.5% micro-gain
                        
                    # Take profit check (Siempre aplica)
                    if current_price >= float(trade.price_entry) * (1 + current_tp_pct):
                        should_close = True
                        close_reason = f"Take Profit (+{current_tp_pct*100:.1f}%)"
                        
                    # Stop loss check (Solo en modo trend)
                    elif current_price <= float(trade.price_entry) * (1 - sl_pct) and trading_mode not in ["target", "scalper"]:
                        should_close = True
                        close_reason = f"Stop Loss (-{sl_pct*100:.1f}%)"
                        
                    # Strategy Reversal check (Solo en modo trend)
                    elif current_signal == "SELL" and trading_mode not in ["target", "scalper"]:
                        should_close = True
                        close_reason = "Reversión de Estrategia (Señal SELL)"
                        
                if should_close:
                    log.info(f"Closing trade {trade.trade_id} for {symbol} due to {close_reason}. Entry: {trade.price_entry}, Current: {current_price}")
                    
                    execution_side = "SELL" if trade.side == "BUY" else "BUY"
                    execution_result = await order_executor.execute_order(
                        symbol=symbol,
                        side=execution_side,
                        amount=float(trade.quantity),
                        order_type="MARKET"
                    )
                    
                    executed_price = execution_result.get("price", current_price)
                    execution_result["price"] = executed_price
                    
                    closed_trade = self.portfolio_manager.record_close_trade(trade.trade_id, execution_result)
                    
                    pnl_usd = float(closed_trade.pnl) if closed_trade else 0.0
                    pnl_pct = float(closed_trade.pnl_pct) if closed_trade else 0.0
                    
                    total_capital = await self.get_current_capital()
                    capital_clp = self.clp_converter.convert_usd_to_clp(total_capital)
                    
                    trade_details = {
                        "symbol": symbol,
                        "side": execution_side,
                        "amount": float(trade.quantity),
                        "price": executed_price,
                        "pnl_usd": pnl_usd,
                        "pnl_pct": pnl_pct,
                        "reason": close_reason
                    }
                    
                    self.notifier.send_trade_alert(trade_details, capital_clp)
                    registrar_log("REPORTE", f"Operación CERRADA: {execution_side} de {trade.quantity} {symbol} a {executed_price} USD. PnL: {pnl_usd:.2f} USD ({pnl_pct*100:.2f}%). Razón: {close_reason}")
                    
                    return {'symbol': symbol, 'decision': 'CLOSED', 'reason': close_reason}
                    
        except Exception as e:
            log.error(f"Error managing open trades for {symbol}: {e}")
        finally:
            session.close()
            
        return None

    async def run_cycle(self):
        if self.paused:
            log.info("Bot is paused. Skipping cycle.")
            return
            
        log.info("--- Starting async run_cycle ---")
        connector = CCXTConnector()
        data_collector = DataCollector(connector)
        order_executor = OrderExecutor(connector)
        try:
            current_tf = self._get_current_timeframe()
            
            # Anti-Repainting Protection
            if current_tf.endswith('m'):
                tf_mins = int(current_tf.replace('m', ''))
                current_min = datetime.utcnow().minute
                if tf_mins > 1 and current_min % tf_mins != 0:
                    log.info(f"Timeframe {current_tf} selected. Minute {current_min} is not a multiple. Skipping cycle to avoid repainting.")
                    decisions = [{'symbol': s, 'decision': 'HOLD', 'reason': f"Waiting for {current_tf} candle to close"} for s in self.config.bot.trading_pairs]
                    self.portfolio_manager.record_decisions_bulk(decisions)
                    return
            
            # Obtener capital total una vez por ciclo (optimización)
            total_capital = await self.get_current_capital()
            
            # Ejecutar evaluación de símbolos de forma concurrente
            tasks = [self.process_symbol(symbol, current_tf, total_capital, data_collector, order_executor) for symbol in self.config.bot.trading_pairs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            bulk_decisions = []
            for result in results:
                if isinstance(result, Exception):
                    log.error(f"Unhandled exception in gather: {result}")
                elif isinstance(result, dict):
                    bulk_decisions.append(result)
            
            if bulk_decisions:
                self.portfolio_manager.record_decisions_bulk(bulk_decisions)

        except Exception as e:
            log.error(f"Critical unhandled error in run_cycle: {e}")
            self.notifier.send_error_alert(f"Critical unhandled error in run_cycle:\n{traceback.format_exc()}")
        finally:
            try:
                await connector.close()
            except Exception as ce:
                log.error(f"Error closing connector session: {ce}")
        log.info("--- Finished async run_cycle ---")

    async def execute_manual_order(self, symbol: str, side: str, amount: float):
        connector = CCXTConnector()
        executor = OrderExecutor(connector)
        try:
             res = await executor.execute_order(symbol, side, amount, "MARKET")
             self.portfolio_manager.record_open_trade(res, strategy=f"MANUAL_{side}")
             return res
        finally:
             await connector.close()

    def _run_cycle_sync(self):
        try:
            asyncio.run(self.run_cycle())
        except Exception as e:
            log.error(f"Error in sync runner: {e}")

    def start(self):
        log.info("Starting TradingBot Scheduler...")
        try:
            self.notifier.send_message("🚀 *TradingBot iniciado exitosamente!*\n⚙️ El bot ha arrancado y está operando. Evaluando el mercado...\nUsa /status para ver comandos.")
            
            # Iniciar el scheduler primero
            self.scheduler.add_job(self._run_cycle_sync, 'interval', minutes=1)
            
            # Correr run_cycle inmediatamente en el hilo actual antes de soltarlo (opcional, o podemos correrlo sync)
            self._run_cycle_sync()
            
            self.scheduler.start()
        except Exception as e:
            log.error(f"Critical error in TradingBot start(): {e}")
            self.notifier.send_error_alert(f"Critical error in TradingBot start():\n{traceback.format_exc()}")
            raise
