"""
tradingbot/database/migrations/002_fiscal_and_dca_columns.py

Migración 002: Incorpora campos fiscales (SII Chile), deducción de comisiones (fee drag),
escalonamiento Micro DCA y subcuenta de reserva.
- Columnas añadidas a trades: dca_step, exit_reason, fee_usd, pnl_net_usd, clp_exchange_rate, pnl_clp.
- Columnas añadidas a digital_wallet: reserve_usd.
"""

import sqlite3

VERSION = "002"
NAME = "fiscal_and_dca_columns"


def up(conn: sqlite3.Connection):
    cur = conn.cursor()

    # 1. Tabla trades
    cur.execute("PRAGMA table_info(trades);")
    existing_trade_cols = set(row[1] for row in cur.fetchall())

    trade_columns_to_add = [
        ("dca_step", "INTEGER DEFAULT 1"),
        ("exit_reason", "TEXT"),
        ("fee_usd", "NUMERIC(18, 8) DEFAULT 0.0"),
        ("pnl_net_usd", "NUMERIC(18, 8) DEFAULT 0.0"),
        ("clp_exchange_rate", "NUMERIC(18, 8)"),
        ("pnl_clp", "NUMERIC(18, 8)"),
    ]

    for col_name, col_type in trade_columns_to_add:
        if col_name not in existing_trade_cols:
            cur.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type};")

    # 2. Tabla digital_wallet
    cur.execute("PRAGMA table_info(digital_wallet);")
    existing_wallet_cols = set(row[1] for row in cur.fetchall())

    if "reserve_usd" not in existing_wallet_cols:
        cur.execute("ALTER TABLE digital_wallet ADD COLUMN reserve_usd NUMERIC(18, 8) DEFAULT 0.0;")


def down(conn: sqlite3.Connection):
    """
    Rollback: Elimina las columnas añadidas usando soporte SQLite DROP COLUMN (SQLite 3.35+).
    """
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(trades);")
    existing_trade_cols = set(row[1] for row in cur.fetchall())

    cols_to_drop = ["pnl_clp", "clp_exchange_rate", "pnl_net_usd", "fee_usd", "exit_reason", "dca_step"]
    for col in cols_to_drop:
        if col in existing_trade_cols:
            cur.execute(f"ALTER TABLE trades DROP COLUMN {col};")

    cur.execute("PRAGMA table_info(digital_wallet);")
    existing_wallet_cols = set(row[1] for row in cur.fetchall())
    if "reserve_usd" in existing_wallet_cols:
        cur.execute("ALTER TABLE digital_wallet DROP COLUMN reserve_usd;")
