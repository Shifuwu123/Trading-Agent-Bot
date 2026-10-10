"""
tests/test_db_storage_and_cloud.py

Pruebas unitarias y de integración para la arquitectura híbrida de base de datos
(DBStorageManager y CloudSyncProvider).
"""

import os
import tempfile
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone

from tradingbot.database.db_storage_manager import DBStorageManager
from tradingbot.database.cloud_sync import CloudSyncProvider


@pytest.fixture
def temp_dbs():
    """Crea rutas temporales para simular RAM y disco persistente."""
    temp_dir = tempfile.mkdtemp()
    ram_path = os.path.join(temp_dir, "ram_tradingbot.db")
    disk_path = os.path.join(temp_dir, "disk_tradingbot.db")
    backup_dir = os.path.join(temp_dir, "backups")

    # Inicializar una base de datos con tablas mínimas en disco
    conn = sqlite3.connect(disk_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE digital_wallet (id INTEGER PRIMARY KEY, balance_usd REAL, is_paper INTEGER);")
    cur.execute("INSERT INTO digital_wallet VALUES (1, 16.0, 1);")
    cur.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, trade_id TEXT, symbol TEXT, side TEXT, quantity REAL, price_entry REAL, price_exit REAL, pnl REAL, pnl_pct REAL, status TEXT, opened_at TEXT, closed_at TEXT, agent_id TEXT);")
    cur.execute("INSERT INTO trades VALUES (1, 't-1', 'SOL/USDT', 'BUY', 0.1, 150.0, 155.0, 0.5, 3.3, 'CLOSED', '2026-10-09 10:00:00', '2026-10-09 10:15:00', 'scalper_t1');")
    cur.execute("CREATE TABLE portfolio (id INTEGER PRIMARY KEY, asset TEXT, quantity REAL, avg_price REAL, current_price REAL, unrealized_pnl REAL, is_paper INTEGER);")
    cur.execute("CREATE TABLE candles (id INTEGER PRIMARY KEY, symbol TEXT, timeframe TEXT, timestamp TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);")
    cur.execute("CREATE TABLE decision_logs (id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, decision TEXT, reason TEXT);")

    # Insertar logs antiguos y recientes
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    recent_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO decision_logs (timestamp, symbol, decision, reason) VALUES (?, 'SOL/USDT', 'HOLD', 'No signal');", (old_ts,))
    cur.execute("INSERT INTO decision_logs (timestamp, symbol, decision, reason) VALUES (?, 'SOL/USDT', 'HOLD', 'No signal');", (recent_ts,))
    cur.execute("INSERT INTO decision_logs (timestamp, symbol, decision, reason) VALUES (?, 'SOL/USDT', 'BUY', 'RSI oversold');", (old_ts,))

    # Insertar velas antiguas y recientes
    cur.execute("INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) VALUES ('SOL/USDT', '1m', ?, 150, 151, 149, 150.5, 100);", (old_ts,))
    cur.execute("INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) VALUES ('SOL/USDT', '1m', ?, 150, 151, 149, 150.5, 100);", (recent_ts,))

    conn.commit()
    conn.close()

    yield ram_path, disk_path, backup_dir

    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_ensure_ram_db_initialization(temp_dbs):
    ram_path, disk_path, backup_dir = temp_dbs

    mgr = DBStorageManager(
        active_db_path=ram_path,
        persistent_db_path=disk_path,
        backup_dir=backup_dir
    )

    # Inicialmente RAM no existe
    assert not os.path.exists(ram_path)

    # Debe copiar de disk_path a ram_path
    active = mgr.ensure_ram_db_initialized()
    assert active == ram_path
    assert os.path.exists(ram_path)
    assert mgr.check_db_integrity(ram_path)

    # Verificar que los datos existen en RAM
    conn = sqlite3.connect(ram_path)
    cur = conn.cursor()
    cur.execute("SELECT balance_usd FROM digital_wallet")
    row = cur.fetchone()
    conn.close()
    assert row[0] == 16.0


