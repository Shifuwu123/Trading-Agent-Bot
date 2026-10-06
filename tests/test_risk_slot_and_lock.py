import pytest
from decimal import Decimal
from tradingbot.core.config import load_yaml_config
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import DigitalWallet, Portfolio

def test_risk_manager_slot_allocation():
    config = load_yaml_config("config.yaml")
    config.risk.max_open_positions = 10
    config.risk.max_capital_exposure_pct = 1.00
    config.risk.reserve_capital_pct = 0.30
    config.risk.max_loss_per_trade_pct = 0.02
    config.risk.min_order_usd = 1.00
    
    rm = RiskManager(config)
    total_capital = 50.0
    current_price = 10.0
    stop_loss = 9.80  # 2% stop loss
    
    # Position size should be limited by slot budget:
    # Usable capital = 70% of $50 = $35
    # Max slots = 10 -> $3.50 max investment per slot
    # Expected units = 3.50 / 10.0 = 0.35 units
    size = rm.calculate_position_size(total_capital, current_price, stop_loss, is_dca=False)
    assert size > 0
    assert size * current_price <= 3.51  # Within floating precision of $3.50

@pytest.mark.asyncio
async def test_wallet_non_negative_clamp():
    pm = PortfolioManager()
    session = DatabaseSession.get_session()
    try:
        wallet = session.query(DigitalWallet).filter(DigitalWallet.is_paper == True).first()
        assert wallet is not None
        initial_balance = float(wallet.balance_usd)
        
        # Simulate buying an asset whose cost exceeds the wallet balance
        excessive_amount = (initial_balance + 100.0) / 10.0
        pm._update_virtual_wallet(session, "BUY", excessive_amount, 10.0)
        session.commit()
        
        # Verify it clamped to 0.0, never negative
        assert wallet.balance_usd == Decimal("0.0")
        
        # Restore balance for test cleanliness
        wallet.balance_usd = Decimal(str(initial_balance))
        session.commit()
    finally:
        session.close()

@pytest.mark.asyncio
async def test_total_equity_calculation():
    pm = PortfolioManager()
    cash = await pm.get_liquid_cash_async()
    equity = await pm.get_total_equity_async()
    assert cash >= 0
    assert equity >= cash

@pytest.mark.asyncio
async def test_no_duplicate_buys_for_open_symbol():
    from unittest.mock import MagicMock, AsyncMock
    import pandas as pd
    from tradingbot.engine.trade_engine import TradeEngine
    from tradingbot.database.models import Trade

    config = load_yaml_config("config.yaml")
    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    strategy.slow_period = 21
    strategy.generate_signal.return_value = "BUY"
    notifier = MagicMock()
    clp_converter = MagicMock()
    clp_converter.convert_usd_to_clp.return_value = 50000

    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)
    
    # Insert a dummy open trade
    session = DatabaseSession.get_session()
    dummy_trade = Trade(
        trade_id="test_dup_001",
        symbol="TEST/USDT",
        side="BUY",
        quantity=1.0,
        price_entry=10.0,
        status="OPEN"
    )
    session.add(dummy_trade)
    session.commit()
    session.close()

    try:
        # Mock data collector returning dummy candle
        mock_collector = MagicMock()
        mock_df = pd.DataFrame({'close': [10.0] * 80})
        mock_collector.get_historical_data = AsyncMock(return_value=mock_df)
        mock_executor = MagicMock()
        mock_executor.execute_order = AsyncMock()

        result = await te.process_symbol("TEST/USDT", "1m", 50.0, mock_collector, mock_executor)
        
        # Must return HOLD with informative reason
        assert result['decision'] == "HOLD"
        assert "Posición ya abierta" in result['reason']
        mock_executor.execute_order.assert_not_called()
    finally:
        # Cleanup
        session = DatabaseSession.get_session()
        session.query(Trade).filter(Trade.trade_id == "test_dup_001").delete()
        session.commit()
        session.close()


