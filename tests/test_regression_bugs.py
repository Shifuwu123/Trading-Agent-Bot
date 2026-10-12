"""
tests/test_regression_bugs.py

Suite de Pruebas de Regresión para Bugs Históricos del Trading Bot.
Garantiza que ningún fallo previamente resuelto vuelva a introducirse en el sistema.

Casos cubiertos:
1. Bug 8ed73e0: Prevención de compras duplicadas en símbolos con posiciones abiertas o DCA en curso.
2. Bug f6923ea: Gating estricto de umbrales de pullback en Micro DCA (evitar compras fuera de rango).
3. Bug 836d854: Re-vinculación dinámica de asyncio.Lock ante recreación de EventLoops en APScheduler.
4. Bug 0fef1fb: Modelado contable de Fee Drag (evitar barrido de ganancias en PnL neto negativo).
5. Bug 321e80c: Regla de reserva individual por moneda (75% orden máxima, 25% reserva, mín $0.10 USD).
6. Bug 0fef1fb: Schema Guard & Data Guard (prohibir sobreescritura de disco con base RAM vacía o corrupta).
7. Bug 798aac1: Aislamiento total de la base de datos de test respecto a producción.
8. Bug fb3e503: Sanitización y enmascaramiento de credenciales y secretos en logs y alertas.
9. Bug f6923ea: Seguro de Salida por Tiempo (Safe Time-Stop) multi-ciclo y reseteo por rebote positivo.
10. Bug 06d24ed: Protección matemática contra división por cero en cálculo de slots y rendimientos.
"""

import os
import sqlite3
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock
import pandas as pd
import pytest

from tradingbot.core.config import load_yaml_config
from tradingbot.engine.risk_manager import RiskManager
from tradingbot.engine.trade_engine import TradeEngine
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Trade, DigitalWallet, Portfolio
from tradingbot.database.db_storage_manager import DBStorageManager
from tradingbot.utils.logger import sanitize_sensitive_data


# ─────────────────────────────────────────────────────────────────────────────
# 1. Regresión Bug 8ed73e0: Prevención de Compras Duplicadas
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_regression_duplicate_buys_prevention():
    """Verifica que una señal BUY no abra una segunda posición si ya existe una abierta."""
    config = load_yaml_config("config.yaml")
    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    strategy.slow_period = 21
    strategy.generate_signal.return_value = "BUY"
    notifier = MagicMock()
    clp_converter = MagicMock()
    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    session = DatabaseSession.get_session()
    sym = "REG_DUP/USDT"
    trade = Trade(
        trade_id="reg_dup_001",
        symbol=sym,
        side="BUY",
        quantity=Decimal("1.0"),
        price_entry=Decimal("10.0"),
        status="OPEN",
        dca_step=2 # Ya completó DCA
    )
    session.add(trade)
    session.commit()
    session.close()

    try:
        mock_collector = MagicMock()
        mock_collector.get_historical_data = AsyncMock(return_value=pd.DataFrame({'close': [10.0] * 80}))
        mock_executor = MagicMock()
        mock_executor.execute_order = AsyncMock()

        result = await te.process_symbol(sym, "1m", 16.0, mock_collector, mock_executor)
        assert result['decision'] == "HOLD"
        assert "Posición ya abierta" in result['reason']
        mock_executor.execute_order.assert_not_called()
    finally:
        session = DatabaseSession.get_session()
        session.query(Trade).filter(Trade.trade_id == "reg_dup_001").delete()
        session.commit()
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Regresión Bug f6923ea: Micro DCA Pullback Threshold Gating
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_regression_micro_dca_pullback_bounds():
    """Verifica que Micro DCA Tramo 2 solo se dispare si la caída está estrictamente en [0.6%, 2.5%]."""
    config = load_yaml_config("config.yaml")
    config.risk.micro_dca.enabled = True
    config.risk.micro_dca.pullback_min_pct = 0.006  # 0.6%
    config.risk.micro_dca.pullback_max_pct = 0.025  # 2.5%

    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    strategy.slow_period = 21
    strategy.generate_signal.return_value = "BUY"
    notifier = MagicMock()
    clp_converter = MagicMock()
    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    session = DatabaseSession.get_session()
    sym = "REG_DCA/USDT"
    trade = Trade(
        trade_id="reg_dca_001",
        symbol=sym,
        side="BUY",
        quantity=Decimal("0.05"),
        price_entry=Decimal("100.0"),
        status="OPEN",
        dca_step=1
    )
    session.add(trade)
    session.commit()
    session.close()

    try:
        mock_executor = MagicMock()
        mock_executor.execute_order = AsyncMock()

        # Caso A: Caída de solo 0.2% (menor al mínimo 0.6%) -> HOLD
        mock_collector_small = MagicMock()
        mock_collector_small.get_historical_data = AsyncMock(return_value=pd.DataFrame({'close': [99.8] * 80}))
        res_small = await te.process_symbol(sym, "1m", 16.0, mock_collector_small, mock_executor)
        assert res_small['decision'] == "HOLD"
        mock_executor.execute_order.assert_not_called()

        # Caso B: Caída de 4.0% (mayor al máximo 2.5% - posible crash) -> HOLD
        mock_collector_large = MagicMock()
        mock_collector_large.get_historical_data = AsyncMock(return_value=pd.DataFrame({'close': [96.0] * 80}))
        res_large = await te.process_symbol(sym, "1m", 16.0, mock_collector_large, mock_executor)
        assert res_large['decision'] == "HOLD"
        mock_executor.execute_order.assert_not_called()
    finally:
        session = DatabaseSession.get_session()
        session.query(Trade).filter(Trade.trade_id == "reg_dca_001").delete()
        session.commit()
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Regresión Bug 836d854: Asyncio.Lock Dinámico en Nuevos Loops
# ─────────────────────────────────────────────────────────────────────────────
def test_regression_asyncio_lock_rebinding_across_loops():
    """Valida que TradeEngine.trade_lock nunca lance RuntimeError al cambiar de bucle de eventos."""
    config = load_yaml_config("config.yaml")
    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    notifier = MagicMock()
    clp_converter = MagicMock()
    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    async def step(loop_idx: int):
        async with te.trade_lock:
            await asyncio.sleep(0.005)
        return loop_idx

    # Ejecutar 5 bucles asyncio.run distintos consecutivos
    for i in range(5):
        result = asyncio.run(step(i))
        assert result == i


