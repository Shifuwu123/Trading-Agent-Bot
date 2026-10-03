import asyncio
import sys
from pathlib import Path

# Add the project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradingbot.core.config import load_yaml_config, get_settings
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.market.ccxt_connector import CCXTConnector
from tradingbot.market.data_collector import DataCollector
from tradingbot.strategies.ema_crossover import EMACrossoverStrategy
from tradingbot.execution.order_executor import OrderExecutor
from tradingbot.execution.portfolio_manager import PortfolioManager
from tradingbot.utils.logger import log

def main():
    try:
        log.info("Iniciando prueba de integración de módulos...")
        
        # 1. Test Config & Risk Manager
        log.info("1. Probando Config y RiskManager...")
        config = load_yaml_config("config.yaml")
        risk_manager = RiskManager(config)
        
        # Simulate a trade risk check
        can_open = risk_manager.can_open_position(1)
        log.info(f"Can open position (1 open): {can_open}")
        
        # 2. Test Market Connector
        log.info("2. Probando CCXTConnector (Binance Testnet)...")
        settings = get_settings()
        
        # Iniciar sin api keys reales, solo para ver si levanta la clase y testnet
        connector = CCXTConnector()
        # Fetch mock balance or just ticker if keys are empty
        if not settings.exchange_api_key or settings.exchange_api_key == "your_api_key_here":
            log.warning("No hay API keys configuradas, saltando test de balance, intentando fetch_ticker...")
            ticker = connector.fetch_ticker("BTC/USDT")
            log.info(f"Ticker BTC/USDT: {ticker['last'] if ticker else 'N/A'}")
        else:
            balance = connector.fetch_balance()
            log.info(f"Balance: {balance}")

        # 3. Test Data Collector
        log.info("3. Probando DataCollector...")
        collector = DataCollector(connector)
        df = collector.get_historical_data("BTC/USDT", timeframe="1h", limit=50)
        log.info(f"OHLCV DataFrame shape: {df.shape if df is not None else 'N/A'}")
        
        # 4. Test Strategy
        signal = "HOLD"
        if df is not None and not df.empty:
            log.info("4. Probando EMACrossoverStrategy...")
            strategy = EMACrossoverStrategy(fast_period=9, slow_period=21)
            signal = strategy.generate_signal(df)
            log.info(f"Señal generada: {signal}")
            
        # 5. Test Execution (Paper Trading)
        log.info("5. Probando OrderExecutor y PortfolioManager en modo Paper...")
        executor = OrderExecutor(connector)
        portfolio = PortfolioManager()
        
        # Simular una compra sin importar la señal real para probar la BD
        exec_result = executor.execute_order("BTC/USDT", "BUY", 0.01)
        log.info(f"Resultado de ejecución: {exec_result}")
        
        # Registrar trade en DB
        trade = portfolio.record_open_trade(exec_result, strategy="test")
        log.info(f"Trade guardado en DB con ID local: {trade.id}, Estado: {trade.status}")
        
        log.info("✅ Integración básica y BD exitosa.")
        
    except Exception as e:
        log.error(f"Error en la prueba de integración: {e}")

if __name__ == "__main__":
    main()