@pytest.mark.asyncio
async def test_individual_coin_reserve_order_size():
    from unittest.mock import MagicMock, AsyncMock
    import pandas as pd
    from tradingbot.engine.trade_engine import TradeEngine
    from tradingbot.database.models import Trade

    config = load_yaml_config("config.yaml")
    config.risk.coin_reserve_pct = 0.25
    config.risk.max_coin_order_pct = 0.75
    config.risk.min_order_usd = 0.10

    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    strategy.name = "EMACrossover"
    strategy.slow_period = 21
    strategy.generate_signal.return_value = "BUY"
    notifier = MagicMock()
    clp_converter = MagicMock()
    clp_converter.convert_usd_to_clp.return_value = 50000

    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    mock_collector = MagicMock()
    mock_df = pd.DataFrame({'close': [10.0] * 80})
    mock_collector.get_historical_data = AsyncMock(return_value=mock_df)

    mock_executor = MagicMock()
    mock_executor.execute_order = AsyncMock(return_value={
        "order_id": "test_ord_001",
        "symbol": "SOL/USDT",
        "side": "BUY",
        "amount": 0.075,
        "price": 10.0,
        "type": "MARKET",
        "is_paper": True,
        "status": "FILLED"
    })

    try:
        # With $1.00 USD base and 0 PnL, max order is 0.75 USD. At price $10, amount = 0.075 units.
        result = await te.process_symbol("SOL/USDT", "1m", 16.0, mock_collector, mock_executor, agent_id="scalper_t1")

        assert result['decision'] == "BUY"
        mock_executor.execute_order.assert_called_once()
        call_kwargs = mock_executor.execute_order.call_args.kwargs
        assert call_kwargs['amount'] == pytest.approx(0.075, rel=1e-3)
        assert call_kwargs['price'] == 10.0
    finally:
        session = DatabaseSession.get_session()
        session.query(Trade).filter(Trade.trade_id == "test_ord_001").delete()
        session.commit()
        session.close()


def test_trade_engine_lock_across_different_event_loops():
    """Verifica que TradeEngine.trade_lock se reasocie automáticamente a nuevos event loops sin lanzar RuntimeError."""
    import asyncio
    from unittest.mock import MagicMock
    from tradingbot.engine.trade_engine import TradeEngine

    config = load_yaml_config("config.yaml")
    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    notifier = MagicMock()
    clp_converter = MagicMock()

    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    async def acquire_in_loop():
        async with te.trade_lock:
            await asyncio.sleep(0.01)
        return id(te.trade_lock)

    # Ciclo 1 en Loop 1
    lock_id_1 = asyncio.run(acquire_in_loop())

    # Ciclo 2 en Loop 2 (nuevo bucle creado por asyncio.run)
    lock_id_2 = asyncio.run(acquire_in_loop())

    # Ciclo 3 en Loop 3
    lock_id_3 = asyncio.run(acquire_in_loop())

    # Cada ciclo en un loop diferente debe generar un Lock fresco asociado a ese loop
    assert lock_id_1 != lock_id_2
    assert lock_id_2 != lock_id_3


def test_trade_engine_lock_shared_within_same_event_loop():
    """Verifica que múltiples tareas concurrentes dentro del mismo event loop compartan la misma instancia de Lock."""
    import asyncio
    from unittest.mock import MagicMock
    from tradingbot.engine.trade_engine import TradeEngine

    config = load_yaml_config("config.yaml")
    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    notifier = MagicMock()
    clp_converter = MagicMock()

    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    async def run_concurrent():
        async def task_a():
            async with te.trade_lock:
                await asyncio.sleep(0.02)
            return id(te.trade_lock)

        async def task_b():
            async with te.trade_lock:
                await asyncio.sleep(0.02)
            return id(te.trade_lock)

        id_a, id_b = await asyncio.gather(task_a(), task_b())
        assert id_a == id_b
        return id_a

    res_id = asyncio.run(run_concurrent())
    assert res_id is not None


