import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from tradingbot.core.config import load_yaml_config, AppConfig, MarketBiasConfig, TimeStopConfig, MicroDCAConfig, ProfitHarvestConfig
from tradingbot.services.market_bias_service import BTCMarketBiasFilter
from tradingbot.services.profit_harvest_service import ProfitHarvestEngine
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Trade, Portfolio, DigitalWallet, DecisionLog
from tradingbot.engine.trade_engine import TradeEngine
from tradingbot.engine.risk_manager import RiskManager
from sqlalchemy import select


@pytest.fixture
def mock_config():
    config = load_yaml_config("configs/agent_scalper.yaml")
    config.risk.max_open_positions = 50
    return config


@pytest.fixture
def mock_notifier():
    notifier = MagicMock()
    notifier.send_message = MagicMock()
    notifier.send_trade_alert = MagicMock()
    notifier.send_error_alert = MagicMock()
    return notifier


@pytest.fixture
def mock_clp():
    clp = MagicMock()
    clp.convert_usd_to_clp = MagicMock(return_value="35.000 CLP")
    return clp


@pytest.mark.asyncio
async def test_btc_market_bias_filter():
    """Verifica que BTCMarketBiasFilter calcule correctamente Bullish vs Bearish y use caché."""
    bias_filter = BTCMarketBiasFilter(
        config=MarketBiasConfig(enabled=True, btc_symbol="BTC/USDT", timeframe="1h", ema_period=50, cache_ttl_seconds=60)
    )

    # 1. Simular velas alcistas (precio > EMA 50)
    bullish_prices = [80000 + i * 50 for i in range(60)] # Precios crecientes hasta 82950
    df_bullish = pd.DataFrame({
        'timestamp': [datetime.now(timezone.utc) - timedelta(hours=60-i) for i in range(60)],
        'open': bullish_prices,
        'high': [p + 20 for p in bullish_prices],
        'low': [p - 20 for p in bullish_prices],
        'close': bullish_prices,
        'volume': [100.0] * 60
    })

    data_collector_mock = AsyncMock()
    data_collector_mock.get_historical_data.return_value = df_bullish

    bias, reason = await bias_filter.get_btc_bias(data_collector_mock)
    assert bias == "BULLISH"
    assert "BTC 1h" in reason
    assert data_collector_mock.get_historical_data.call_count == 1

    # 2. Verificar que la segunda llamada consecutiva usa la memoria caché (no llama a CCXT de nuevo)
    bias_cached, _ = await bias_filter.get_btc_bias(data_collector_mock)
    assert bias_cached == "BULLISH"
    assert data_collector_mock.get_historical_data.call_count == 1  # No aumentó

    # 3. Simular velas bajistas (precio < EMA 50)
    bias_filter._last_checked = None # Invalidar caché
    bearish_prices = [85000 - i * 100 for i in range(60)] # Precios decrecientes
    df_bearish = pd.DataFrame({
        'timestamp': [datetime.now(timezone.utc) - timedelta(hours=60-i) for i in range(60)],
        'open': bearish_prices,
        'high': [p + 20 for p in bearish_prices],
        'low': [p - 20 for p in bearish_prices],
        'close': bearish_prices,
        'volume': [100.0] * 60
    })
    data_collector_mock.get_historical_data.return_value = df_bearish

    bias_bear, reason_bear = await bias_filter.get_btc_bias(data_collector_mock)
    assert bias_bear == "BEARISH"
    assert "< EMA50" in reason_bear


@pytest.mark.asyncio
async def test_btc_bias_blocks_altcoin_buy(mock_config, mock_notifier, mock_clp):
    """Verifica que una señal BUY en Altcoin quede bloqueada si BTC Bias es BEARISH."""
    pm = PortfolioManager()
    risk_manager = RiskManager(mock_config)
    strategy_mock = MagicMock()
    strategy_mock.generate_signal.return_value = "BUY"
    strategy_mock.slow_period = 21
    strategy_mock.name = "EMACrossover"

    trade_engine = TradeEngine(
        config=mock_config,
        risk_manager=risk_manager,
        portfolio_manager=pm,
        strategy=strategy_mock,
        notifier=mock_notifier,
        clp_converter=mock_clp
    )

    test_symbol = "TESTALT/USDT"

    # Forzar sesgo bajista
    trade_engine.market_bias_filter.get_btc_bias = AsyncMock(return_value=("BEARISH", "BTC 1h $80,000 < EMA50 $82,500"))

    data_collector = AsyncMock()
    df_sui = pd.DataFrame({
        'timestamp': [datetime.utcnow() - timedelta(minutes=50-i) for i in range(50)],
        'open': [1.20] * 50,
        'high': [1.25] * 50,
        'low': [1.18] * 50,
        'close': [1.22] * 50,
        'volume': [1000] * 50
    })
    data_collector.get_historical_data.return_value = df_sui

    order_executor = AsyncMock()

    result = await trade_engine.process_symbol(
        symbol=test_symbol,
        current_tf="1m",
        total_capital=50.0,
        data_collector=data_collector,
        order_executor=order_executor,
        agent_id="scalper_t1"
    )

    assert result['decision'] == 'BLOCKED'
    assert "BTC Macro Bias Bearish" in result['reason']
    assert order_executor.execute_order.call_count == 0


