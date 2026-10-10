#!/usr/bin/env python3
"""
scripts/reset_to_50usd.py

Reinicio completo de estado contable, órdenes y billetera a $50.00 USD.
PRESERVA ÍNTEGRAMENTE:
- `candles`: dataset histórico OHLCV para Deep Learning.
- `decision_logs`: micro-decisiones históricas para Machine Learning.
"""

import os
import shutil
import sqlite3
from datetime import datetime

DB_PATH = "tradingbot.db"
BACKUP_PATH = f"tradingbot.db.bak_pre_reset_50usd_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def run_reset():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"No se encontró la base de datos en {DB_PATH}")

    # Checkpoint WAL first
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.close()

    # Create full backup
    print(f"📦 Creando respaldo de base de datos en {BACKUP_PATH}...")
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print("✅ Respaldo creado exitosamente.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Pre-reset counts
    candles_count_before = c.execute("SELECT count(*) FROM candles").fetchone()[0]
    decisions_count_before = c.execute("SELECT count(*) FROM decision_logs").fetchone()[0]
    trades_count_before = c.execute("SELECT count(*) FROM trades").fetchone()[0]
    open_trades_before = c.execute("SELECT count(*) FROM trades WHERE status = 'OPEN'").fetchone()[0]

    print("\n--- Estado Previo ---")
    print(f"Candles (Deep Learning): {candles_count_before} registros")
    print(f"Decision Logs (ML):     {decisions_count_before} registros")
    print(f"Total Trades:           {trades_count_before} (Abiertos: {open_trades_before})")

    # 1. Reset Digital Wallet to 50.00 USD
    c.execute("UPDATE digital_wallet SET balance_usd = 50.0 WHERE is_paper = 1")
    if c.rowcount == 0:
        c.execute("INSERT INTO digital_wallet (telegram_id, balance_usd, is_paper) VALUES ('1676283475', 50.0, 1)")
    print(f"✅ Digital Wallet actualizada a $50.00 USD (filas modificadas: {c.rowcount})")

    # 2. Archive all trades
    c.execute("UPDATE trades SET status = 'ARCHIVED' WHERE status != 'ARCHIVED'")
    print(f"✅ Trades abiertos archivados: {c.rowcount} órdenes")

    # 3. Clean active portfolio positions
    c.execute("UPDATE portfolio SET quantity = 0, avg_price = 0, unrealized_pnl = 0")
    print(f"✅ Holdings de portfolio reiniciados a 0: {c.rowcount} activos")

    # 4. Clear cash_flow
    c.execute("DELETE FROM cash_flow")
    print(f"✅ Cashflow reiniciado a 0 registros")

    conn.commit()

    # Post-reset verification
    candles_count_after = c.execute("SELECT count(*) FROM candles").fetchone()[0]
    decisions_count_after = c.execute("SELECT count(*) FROM decision_logs").fetchone()[0]
    wallet_balance = c.execute("SELECT balance_usd FROM digital_wallet WHERE is_paper = 1").fetchone()[0]
    open_trades_after = c.execute("SELECT count(*) FROM trades WHERE status = 'OPEN'").fetchone()[0]
    active_portfolio_count = c.execute("SELECT count(*) FROM portfolio WHERE quantity > 0").fetchone()[0]

    conn.close()

    print("\n--- Verificación Post-Reinicio ---")
    print(f"Candles (Deep Learning): {candles_count_after} (Conservados: {candles_count_after == candles_count_before})")
    print(f"Decision Logs (ML):     {decisions_count_after} (Conservados: {decisions_count_after == decisions_count_before})")
    print(f"Wallet Balance:         ${wallet_balance:.2f} USD")
    print(f"Open Trades:            {open_trades_after}")
    print(f"Active Portfolio Items: {active_portfolio_count}")

    assert candles_count_after == candles_count_before, "¡ERROR CRÍTICO: Se alteraron las velas de deep learning!"
    assert decisions_count_after == decisions_count_before, "¡ERROR CRÍTICO: Se alteraron los logs de decisiones!"
    assert wallet_balance == 50.0, f"¡ERROR: Balance esperado 50.0 pero se obtuvo {wallet_balance}!"
    assert open_trades_after == 0, f"¡ERROR: Quedaron {open_trades_after} trades abiertos!"
    assert active_portfolio_count == 0, f"¡ERROR: Quedaron {active_portfolio_count} activos con balance en portafolio!"

    print("\n🎉 REINICIO A $50.00 USD Y PRESERVACIÓN DE DATOS COMPLETADO CON ÉXITO.")

if __name__ == "__main__":
    run_reset()
