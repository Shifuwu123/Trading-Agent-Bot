"""
tradingbot/database/migrations/003_archive_synthetic_test_trade_113.py

Migración 003: Saneamiento forense del trade #113 (artefacto sintético de pytest).
Cambia el estado de 'CLOSED' a 'ARCHIVED_TEST' para restituir el PnL legítimo de SOL/USDT.
"""

import sqlite3

VERSION = "003"
NAME = "archive_synthetic_test_trade_113"


def up(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
        UPDATE trades
        SET status = 'ARCHIVED_TEST',
            exit_reason = '[SANITIZED] Test Leak Artefact - Pytest 11/10/2026'
        WHERE id = 113 AND trade_id = 'mock_aed7f859';
    """)


def down(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
        UPDATE trades
        SET status = 'CLOSED',
            exit_reason = 'Hard Stop Loss Emergencia (-4.5%)'
        WHERE id = 113 AND trade_id = 'mock_aed7f859';
    """)