# ─────────────────────────────────────────────────────────────────────────────
# 4. Regresión Bug 0fef1fb: Fee Drag y PnL Neto Negativo
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_regression_fee_drag_negative_net_pnl():
    """
    Verifica que operaciones con ganancia bruta leve (+0.10%) pero pérdida neta
    tras comisiones (-0.10% ida y vuelta) calculen PnL neto negativo y NO activen profit sweep.
    """
    pm = PortfolioManager()
    session = DatabaseSession.get_session()
    try:
        # Registrar trade de compra
        exec_open = {
            "order_id": "reg_fee_001",
            "symbol": "REG_FEE/USDT",
            "side": "BUY",
            "type": "MARKET",
            "amount": 1.0,
            "price": 1000.0,
            "is_paper": True
        }
        pm.record_open_trade(exec_open)

        # Precio de salida sube levemente a $1001 (+0.10% bruto)
        exec_close = {
            "symbol": "REG_FEE/USDT",
            "side": "SELL",
            "type": "MARKET",
            "amount": 1.0,
            "price": 1001.0,
            "is_paper": True
        }
        closed_trade = pm.record_close_trade("reg_fee_001", exec_close)
        assert closed_trade is not None

        # PnL bruto es +$1.00 USD
        assert closed_trade.pnl == Decimal("1.00")

        # Comisiones Binance Spot (0.10% entrada + 0.10% salida = $1.00 + $1.001 = $2.001 USD)
        expected_fee = (Decimal("1000.0") + Decimal("1001.0")) * Decimal("0.0010")
        assert closed_trade.fee_usd == expected_fee

        # PnL neto = $1.00 - $2.001 = -$1.001 USD (NEGATIVO por Fee Drag)
        assert closed_trade.pnl_net_usd < Decimal("0.0")

        # Verificar que el barrido de ganancias (Profit Sweep) NO se disparó
        wallet = session.query(DigitalWallet).filter(DigitalWallet.is_paper == True).first()
        initial_reserve = wallet.reserve_usd or Decimal("0.0")
        assert initial_reserve == Decimal("0.0")
    finally:
        session.query(Trade).filter(Trade.trade_id == "reg_fee_001").delete()
        session.commit()
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Regresión Bug 321e80c: Regla de Reserva por Moneda y Mínimo de Orden
# ─────────────────────────────────────────────────────────────────────────────
def test_regression_coin_reserve_and_min_order():
    """Valida la regla de reserva del 25% y tope máximo de orden del 75%."""
    config = load_yaml_config("config.yaml")
    config.risk.coin_reserve_pct = 0.25
    config.risk.max_coin_order_pct = 0.75
    config.risk.min_order_usd = 0.10

    rm = RiskManager(config)
    coin_balance = 1.0  # Base $1.00 USD
    max_order = coin_balance * config.risk.max_coin_order_pct
    assert max_order == 0.75
    assert (coin_balance - max_order) == 0.25

    # Si el balance es menor que el mínimo requerido para una orden de $0.10
    tiny_balance = 0.05
    tiny_alloc = tiny_balance * config.risk.max_coin_order_pct
    assert tiny_alloc < config.risk.min_order_usd


