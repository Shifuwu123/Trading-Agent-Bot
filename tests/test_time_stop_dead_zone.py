"""
tests/test_time_stop_dead_zone.py

Pruebas para verificar el Safe Time-Stop con Banda Muerta (Dead Zone).
Valida que micro-pérdidas insignificantes (-0.05% a -0.29%) no sean cortadas prematuramente,
eliminando el 'efecto cortacésped' identificado en la auditoría.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from tradingbot.engine.trade_engine import TradeEngine
from tradingbot.core.config import load_yaml_config
from tradingbot.database.models import Trade


@pytest.mark.asyncio
async def test_time_stop_dead_zone_tolerates_minor_loss():
    config = load_yaml_config("configs/agent_scalper.yaml")
    config.bot.trading_mode = "scalper"
    config.risk.time_stop.enabled = True
    config.risk.time_stop.min_duration_minutes = 120
    config.risk.time_stop.consecutive_cycles_required = 3
    config.risk.time_stop.dead_zone_pct = 0.0030 # 0.30%

    engine = TradeEngine(
        config=config,
        risk_manager=MagicMock(),
        portfolio_manager=MagicMock(),
        strategy=MagicMock(),
        notifier=MagicMock(),
        clp_converter=MagicMock(),
    )

    # Crear trade abierto con 130 minutos de duración y pérdida leve (-0.10%), dentro de la Dead Zone
    mock_trade = Trade(
        trade_id="mock_trade_dead_zone",
        symbol="NEAR/USDT",
        side="BUY",
        quantity=1.0,
        price_entry=5.00,
        status="OPEN",
        agent_id="scalper_t1",
        opened_at=datetime.utcnow() - timedelta(minutes=130),
    )

    current_price = 4.995 # Pérdida de -0.10% (dentro de 0.0% a -0.30%)

    with patch("tradingbot.engine.trade_engine.DatabaseSession.get_async_session") as mock_get_sess:
        mock_sess = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_trade]
        mock_sess.execute = AsyncMock(return_value=mock_res)
        mock_get_sess.return_value.__aenter__.return_value = mock_sess

        mock_executor = AsyncMock()
        await engine.manage_open_trades(
            symbol="NEAR/USDT",
            current_price=current_price,
            current_signal="HOLD",
            order_executor=mock_executor,
            total_capital=10.0,
            agent_id="scalper_t1",
        )

        # No debe ejecutarse ninguna orden de cierre porque está dentro de la Dead Zone
        mock_executor.execute_order.assert_not_called()
        assert "mock_trade_dead_zone" not in engine.time_stop_tracker


@pytest.mark.asyncio
async def test_time_stop_dead_zone_closes_on_real_loss():
    config = load_yaml_config("configs/agent_scalper.yaml")
    config.bot.trading_mode = "scalper"
    config.risk.time_stop.enabled = True
    config.risk.time_stop.min_duration_minutes = 120
    config.risk.time_stop.consecutive_cycles_required = 2
    config.risk.time_stop.dead_zone_pct = 0.0030

    mock_pm = MagicMock()
    mock_closed = MagicMock()
    mock_closed.pnl = -0.03
    mock_closed.pnl_pct = -0.006
    mock_closed.fee_usd = 0.001
    mock_closed.pnl_net_usd = -0.031
    mock_closed.pnl_clp = -29.0
    mock_pm.record_close_trade_async = AsyncMock(return_value=mock_closed)

    engine = TradeEngine(
        config=config,
        risk_manager=MagicMock(),
        portfolio_manager=mock_pm,
        strategy=MagicMock(),
        notifier=MagicMock(),
        clp_converter=MagicMock(),
    )

    mock_trade = Trade(
        trade_id="mock_trade_real_loss",
        symbol="NEAR/USDT",
        side="BUY",
        quantity=1.0,
        price_entry=5.00,
        status="OPEN",
        agent_id="scalper_t1",
        opened_at=datetime.utcnow() - timedelta(minutes=130),
    )

    current_price = 4.97 # Pérdida de -0.60% (supera el -0.30% de la Dead Zone)

    with patch("tradingbot.engine.trade_engine.DatabaseSession.get_async_session") as mock_get_sess:
        mock_sess = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_trade]
        mock_sess.execute = AsyncMock(return_value=mock_res)
        mock_get_sess.return_value.__aenter__.return_value = mock_sess

        mock_executor = AsyncMock()
        mock_executor.execute_order.return_value = {"price": 4.97}

        # Ciclo 1: Acumula confirmación
        await engine.manage_open_trades(
            symbol="NEAR/USDT",
            current_price=current_price,
            current_signal="HOLD",
            order_executor=mock_executor,
            total_capital=10.0,
            agent_id="scalper_t1",
        )
        assert engine.time_stop_tracker.get("mock_trade_real_loss") == 1
        mock_executor.execute_order.assert_not_called()

        # Ciclo 2: Alcanza 2 ciclos consecutivos requeridos -> debe ejecutar cierre
        await engine.manage_open_trades(
            symbol="NEAR/USDT",
            current_price=current_price,
            current_signal="HOLD",
            order_executor=mock_executor,
            total_capital=10.0,
            agent_id="scalper_t1",
        )
        mock_executor.execute_order.assert_called_once()
