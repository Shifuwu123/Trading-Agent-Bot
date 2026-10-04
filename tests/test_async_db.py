import pytest
import pytest_asyncio
from decimal import Decimal
from tradingbot.execution.portfolio_manager import DatabaseSession, PortfolioManager
from tradingbot.database.models import Trade, Portfolio, DigitalWallet, Candle, DecisionLog

@pytest.mark.asyncio
async def test_async_database_session():
    """Verifica que DatabaseSession.get_async_session opera correctamente con aiosqlite."""
    DatabaseSession.initialize()
    async with DatabaseSession.get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(DigitalWallet).filter(DigitalWallet.is_paper == True))
        wallet = result.scalars().first()
        assert wallet is not None
        assert float(wallet.balance_usd) > 0

@pytest.mark.asyncio
async def test_async_portfolio_manager_methods():
    """Verifica operaciones asíncronas de registro y consulta en PortfolioManager."""
    pm = PortfolioManager()
    
    # 1. Test decision async
    await pm.record_decision_async("SOL/USDT", "HOLD", "Test async decision")
    
    # 2. Test bulk decisions async
    bulk = [
        {"symbol": "BTC/USDT", "decision": "HOLD", "reason": "Test bulk 1"},
        {"symbol": "ETH/USDT", "decision": "HOLD", "reason": "Test bulk 2"}
    ]
    await pm.record_decisions_bulk_async(bulk)
    
    # 3. Test asset price async
    await pm.update_asset_price_async("SOL/USDT", 130.5, is_paper=True)
    
    # 4. Test cashflow summary async
    summary = await pm.get_cashflow_summary_async()
    assert "balance" in summary
    assert summary["balance"] > 0
    
    # 5. Test portfolio summary async
    portfolio = await pm.get_portfolio_summary_async()
    assert isinstance(portfolio, list)

    # 6. Test reset_pnl_async
    reset_res = await pm.reset_pnl_async(is_paper=True)
    assert reset_res["status"] == "success"
    assert "archived_trades_count" in reset_res