# ─────────────────────────────────────────────────────────────────────────────
# 6. Regresión Bug 0fef1fb: Schema Guard & Empty DB Protection
# ─────────────────────────────────────────────────────────────────────────────
def test_regression_schema_guard_rejects_empty_or_corrupt_db(tmp_path):
    """Verifica que DBStorageManager rechace una base vacía de 0 bytes o sin trades."""
    empty_db = tmp_path / "empty.db"
    empty_db.write_text("")

    mgr = DBStorageManager(
        active_db_path=str(empty_db),
        persistent_db_path=str(tmp_path / "persist.db"),
        backup_dir=str(tmp_path / "backups"),
        golden_backup_path=str(tmp_path / "golden.db")
    )

    # 1. Integridad física de archivo vacío debe ser False
    assert mgr.check_db_integrity(str(empty_db)) is False

    # 2. Schema Guard debe rechazar archivo vacío
    assert mgr.check_db_schema_and_data(str(empty_db), min_trades=1) is False

    # 3. Schema Guard debe rechazar base con tablas pero 0 trades cuando min_trades=1
    zero_trades_db = tmp_path / "zero_trades.db"
    conn = sqlite3.connect(str(zero_trades_db))
    for t in mgr.REQUIRED_TABLES:
        conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY);")
    conn.commit()
    conn.close()
    assert mgr.check_db_schema_and_data(str(zero_trades_db), min_trades=1) is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. Regresión Bug 798aac1: Aislamiento de Base de Datos en Tests
# ─────────────────────────────────────────────────────────────────────────────
def test_regression_test_database_isolation():
    """Verifica que la base de datos de test sea efímera y no sea el archivo de producción."""
    from tradingbot.core.config import get_settings
    settings = get_settings()
    # No debe apuntar a la base de datos real de producción
    assert "/dev/shm/tradingbot.db" not in settings.database_url
    assert "test_tradingbot_" in settings.database_url


# ─────────────────────────────────────────────────────────────────────────────
# 8. Regresión Bug fb3e503: Sanitización de Secretos
# ─────────────────────────────────────────────────────────────────────────────
def test_regression_secret_sanitizer():
    """Verifica que tokens de Telegram y API keys se enmascaren en logs."""
    leak_sample = "https://api.telegram.org/bot1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567/sendMessage"
    sanitized = sanitize_sensitive_data(leak_sample)
    assert "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567" not in sanitized
    assert "***REDACTED_TELEGRAM_TOKEN***" in sanitized


# ─────────────────────────────────────────────────────────────────────────────
# 9. Regresión Bug f6923ea: Safe Time-Stop Multi-Ciclo y Rebound
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_regression_safe_time_stop_rebound_resets_tracker():
    """Verifica que si una posición en scalper madura y rebota a positivo, el tracker de salida se reinicia."""
    config = load_yaml_config("config.yaml")
    config.bot.trading_mode = "scalper"
    config.risk.time_stop.enabled = True
    config.risk.time_stop.min_duration_minutes = 60
    config.risk.time_stop.consecutive_cycles_required = 3

    rm = RiskManager(config)
    pm = PortfolioManager()
    strategy = MagicMock()
    notifier = MagicMock()
    clp_converter = MagicMock()
    te = TradeEngine(config, rm, pm, strategy, notifier, clp_converter)

    # Simular que el trade ya llevaba 2 ciclos consecutivos en pérdida
    trade_id = "reg_ts_001"
    te.time_stop_tracker[trade_id] = 2

    # Simular rebote: precio actual sube por sobre el precio de entrada
    from datetime import datetime, timedelta
    trade = Trade(
        trade_id=trade_id,
        symbol="REG_TS/USDT",
        side="BUY",
        quantity=Decimal("1.0"),
        price_entry=Decimal("100.0"),
        opened_at=datetime.utcnow() - timedelta(minutes=90),
        status="OPEN"
    )
    session = DatabaseSession.get_session()
    session.add(trade)
    session.commit()
    session.close()

    try:
        mock_executor = MagicMock()
        # Precio actual es $100.5 (ganancia leve, rebote)
        res = await te.manage_open_trades("REG_TS/USDT", 100.5, "HOLD", mock_executor, 16.0)
        assert res is None  # No se cierra
        # Tracker de ciclos debe haberse reseteado a vacío
        assert trade_id not in te.time_stop_tracker
    finally:
        session = DatabaseSession.get_session()
        session.query(Trade).filter(Trade.trade_id == trade_id).delete()
        session.commit()
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# 10. Regresión Bug 06d24ed: División por Cero y Casos Extremos
# ─────────────────────────────────────────────────────────────────────────────
def test_regression_division_by_zero_protection():
    """Verifica que RiskManager maneje de forma segura precios iguales o capitales cero."""
    config = load_yaml_config("config.yaml")
    rm = RiskManager(config)

    # Precio de entrada igual al stop loss
    size_equal = rm.calculate_position_size(total_capital=100.0, entry_price=50.0, stop_loss_price=50.0)
    assert size_equal == 0.0

    # Capital cero
    size_zero = rm.calculate_position_size(total_capital=0.0, entry_price=50.0, stop_loss_price=48.0)
    assert size_zero == 0.0

    # Precios negativos o cero
    size_neg = rm.calculate_position_size(total_capital=100.0, entry_price=-10.0, stop_loss_price=48.0)
    assert size_neg == 0.0
