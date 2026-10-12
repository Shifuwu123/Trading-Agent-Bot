"""
tradingbot/database/migrations/001_initial_schema.py

Migración 001: Esquema base de la plataforma de trading.
Crea tablas: trades, digital_wallet, portfolio, candles, decision_logs, cash_flow, bot_commands.
"""

import sqlite3

VERSION = "001"
NAME = "initial_schema"


def up(conn: sqlite3.Connection):
    """Crea las tablas base del sistema si no existen."""
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id VARCHAR UNIQUE,
            symbol VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            order_type VARCHAR DEFAULT 'MARKET',
            quantity NUMERIC(18, 8) NOT NULL,
            price_entry NUMERIC(18, 8) NOT NULL,
            price_exit NUMERIC(18, 8),
            stop_loss NUMERIC(18, 8),
            take_profit NUMERIC(18, 8),
            pnl NUMERIC(18, 8),
            pnl_pct NUMERIC(18, 8),
            status VARCHAR DEFAULT 'OPEN',
            mode VARCHAR,
            strategy VARCHAR,
            opened_at DATETIME,
            closed_at DATETIME,
            exchange VARCHAR,
            is_paper BOOLEAN DEFAULT 1,
            agent_id VARCHAR(50) DEFAULT 'legacy'
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_trades_trade_id ON trades(trade_id);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS digital_wallet (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id VARCHAR,
            balance_usd NUMERIC(18, 8) DEFAULT 50.0,
            is_paper BOOLEAN DEFAULT 1,
            CONSTRAINT _telegram_paper_uc UNIQUE (telegram_id, is_paper)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_id INTEGER REFERENCES digital_wallet(id),
            asset VARCHAR,
            quantity NUMERIC(18, 8) DEFAULT 0.0,
            avg_price NUMERIC(18, 8) DEFAULT 0.0,
            current_price NUMERIC(18, 8) DEFAULT 0.0,
            unrealized_pnl NUMERIC(18, 8) DEFAULT 0.0,
            updated_at DATETIME,
            is_paper BOOLEAN DEFAULT 1,
            agent_id VARCHAR(50) DEFAULT 'legacy',
            CONSTRAINT _asset_paper_uc UNIQUE (asset, is_paper)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_portfolio_asset ON portfolio(asset);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol VARCHAR NOT NULL,
            timeframe VARCHAR NOT NULL,
            timestamp DATETIME NOT NULL,
            open NUMERIC(18, 8) NOT NULL,
            high NUMERIC(18, 8) NOT NULL,
            low NUMERIC(18, 8) NOT NULL,
            close NUMERIC(18, 8) NOT NULL,
            volume NUMERIC(18, 8) NOT NULL,
            CONSTRAINT _symbol_tf_ts_uc UNIQUE (symbol, timeframe, timestamp)
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_candles_symbol ON candles(symbol);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_candles_timestamp ON candles(timestamp);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS decision_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            symbol VARCHAR NOT NULL,
            decision VARCHAR NOT NULL,
            reason TEXT
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_decision_logs_symbol ON decision_logs(symbol);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_decision_logs_timestamp ON decision_logs(timestamp);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cash_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id VARCHAR,
            timestamp DATETIME,
            type VARCHAR NOT NULL,
            amount_usd NUMERIC(18, 8) NOT NULL,
            description TEXT,
            is_paper BOOLEAN DEFAULT 1
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_cash_flow_telegram_id ON cash_flow(telegram_id);")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command VARCHAR NOT NULL,
            args VARCHAR,
            status VARCHAR DEFAULT 'PENDING',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)


def down(conn: sqlite3.Connection):
    """Elimina las tablas base (rollback total)."""
    cur = conn.cursor()
    tables = ["bot_commands", "cash_flow", "decision_logs", "candles", "portfolio", "digital_wallet", "trades"]
    for t in tables:
        cur.execute(f"DROP TABLE IF EXISTS {t};")
