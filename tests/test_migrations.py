"""
tests/test_migrations.py

Pruebas automatizadas rigurosas para el subsistema de migraciones y rollbacks.
Verifica:
1. Aplicación limpia e idempotente de migraciones (up).
2. Reversión segura de migraciones (down / rollback).
3. Respaldo snapshot automático pre-migración.
4. Auto-restauración y protección contra fallos o corrupción a mitad de camino.
"""

import os
import sqlite3
import tempfile
import pytest

from tradingbot.database.migrations.manager import MigrationManager, MigrationError


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(prefix="test_mig_", suffix=".db")
    os.close(fd)
    backup_dir = tempfile.mkdtemp(prefix="test_mig_backups_")
    yield path, backup_dir
    if os.path.exists(path):
        os.remove(path)
    import shutil
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)


def test_migrations_apply_and_verify_schema(temp_db):
    db_path, backup_dir = temp_db
    manager = MigrationManager(db_path=db_path, backup_dir=backup_dir)

    # 1. Aplicar todas las migraciones
    applied = manager.apply_all()
    assert "001" in applied
    assert "002" in applied

    # 2. Verificar que las tablas y columnas existen
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = set(r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall())
    assert "trades" in tables
    assert "digital_wallet" in tables
    assert "schema_migrations" in tables

    # Columnas de 002
    cur.execute("PRAGMA table_info(trades);")
    trade_cols = set(r[1] for r in cur.fetchall())
    assert "dca_step" in trade_cols
    assert "fee_usd" in trade_cols
    assert "pnl_net_usd" in trade_cols
    assert "pnl_clp" in trade_cols

    cur.execute("PRAGMA table_info(digital_wallet);")
    wallet_cols = set(r[1] for r in cur.fetchall())
    assert "reserve_usd" in wallet_cols
    conn.close()

    # 3. Idempotencia: segunda ejecución no aplica nada adicional
    second_applied = manager.apply_all()
    assert second_applied == []


def test_migrations_rollback_and_restore(temp_db):
    db_path, backup_dir = temp_db
    manager = MigrationManager(db_path=db_path, backup_dir=backup_dir)

    manager.apply_all()
    applied_before = manager.get_applied_versions()
    assert applied_before == ["001", "002"]

    # Insertar un registro de prueba
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("INSERT INTO trades (trade_id, symbol, side, quantity, price_entry, fee_usd) VALUES ('t1', 'BTC/USDT', 'BUY', 0.1, 50000, 0.05);")
    conn.commit()
    conn.close()

    # Revertir última migración (002)
    rolled_back = manager.rollback_last()
    assert rolled_back == "002"
    assert manager.get_applied_versions() == ["001"]

    # Verificar que las columnas de 002 ya no están en trades
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(trades);")
    trade_cols = set(r[1] for r in cur.fetchall())
    assert "fee_usd" not in trade_cols
    # Pero el trade base aún existe (integridad de datos preservada)
    cur.execute("SELECT trade_id, symbol FROM trades WHERE trade_id='t1';")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "t1"
    conn.close()

    # Reaplicar 002
    reapplied = manager.apply_all()
    assert reapplied == ["002"]
    assert manager.get_applied_versions() == ["001", "002"]


def test_migrations_safety_snapshot_on_failure(temp_db):
    """Verifica que si una migración falla, se restaura el snapshot previo automáticamente."""
    db_path, backup_dir = temp_db
    manager = MigrationManager(db_path=db_path, backup_dir=backup_dir)

    manager.apply_all()

    # Crear una migración defectuosa temporal en un directorio ad-hoc
    test_mig_dir = tempfile.mkdtemp()
    with open(os.path.join(test_mig_dir, "003_bad_migration.py"), "w") as f:
        f.write("""
VERSION = "003"
NAME = "bad_migration"
def up(conn):
    conn.execute("ALTER TABLE trades ADD COLUMN good_col TEXT;")
    raise RuntimeError("Simulated migration failure mid-transaction!")
def down(conn):
    pass
""")

    failing_manager = MigrationManager(db_path=db_path, migrations_dir=test_mig_dir, backup_dir=backup_dir)

    with pytest.raises(Exception):
        failing_manager.apply_all()

    # Comprobar que good_col NO quedó en trades porque se revirtió al snapshot
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(trades);")
    cols = set(r[1] for r in cur.fetchall())
    assert "good_col" not in cols
    conn.close()

    import shutil
    shutil.rmtree(test_mig_dir, ignore_errors=True)
