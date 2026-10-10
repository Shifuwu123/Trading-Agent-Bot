#!/usr/bin/env python3
"""
scripts/reset_to_16usd_matrix.py

Reinicio completo del estado contable, órdenes y billetera a $16.00 USD (Base Matriz Multi-Agente).
Asignación base: $1.00 USD por cada una de las 16 monedas distribuidas entre los 4 agentes:
- ScalperAgent_Tier1: $7.00 USD (7 monedas: SOL, BNB, XRP, SUI, NEAR, DOGE, ADA)
- MomentumAgent_Tier2: $5.00 USD (5 monedas: FET, TAO, WLD, STRK, QNT)
- SpeculativeAgent_Tier3: $2.00 USD (2 monedas: BEAMX, MUBARAK)
- MacroTrader_BTCETH: $2.00 USD (2 monedas: BTC, ETH)

Total: 16 monedas * $1.00 USD = $16.00 USD.

PRESERVA ÍNTEGRAMENTE:
- `candles`: dataset histórico OHLCV para Deep Learning.
- `decision_logs`: micro-decisiones históricas para Machine Learning (excluyendo tests).
"""

import os
import shutil
import sqlite3
from datetime import datetime

DB_PATH = "tradingbot.db"
BACKUP_PATH = f"tradingbot.db.bak_matrix_16usd_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

VALID_ASSETS = [
    "BTC", "ETH",
    "FET", "TAO", "WLD", "STRK", "QNT",
    "SOL", "BNB", "XRP", "SUI", "NEAR", "DOGE", "ADA",
    "BEAMX", "MUBARAK"
]

def run_reset():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"No se encontró la base de datos en {DB_PATH}")

    # 1. Checkpoint WAL first
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.commit()
    conn.close()

    # 2. Create full backup
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

    # 3. Eliminar activos y trades de pruebas (TEST%)
    c.execute("DELETE FROM portfolio WHERE asset LIKE 'TEST%'")
    print(f"🧹 Activos TEST eliminados de portfolio: {c.rowcount}")
    c.execute("DELETE FROM trades WHERE symbol LIKE 'TEST%'")
    print(f"🧹 Trades TEST eliminados: {c.rowcount}")
    c.execute("DELETE FROM decision_logs WHERE symbol LIKE 'TEST%'")
    print(f"🧹 DecisionLogs TEST eliminados: {c.rowcount}")

    # 4. Reset Digital Wallet to 16.00 USD
    c.execute("UPDATE digital_wallet SET balance_usd = 16.0 WHERE is_paper = 1")
    if c.rowcount == 0:
        c.execute("INSERT INTO digital_wallet (telegram_id, balance_usd, is_paper) VALUES ('1676283475', 16.0, 1)")
    print(f"✅ Digital Wallet actualizada a $16.00 USD (filas modificadas: {c.rowcount})")

    # 5. Archive all trades
    c.execute("UPDATE trades SET status = 'ARCHIVED' WHERE status != 'ARCHIVED'")
    print(f"✅ Trades archivados: {c.rowcount} órdenes")

    # 6. Clean active portfolio positions for all legitimate coins
    c.execute("UPDATE portfolio SET quantity = 0, avg_price = 0, unrealized_pnl = 0")
    print(f"✅ Holdings de portfolio reiniciados a 0: {c.rowcount} activos")

    # Asegurar que todas las 16 monedas de la matriz existan en portfolio
    for asset in VALID_ASSETS:
        exists = c.execute("SELECT count(*) FROM portfolio WHERE asset = ? AND is_paper = 1", (asset,)).fetchone()[0]
        if not exists:
            c.execute(
                "INSERT INTO portfolio (asset, quantity, avg_price, current_price, unrealized_pnl, is_paper, updated_at) VALUES (?, 0, 0, 0, 0, 1, ?)",
                (asset, datetime.utcnow().isoformat())
            )
    print(f"✅ Matriz de 16 activos verificada en portfolio.")

    # 7. Clear cash_flow
    c.execute("DELETE FROM cash_flow")
    print(f"✅ Cashflow reiniciado a 0 registros")

    conn.commit()

    # Post-reset verification
    candles_count_after = c.execute("SELECT count(*) FROM candles").fetchone()[0]
    decisions_count_after = c.execute("SELECT count(*) FROM decision_logs").fetchone()[0]
    wallet_balance = c.execute("SELECT balance_usd FROM digital_wallet WHERE is_paper = 1").fetchone()[0]
    open_trades_after = c.execute("SELECT count(*) FROM trades WHERE status = 'OPEN'").fetchone()[0]
    active_portfolio_count = c.execute("SELECT count(*) FROM portfolio WHERE quantity > 0").fetchone()[0]
    total_portfolio_assets = c.execute("SELECT count(*) FROM portfolio WHERE is_paper = 1").fetchone()[0]

    conn.close()

    print("\n--- Verificación Post-Reinicio ---")
    print(f"Candles (Deep Learning): {candles_count_after} (Conservados: {candles_count_after == candles_count_before})")
    print(f"Decision Logs (ML):     {decisions_count_after}")
    print(f"Wallet Balance:         ${wallet_balance:.2f} USD")
    print(f"Open Trades:            {open_trades_after}")
    print(f"Active Portfolio Items: {active_portfolio_count}")
    print(f"Total Portfolio Assets: {total_portfolio_assets}")

    assert candles_count_after == candles_count_before, "¡ERROR CRÍTICO: Se alteraron las velas de deep learning!"
    assert wallet_balance == 16.0, f"¡ERROR: Balance esperado 16.0 pero se obtuvo {wallet_balance}!"
    assert open_trades_after == 0, f"¡ERROR: Quedaron {open_trades_after} trades abiertos!"
    assert active_portfolio_count == 0, f"¡ERROR: Quedaron {active_portfolio_count} activos con balance en portafolio!"

    print("\n🎉 REINICIO A $16.00 USD (MATRIZ 16 MONEDAS) COMPLETADO CON ÉXITO.")

if __name__ == "__main__":
    run_reset()
