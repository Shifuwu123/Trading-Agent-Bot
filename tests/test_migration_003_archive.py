"""
tests/test_migration_003_archive.py

Pruebas para verificar el saneamiento del Trade #113 mediante la Migración 003.
Confirma que el PnL de SOL/USDT excluye la pérdida artificial (-$0.364 USD).
"""

import sqlite3
import tempfile
import os
import pytest

from tradingbot.database.migrations.manager import MigrationManager


@pytest.fixture
def clean_db():
    fd, path = tempfile.mkstemp(prefix="test_mig003_", suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_migration_003_archives_trade_113(clean_db):
    # 1. Aplicar migraciones 001 y 002
    manager = MigrationManager(db_path=clean_db)
    manager.apply_all()

    # 2. Insertar el trade #113 sintético que causó la distorsión
    conn = sqlite3.connect(clean_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO trades (id, trade_id, symbol, side, quantity, price_entry, price_exit, pnl, status, exit_reason)
        VALUES (113, 'mock_aed7f859', 'SOL/USDT', 'BUY', 0.00355, 112.49, 10.00, -0.364441, 'CLOSED', 'Hard Stop Loss Emergencia (-4.5%)');
    """)
    # Insertar también un trade legítimo de SOL
    cur.execute("""
        INSERT INTO trades (id, trade_id, symbol, side, quantity, price_entry, price_exit, pnl, status, exit_reason)
        VALUES (200, 'real_trade_01', 'SOL/USDT', 'BUY', 0.00355, 112.00, 113.68, 0.005964, 'CLOSED', 'Take Profit (+1.5%)');
    """)
    conn.commit()

    # Antes de migración 003: PnL de SOL suma el trade #113
    cur.execute("SELECT SUM(pnl) FROM trades WHERE symbol = 'SOL/USDT' AND status = 'CLOSED'")
    pnl_before = cur.fetchone()[0]
    assert pnl_before < -0.30

    # 3. Aplicar migración 003
    import importlib
    mig_003 = importlib.import_module("tradingbot.database.migrations.003_archive_synthetic_test_trade_113")
    mig_003.up(conn)
    conn.commit()

    # 4. Verificar que el trade #113 quedó archivado
    cur.execute("SELECT status, exit_reason FROM trades WHERE id = 113")
    row = cur.fetchone()
    assert row[0] == "ARCHIVED_TEST"
    assert "[SANITIZED]" in row[1]

    # 5. PnL legítimo de SOL ahora excluye el trade #113
    cur.execute("SELECT SUM(pnl) FROM trades WHERE symbol = 'SOL/USDT' AND status = 'CLOSED'")
    pnl_after = cur.fetchone()[0]
    assert pnl_after == pytest.approx(0.005964, rel=1e-4)

    # 6. Probar rollback
    mig_003.down(conn)
    conn.commit()
    cur.execute("SELECT status FROM trades WHERE id = 113")
    assert cur.fetchone()[0] == "CLOSED"

    conn.close()
