import pytest
import os
import time
import ccxt.async_support as ccxt
from unittest.mock import AsyncMock, patch, MagicMock
from tradingbot.market.ccxt_connector import CCXTConnector
from tradingbot.engine.trade_engine import TradeEngine

@pytest.mark.asyncio
async def test_ccxt_connector_caching_and_load():
    connector = CCXTConnector()
    # Ensure cache directory is configured
    assert connector._cache_dir.endswith("data/cache")
    
    # Test ensure_markets_loaded populates markets
    markets = await connector.ensure_markets_loaded()
    assert isinstance(markets, dict)
    assert len(markets) > 0
    assert connector.cache_key in CCXTConnector._cached_markets
    
    # Test second instance reuses memory cache
    connector2 = CCXTConnector()
    assert len(connector2.exchange.markets) > 0
    assert len(connector2.exchange.markets) == len(markets)
    
    await connector.close()
    await connector2.close()

@pytest.mark.asyncio
async def test_ccxt_fetch_ohlcv_retry_on_timeout():
    connector = CCXTConnector()
    
    # Pre-populate dummy markets
    connector.exchange.markets = {"BTC/USDT": {"id": "BTCUSDT", "symbol": "BTC/USDT"}}
    
    # Mock exchange fetch_ohlcv to fail once with RequestTimeout then succeed
    mock_fetch = AsyncMock(side_effect=[
        ccxt.RequestTimeout("Simulated timeout"),
        [[1600000000000, 100, 105, 95, 102, 1000]]
    ])
    connector.exchange.fetch_ohlcv = mock_fetch
    
    ohlcv = await connector.fetch_ohlcv("BTC/USDT", "1m", limit=1, max_retries=2)
    assert len(ohlcv) == 1
    assert mock_fetch.call_count == 2
    
    await connector.close()

@pytest.mark.asyncio
async def test_trade_engine_handles_network_timeout_gracefully():
    # Mock components for TradeEngine
    config_mock = MagicMock()
    risk_manager_mock = MagicMock()
    portfolio_manager_mock = MagicMock()
    strategy_mock = MagicMock()
    strategy_mock.slow_period = 21
    notifier_mock = MagicMock()
    clp_converter_mock = MagicMock()
    
    engine = TradeEngine(
        config=config_mock,
        risk_manager=risk_manager_mock,
        portfolio_manager=portfolio_manager_mock,
        strategy=strategy_mock,
        notifier=notifier_mock,
        clp_converter=clp_converter_mock
    )
    
    data_collector_mock = MagicMock()
    data_collector_mock.get_historical_data = AsyncMock(
        side_effect=ccxt.RequestTimeout("Binance exchangeInfo timeout")
    )
    order_executor_mock = MagicMock()
    
    result = await engine.process_symbol(
        symbol="ADA/USDT",
        current_tf="5m",
        total_capital=100.0,
        data_collector=data_collector_mock,
        order_executor=order_executor_mock
    )
    
    # Check that decision is HOLD and error alert was NOT sent to Telegram
    assert result["decision"] == "HOLD"
    assert "Network timeout transitorio" in result["reason"]
    notifier_mock.send_error_alert.assert_not_called()
