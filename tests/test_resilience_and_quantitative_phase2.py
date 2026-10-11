"""
tests/test_resilience_and_quantitative_phase2.py

Suite de pruebas unitarias y de integración para la Fase 2:
- Watchdog de Salud y Auto-Sanación de Persistencia
- Blindaje del Notificador de Telegram (XML Escaping, Límite 3800, Fallback 400)
- Modelado Económico de Comisiones (Fee Drag), Tasa SII CLP y Reserva 20% (Profit Sweep)
- Filtros Cuantitativos de Régimen de Mercado (Choppiness Index y ADX)
- Take Profit Institucional >= +1.20%
"""

import os
import shutil
import sqlite3
import pytest
from decimal import Decimal
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

from tradingbot.interfaces.telegram.notifier import TelegramNotifier
from tradingbot.database.db_storage_manager import DBStorageManager
from tradingbot.database.storage_watchdog import StorageHealthWatchdog
from tradingbot.strategies.regime_filter import MarketRegimeFilter
from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.database.models import Trade, DigitalWallet, CashFlow


@pytest.fixture
def temp_db_env(tmp_path):
    """Crea un entorno de base de datos aislado para tests."""
    ram_path = str(tmp_path / "ram_tradingbot.db")
    disk_path = str(tmp_path / "disk_tradingbot.db")
    golden_path = str(tmp_path / "golden_tradingbot.db")
    backup_dir = str(tmp_path / "backups_db")

    # Crear una base de datos válida con esquema mínimo
    conn = sqlite3.connect(golden_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, trade_id TEXT UNIQUE, symbol TEXT, side TEXT,
            quantity NUMERIC, price_entry NUMERIC, price_exit NUMERIC,
            pnl NUMERIC, fee_usd NUMERIC, pnl_net_usd NUMERIC,
            clp_exchange_rate NUMERIC, pnl_clp NUMERIC,
            status TEXT, agent_id TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE digital_wallet (
            id INTEGER PRIMARY KEY, telegram_id TEXT,
            balance_usd NUMERIC, reserve_usd NUMERIC, is_paper INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE portfolio (
            id INTEGER PRIMARY KEY, asset TEXT, quantity NUMERIC, is_paper INTEGER
        );
    """)
    # Insertar registros válidos
    cur.execute("""
        INSERT INTO trades (id, trade_id, symbol, side, quantity, price_entry, status)
        VALUES (1, 'mock_1', 'SOL/USDT', 'BUY', 1.0, 150.0, 'OPEN');
    """)
    cur.execute("""
        INSERT INTO digital_wallet (id, telegram_id, balance_usd, reserve_usd, is_paper)
        VALUES (1, '12345', 50.0, 0.0, 1);
    """)
    conn.commit()
    conn.close()

    # Copiar a ram y disk
    shutil.copy2(golden_path, ram_path)
    shutil.copy2(golden_path, disk_path)

    mgr = DBStorageManager(
        active_db_path=ram_path,
        persistent_db_path=disk_path,
        backup_dir=backup_dir,
        golden_backup_path=golden_path,
        sync_interval_seconds=60,
    )

    yield {
        "mgr": mgr,
        "ram": ram_path,
        "disk": disk_path,
        "golden": golden_path,
        "backup_dir": backup_dir,
    }


# =============================================================================
# 1. Tests del Notificador de Telegram Blindado
# =============================================================================

def test_telegram_message_truncation():
    """Verifica que mensajes mayores a 3800 caracteres sean truncados de forma segura."""
    notifier = TelegramNotifier()
    notifier.bot_token = "123456:TEST_TOKEN"
    notifier.chat_id = "999"

    long_text = "A" * 5000
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        notifier.send_message(long_text)
        assert mock_post.called
        sent_payload = mock_post.call_args[1]["json"]
        assert len(sent_payload["text"]) <= 3850
        assert "[Mensaje truncado por límite de tamaño]" in sent_payload["text"]


def test_telegram_error_alert_html_escape():
    """Verifica que caracteres < y > en trazas de excepción no rompan el formato HTML."""
    notifier = TelegramNotifier()
    notifier.bot_token = "123456:TEST_TOKEN"
    notifier.chat_id = "999"

    traceback_str = "<sqlite3.OperationalError: no such table: trades>"
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        notifier.send_error_alert(traceback_str)
        assert mock_post.called
        sent_payload = mock_post.call_args[1]["json"]
        # Debe estar escapado
        assert "&lt;sqlite3.OperationalError" in sent_payload["text"]
        assert "<sqlite3" not in sent_payload["text"]


def test_telegram_fallback_on_http_400():
    """Verifica que ante un HTTP 400 Bad Request, reintente en modo texto plano sin parse_mode."""
    notifier = TelegramNotifier()
    notifier.bot_token = "123456:TEST_TOKEN"
    notifier.chat_id = "999"

    import requests

    first_resp = MagicMock()
    first_resp.status_code = 400
    first_resp.text = "Bad Request: can't parse entities"
    http_error = requests.HTTPError(response=first_resp)

    success_resp = MagicMock()
    success_resp.status_code = 200

    with patch("requests.post", side_effect=[http_error, success_resp]) as mock_post:
        result = notifier.send_message("Texto con error <b>no cerrado", parse_mode="HTML")
        assert result is True
        assert mock_post.call_count == 2
        # Segunda llamada debe tener parse_mode None
        fallback_payload = mock_post.call_args_list[1][1]["json"]
        assert "parse_mode" not in fallback_payload


# =============================================================================
# 2. Tests de Resiliencia, Schema Guard y StorageHealthWatchdog
# =============================================================================

def test_schema_guard_prevents_empty_db_sync(temp_db_env):
    """Verifica que el Schema Guard prohíba sobreescribir disco si RAM tiene 0 bytes o faltan tablas."""
    mgr = temp_db_env["mgr"]
    ram_path = temp_db_env["ram"]

    # Vaciar intencionalmente la base en RAM
    with open(ram_path, "w") as f:
        f.write("")

    res = mgr.sync_to_disk()
    assert res["success"] is False
    assert "SchemaGuard" in res["error"] or "esquema" in res["error"].lower()

    # Verificar que el archivo en disco sigue intacto
    assert os.path.getsize(temp_db_env["disk"]) > 0


def test_storage_watchdog_auto_healing(temp_db_env):
    """Verifica que el Watchdog detecte archivo corrupto y auto-sane desde el Golden Backup."""
    mgr = temp_db_env["mgr"]
    ram_path = temp_db_env["ram"]

    # Simular corrupción en caliente
    with open(ram_path, "w") as f:
        f.write("corrupted content")

    healthy, detail = StorageHealthWatchdog.check_health(ram_path)
    assert healthy is False

    # Ejecutar auto-sanación usando el manager de test
    with patch.object(DBStorageManager, "get_instance", return_value=mgr):
        healed = StorageHealthWatchdog.auto_heal()
        assert healed is True
        # Verificar salud recuperada
        healthy_post, _ = StorageHealthWatchdog.check_health(ram_path)
        assert healthy_post is True


# =============================================================================
# 3. Tests de Filtros Cuantitativos de Régimen (CHOP & ADX)
# =============================================================================

def test_regime_filter_chop_and_adx():
    """Verifica que el filtro de régimen bloquee mercados caóticos y apruebe tendencias."""
    # 1. Mercado en Rango Caótico (alta alternancia sin dirección)
    np.random.seed(42)
    n = 30
    flat_close = 100.0 + np.random.uniform(-1, 1, n)
    flat_high = flat_close + np.random.uniform(0.5, 1.5, n)
    flat_low = flat_close - np.random.uniform(0.5, 1.5, n)
    df_flat = pd.DataFrame({'high': flat_high, 'low': flat_low, 'close': flat_close})

    chop_val = MarketRegimeFilter.calculate_chop(df_flat, period=14)
    assert chop_val > 50.0  # El mercado caótico tiene CHOP elevado

    # 2. Mercado en Fuerte Tendencia Alcista
    trend_close = np.linspace(100.0, 150.0, n)
    trend_high = trend_close + 0.5
    trend_low = trend_close - 0.5
    df_trend = pd.DataFrame({'high': trend_high, 'low': trend_low, 'close': trend_close})

    chop_trend = MarketRegimeFilter.calculate_chop(df_trend, period=14)
    adx_trend = MarketRegimeFilter.calculate_adx(df_trend, period=14)

    # En tendencia fuerte, CHOP debe ser significativamente más bajo que en rango plano
    assert chop_trend < chop_val
    assert adx_trend > 20.0

    is_ok, reason, metrics = MarketRegimeFilter.evaluate_regime(df_trend, chop_max=65.0, adx_min=20.0)
    assert is_ok is True
    assert "Robusto" in reason or "Régimen" in reason


# =============================================================================
# 4. Tests Contables: Fee Drag, Dólar Observado SII y Profit Sweep 20%
# =============================================================================

def test_portfolio_manager_accounting_and_sweep():
    """Verifica que el registro de cierre calcule fee_usd, pnl_net_usd, pnl_clp y reserve_usd."""
    pm = PortfolioManager()

    # Simular conversión fija de CLP
    pm.clp_converter.get_usd_to_clp_rate = MagicMock(return_value=950.0)

    # Mock DB trade
    mock_trade = Trade(
        id=10,
        trade_id="mock_test_fee",
        symbol="SOL/USDT",
        side="BUY",
        quantity=Decimal("1.0"),
        price_entry=Decimal("100.0"),
        status="OPEN",
        is_paper=True,
    )

    from tradingbot.database.models import Portfolio
    mock_portfolio = Portfolio(
        id=1,
        asset="SOL",
        quantity=Decimal("1.0"),
        avg_price=Decimal("100.0"),
        current_price=Decimal("110.0"),
        is_paper=True,
    )

    mock_wallet = DigitalWallet(
        id=1,
        telegram_id="test_user",
        balance_usd=Decimal("50.0"),
        reserve_usd=Decimal("0.0"),
        is_paper=True,
    )

    execution_data = {
        "symbol": "SOL/USDT",
        "side": "SELL",
        "amount": 1.0,
        "price": 110.0,  # Ganancia bruta: +$10.0 USD
        "is_paper": True,
    }

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.side_effect = [
        mock_trade, mock_portfolio, mock_wallet, mock_wallet
    ]

    with patch.object(DatabaseSession, "get_session", return_value=mock_session):
        closed = pm.record_close_trade("mock_test_fee", execution_data)
        assert closed is not None
        # PnL Bruto: 110 - 100 = 10.0
        assert closed.pnl == Decimal("10.0")
        # Fee: (100 + 110) * 0.0010 = 0.21 USD
        assert closed.fee_usd == Decimal("0.21")
        # PnL Neto: 10.0 - 0.21 = 9.79 USD
        assert closed.pnl_net_usd == Decimal("9.79")
        # PnL CLP: 9.79 * 950 = 9300.5 CLP
        assert closed.pnl_clp == Decimal("9300.5")
        # Profit Sweep 20%: 9.79 * 0.20 = 1.958 USD a reserva
        assert mock_wallet.reserve_usd == Decimal("1.958")
