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
from tradingbot.database.models import Trade, BotCommand
from tradingbot.utils.logger import log, registrar_log
from tradingbot.interfaces.telegram.notifier import TelegramNotifier
from tradingbot.utils.clp_converter import CLPConverter
from tradingbot.engine.trade_engine import TradeEngine
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
        
        self.trade_engine = TradeEngine(
            config=self.config,
            risk_manager=self.risk_manager,
            portfolio_manager=self.portfolio_manager,
            strategy=self.strategy,
            notifier=self.notifier,
            clp_converter=self.clp_converter
        )
        log.info("TradingBot initialized with TradeEngine orchestrator.")

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
            tasks = [self.trade_engine.process_symbol(symbol, current_tf, total_capital, data_collector, order_executor) for symbol in self.config.bot.trading_pairs]
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

    def _process_dashboard_commands(self):
        session = DatabaseSession.get_session()
        try:
            commands = session.query(BotCommand).filter(BotCommand.status == 'PENDING').order_by(BotCommand.id.asc()).all()
            for cmd in commands:
                c_name = cmd.command.upper()
                c_args = cmd.args
                
                if c_name == 'PAUSE':
                    self.paused = True
                    log.info("DASHBOARD CMD: Bot paused.")
                elif c_name == 'RESUME':
                    self.paused = False
                    log.info("DASHBOARD CMD: Bot resumed.")
                elif c_name == 'MODE':
                    if c_args in ['trend', 'target', 'scalper']:
                        self.config.bot.trading_mode = c_args
                        # Persist to config.yaml...
                        try:
                            import yaml
                            with open("config.yaml", "r") as f:
                                data = yaml.safe_load(f)
                            if "bot" in data:
                                data["bot"]["trading_mode"] = c_args
                            with open("config.yaml", "w") as f:
                                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                        except Exception as e:
                            log.error(f"Error persisting mode: {e}")
                        log.info(f"DASHBOARD CMD: Mode changed to {c_args}")
                
                cmd.status = 'PROCESSED'
            session.commit()
        except Exception as e:
            log.error(f"Error in dashboard command processor: {e}")
        finally:
            session.close()

    def start(self):
        log.info("Starting TradingBot Scheduler...")
        try:
            self.notifier.send_message("🚀 *TradingBot iniciado exitosamente!*\n⚙️ El bot ha arrancado y está operando. Evaluando el mercado...\nUsa /status para ver comandos.")
            
            # Iniciar el scheduler principal (cada minuto)
            self.scheduler.add_job(self._run_cycle_sync, 'interval', minutes=1)
            
            # Iniciar el scheduler del Dashboard Commands (cada 5 segundos)
            self.scheduler.add_job(self._process_dashboard_commands, 'interval', seconds=5)
            
            # Correr run_cycle inmediatamente en el hilo actual antes de soltarlo
            self._run_cycle_sync()
            
            self.scheduler.start()
        except Exception as e:
            log.error(f"Critical error in TradingBot start(): {e}")
            self.notifier.send_error_alert(f"Critical error in TradingBot start():\n{traceback.format_exc()}")
            raise