@pytest.mark.asyncio
async def test_safe_time_stop_multi_cycle_confirmation(mock_config, mock_notifier, mock_clp):
    """Verifica que el Seguro de Salida por Tiempo requiera 3 confirmaciones y se resetee si rebota."""
    pm = PortfolioManager()
    risk_manager = RiskManager(mock_config)
    strategy_mock = MagicMock()
    strategy_mock.generate_signal.return_value = "HOLD"

    trade_engine = TradeEngine(
        config=mock_config,
        risk_manager=risk_manager,
        portfolio_manager=pm,
        strategy=strategy_mock,
        notifier=mock_notifier,
        clp_converter=mock_clp
    )

    import uuid
    uid = uuid.uuid4().hex[:6]
    test_trade_id = f"test_time_stop_trade_{uid}"
    test_symbol = f"TESTNEAR_{uid}/USDT"
    entry_price = 10.0

    # Crear trade abierto con 130 minutos de antigüedad (supera 120m)
    async with DatabaseSession.get_async_session() as session:
        trade = Trade(
            trade_id=test_trade_id,
            symbol=test_symbol,
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("1.0"),
            price_entry=Decimal(str(entry_price)),
            status="OPEN",
            opened_at=datetime.utcnow() - timedelta(minutes=130),
            agent_id="scalper_t1",
            is_paper=True
        )
        session.add(trade)
        await session.commit()

    order_executor = AsyncMock()
    order_executor.execute_order.return_value = {
        "order_id": f"close_order_{uid}",
        "symbol": test_symbol,
        "side": "SELL",
        "amount": 1.0,
        "price": 9.90,
        "type": "MARKET",
        "is_paper": True
    }

    # Ciclo 1: Precio 9.90 (-1.0% de pérdida, menor al SL hard pero < 0). Debe incrementar a 1/3
    res1 = await trade_engine.manage_open_trades(test_symbol, 9.90, "HOLD", order_executor, 50.0, "scalper_t1")
    assert res1 is None # NO cierra
    assert trade_engine.time_stop_tracker.get(test_trade_id) == 1

    # Ciclo 2: Sigue en pérdida (9.92). Debe incrementar a 2/3
    res2 = await trade_engine.manage_open_trades(test_symbol, 9.92, "HOLD", order_executor, 50.0, "scalper_t1")
    assert res2 is None # NO cierra
    assert trade_engine.time_stop_tracker.get(test_trade_id) == 2

    # Rebote Técnico: Precio sube a 10.02 (+0.2% ganancia pero aún no llega al TP +0.5%).
    # El seguro debe RESETEARSE a 0 para no vender prematuramente
    res_bounce = await trade_engine.manage_open_trades(test_symbol, 10.02, "HOLD", order_executor, 50.0, "scalper_t1")
    assert res_bounce is None
    assert test_trade_id not in trade_engine.time_stop_tracker # Reseteado!

    # Nuevos ciclos en pérdida:
    # Ciclo 1 (post-rebote)
    await trade_engine.manage_open_trades(test_symbol, 9.90, "HOLD", order_executor, 50.0, "scalper_t1")
    assert trade_engine.time_stop_tracker.get(test_trade_id) == 1
    # Ciclo 2
    await trade_engine.manage_open_trades(test_symbol, 9.90, "HOLD", order_executor, 50.0, "scalper_t1")
    assert trade_engine.time_stop_tracker.get(test_trade_id) == 2
    # Ciclo 3 -> 3ra confirmación consecutiva cumplida: ¡Ejecuta Safe Time-Stop!
    res_close = await trade_engine.manage_open_trades(test_symbol, 9.90, "HOLD", order_executor, 50.0, "scalper_t1")
    assert res_close is not None
    assert res_close['decision'] == 'CLOSED'
    assert "Safe Time-Stop" in res_close['reason']
    assert test_trade_id not in trade_engine.time_stop_tracker