def test_sync_to_disk_atomic(temp_dbs):
    ram_path, disk_path, backup_dir = temp_dbs
    mgr = DBStorageManager(
        active_db_path=ram_path,
        persistent_db_path=disk_path,
        backup_dir=backup_dir
    )
    mgr.ensure_ram_db_initialized()

    # Escribir un nuevo trade en RAM
    conn = sqlite3.connect(ram_path)
    conn.execute("INSERT INTO trades VALUES (2, 't-2', 'DOGE/USDT', 'BUY', 10.0, 0.1, 0.12, 0.2, 20.0, 'CLOSED', '2026-10-10 01:00:00', '2026-10-10 01:05:00', 'scalper_t1');")
    conn.commit()
    conn.close()

    # Sincronizar a disco
    res = mgr.sync_to_disk(create_timestamped_backup=True)
    assert res["success"] is True
    assert res["duration_ms"] > 0

    # Verificar que el nuevo trade ahora está en disk_path
    disk_conn = sqlite3.connect(disk_path)
    cur = disk_conn.cursor()
    cur.execute("SELECT count(*) FROM trades")
    count = cur.fetchone()[0]
    disk_conn.close()
    assert count == 2

    # Verificar que se creó un snapshot en backup_dir
    backups = os.listdir(backup_dir)
    assert len(backups) == 1
    assert backups[0].startswith("tradingbot.db.bak_")


def test_housekeeping_prunes_only_old_holds_and_candles(temp_dbs):
    ram_path, disk_path, backup_dir = temp_dbs
    mgr = DBStorageManager(
        active_db_path=ram_path,
        persistent_db_path=disk_path,
        backup_dir=backup_dir
    )
    mgr.ensure_ram_db_initialized()

    # Ejecutar housekeeping con retención de 3 días para HOLD y 3 días para velas
    res = mgr.run_housekeeping(retention_days_hold=3, retention_days_candles=3, retention_days_logs=14)
    assert res["success"] is True
    assert res["deleted_hold"] == 1  # 1 de los 2 HOLDs tenía 5 días de antigüedad
    assert res["deleted_candles"] == 1  # 1 de las 2 velas tenía 5 días

    conn = sqlite3.connect(ram_path)
    cur = conn.cursor()

    # Los trades y la billetera deben permanecer intocados
    cur.execute("SELECT count(*) FROM digital_wallet")
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT count(*) FROM trades")
    assert cur.fetchone()[0] == 1

    # El registro 'BUY' antiguo de decision_logs debe preservarse intacto
    cur.execute("SELECT count(*) FROM decision_logs WHERE decision = 'BUY'")
    assert cur.fetchone()[0] == 1

    # Solo debe quedar 1 HOLD reciente
    cur.execute("SELECT count(*) FROM decision_logs WHERE decision = 'HOLD'")
    assert cur.fetchone()[0] == 1

    conn.close()


def test_cloud_sync_payload_extraction(temp_dbs):
    ram_path, disk_path, backup_dir = temp_dbs
    mgr = DBStorageManager(
        active_db_path=ram_path,
        persistent_db_path=disk_path,
        backup_dir=backup_dir
    )
    mgr.ensure_ram_db_initialized()

    provider = CloudSyncProvider(
        local_db_path=ram_path,
        enabled=False,
        provider="turso"
    )

    payload = provider.extract_sync_payload()
    assert payload is not None
    assert "wallet" in payload
    assert payload["wallet"]["balance_usd"] == 16.0
    assert "metrics" in payload
    assert payload["metrics"]["total_closed_trades"] == 1
    assert payload["metrics"]["realized_pnl_usd"] == 0.5
    assert len(payload["trades"]) == 1
    assert payload["trades"][0]["symbol"] == "SOL/USDT"
