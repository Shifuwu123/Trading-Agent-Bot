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