@pytest.mark.asyncio
async def test_micro_dca_entry_and_pullback_consolidation(mock_config, mock_notifier, mock_clp):
    """Verifica la ejecución de Tramo 1 y posterior consolidación en Tramo 2 (Micro DCA)."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    pm = PortfolioManager()
    risk_manager = RiskManager(mock_config)
    strategy_mock = MagicMock()
    strategy_mock.generate_signal.return_value = "BUY"
    strategy_mock.slow_period = 21
    strategy_mock.name = "EMACrossover"

    trade_engine = TradeEngine(
        config=mock_config,
        risk_manager=risk_manager,
        portfolio_manager=pm,
        strategy=strategy_mock,
        notifier=mock_notifier,
        clp_converter=mock_clp
    )

    # Permitir BTC Bias
    trade_engine.market_bias_filter.get_btc_bias = AsyncMock(return_value=("BULLISH", "BTC 1h Bullish"))

    test_symbol = f"TESTDCA_{uid}/USDT"

    order_executor = AsyncMock()
    
    # 1. Ejecución de Tramo 1 ($0.40 USD)
    order_executor.execute_order.return_value = {
        "order_id": f"dca_order_1_{uid}",
        "symbol": test_symbol,
        "side": "BUY",
        "amount": 1.0,  # 1 ADA a $0.40
        "price": 0.4000,
        "type": "MARKET",
        "is_paper": True
    }

    data_collector = AsyncMock()
    df_ada = pd.DataFrame({
        'timestamp': [datetime.utcnow() - timedelta(minutes=50-i) for i in range(50)],
        'open': [0.40] * 50,
        'high': [0.41] * 50,
        'low': [0.39] * 50,
        'close': [0.40] * 50,
        'volume': [1000] * 50
    })
    data_collector.get_historical_data.return_value = df_ada

    res1 = await trade_engine.process_symbol(test_symbol, "1m", 50.0, data_collector, order_executor, "scalper_t1")
    assert res1['decision'] == 'BUY_DCA_1'
    assert "Micro DCA Tramo 1" in res1['reason']

    # 2. Pullback a $0.3950 (-1.25% de retroceso, dentro de [0.6%, 2.5%])
    df_ada_pullback = df_ada.copy()
    df_ada_pullback.loc[df_ada_pullback.index[-1], 'close'] = 0.3950
    data_collector.get_historical_data.return_value = df_ada_pullback

    order_executor.execute_order.return_value = {
        "order_id": f"dca_order_2_{uid}",
        "symbol": test_symbol,
        "side": "BUY",
        "amount": 0.886, # Tramo 2
        "price": 0.3950,
        "type": "MARKET",
        "is_paper": True
    }

    res2 = await trade_engine.process_symbol(test_symbol, "1m", 50.0, data_collector, order_executor, "scalper_t1")
    assert res2['decision'] == 'BUY_DCA_2'
    assert "Micro DCA Tramo 2" in res2['reason']

    # Verificar que el trade consolidado tiene dca_step = 2 y nuevo precio promedio ponderado
    async with DatabaseSession.get_async_session() as session:
        tr = (await session.execute(select(Trade).filter(Trade.symbol == test_symbol, Trade.status == "OPEN"))).scalars().first()
        assert tr is not None
        assert tr.dca_step == 2
        assert float(tr.price_entry) < 0.4000 # Precio promedio mejorado


@pytest.mark.asyncio
async def test_asset_monetization_and_profit_harvester():
    """Verifica la liquidación contable de activos y el motor de cosecha automática."""
    import uuid
    uid = uuid.uuid4().hex[:6]
    test_asset = f"TEST_{uid}"
    pm = PortfolioManager()
    
    # 1. Crear holding simulado en portfolio
    async with DatabaseSession.get_async_session() as session:
        pf = Portfolio(
            asset=test_asset,
            quantity=Decimal("10.0"),
            avg_price=Decimal("1.00"),
            current_price=Decimal("5.00"), # +400% ROI
            unrealized_pnl=Decimal("40.00"),
            is_paper=True,
            agent_id="scalper_t1"
        )
        session.add(pf)
        await session.commit()

    # 2. Ejecutar monetización
    res = await pm.monetize_asset_async(test_asset, price=5.00, is_paper=True)
    assert res['status'] == 'success'
    assert res['quantity'] == 10.0
    assert res['realized_pnl'] == 40.00
    assert res['total_credited'] == 50.00

    # 3. Verificar que el holding quedó en 0.0
    async with DatabaseSession.get_async_session() as session:
        pf_check = (await session.execute(select(Portfolio).filter(Portfolio.asset == test_asset, Portfolio.is_paper == True))).scalars().first()
        assert float(pf_check.quantity) == 0.0
        assert float(pf_check.avg_price) == 0.0

        # Verificar que se registró el trade de liquidación
        trade_check = (await session.execute(select(Trade).filter(Trade.symbol == f"{test_asset}/USDT", Trade.strategy == "ProfitHarvesting"))).scalars().first()
        assert trade_check is not None
        assert float(trade_check.pnl) == 40.00
