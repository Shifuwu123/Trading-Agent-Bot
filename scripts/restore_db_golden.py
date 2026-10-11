#!/usr/bin/env python3
"""
scripts/restore_db_golden.py

Restaura limpiamente la base de datos de SQLite fusionando el respaldo Milestone íntegro
del 08 de Octubre (tradingbot.db.bak_matrix_16usd_20261008_120949) con el último snapshot
cloud consolidado del 10 de Octubre (cloud_snapshot_tradingbot_20261010_012000.json).

Genera:
1. /home/shifu/tredding-agent/tradingbot_golden_backup.db (Golden Snapshot inmutable)
2. /home/shifu/tredding-agent/tradingbot.db (Copia persistente en disco)
3. /dev/shm/tradingbot.db (Copia activa en RAM)
4. /home/shifu/tredding-agent/backups_db/tradingbot.db.bak_golden_restored
"""

import os
import sys
import json
import sqlite3
import shutil
from datetime import datetime

BOT_DIR = "/home/shifu/tredding-agent"
BACKUP_SOURCE = os.path.join(BOT_DIR, "tradingbot.db.bak_matrix_16usd_20261008_120949")
SNAPSHOT_SOURCE = "/home/shifu/documentos-agy/cloud_snapshot_tradingbot_20261010_012000.json"
GOLDEN_DB = os.path.join(BOT_DIR, "tradingbot_golden_backup.db")
PERSISTENT_DB = os.path.join(BOT_DIR, "tradingbot.db")
RAM_DB = "/dev/shm/tradingbot.db"
BACKUP_DIR = os.path.join(BOT_DIR, "backups_db")

def restore():
    print(f"[*] Iniciando proceso de restauración limpia y Golden Backup...")
    
    if not os.path.exists(BACKUP_SOURCE):
        raise FileNotFoundError(f"No se encontró el respaldo milestone {BACKUP_SOURCE}")
    
    # 1. Crear copia de trabajo temporal para Golden DB
    temp_restored = os.path.join(BOT_DIR, "tradingbot_restored_temp.db")
    if os.path.exists(temp_restored):
        os.remove(temp_restored)
        
    shutil.copy2(BACKUP_SOURCE, temp_restored)
    print(f"[+] Base base copiada desde {BACKUP_SOURCE} ({os.path.getsize(temp_restored):,} bytes)")
    
    conn = sqlite3.connect(temp_restored)
    cur = conn.cursor()
    
    # Verificar columnas existentes en 'trades'
    trade_cols = [r[1] for r in cur.execute("PRAGMA table_info(trades)").fetchall()]
    print(f"[+] Columnas existentes en 'trades': {trade_cols}")
    
    # Agregar columnas tributarias y de comisiones si no existen
    new_cols = [
        ("fee_usd", "NUMERIC(18, 8) DEFAULT 0.0"),
        ("pnl_net_usd", "NUMERIC(18, 8) DEFAULT 0.0"),
        ("clp_exchange_rate", "NUMERIC(18, 8)"),
        ("pnl_clp", "NUMERIC(18, 8)"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in trade_cols:
            print(f"[+] Añadiendo columna '{col_name}' a tabla 'trades'...")
            cur.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type};")
            
    # Verificar columnas en 'digital_wallet'
    wallet_cols = [r[1] for r in cur.execute("PRAGMA table_info(digital_wallet)").fetchall()]
    if "reserve_usd" not in wallet_cols:
        print("[+] Añadiendo columna 'reserve_usd' a tabla 'digital_wallet'...")
        cur.execute("ALTER TABLE digital_wallet ADD COLUMN reserve_usd NUMERIC(18, 8) DEFAULT 0.0;")
        
    conn.commit()
    
    # Obtener trade_ids ya presentes
    existing_trade_ids = set(r[0] for r in cur.execute("SELECT trade_id FROM trades").fetchall())
    print(f"[+] Trades preexistentes en respaldo: {len(existing_trade_ids)}")
    
    # 2. Cargar snapshot cloud si existe y fusionar trades
    if os.path.exists(SNAPSHOT_SOURCE):
        with open(SNAPSHOT_SOURCE, "r") as f:
            snap_data = json.load(f)
            
        snap_trades = snap_data.get("trades", [])
        inserted_count = 0
        for st in snap_trades:
            tid = st.get("trade_id")
            if not tid or tid in existing_trade_ids:
                continue
                
            cur.execute("""
                INSERT INTO trades (
                    trade_id, symbol, side, order_type, quantity, price_entry, price_exit,
                    stop_loss, take_profit, pnl, pnl_pct, status, mode, strategy,
                    opened_at, closed_at, exchange, is_paper, agent_id, dca_step, exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tid, st.get("symbol"), st.get("side"), st.get("order_type", "MARKET"),
                st.get("quantity"), st.get("price_entry"), st.get("price_exit"),
                st.get("stop_loss"), st.get("take_profit"), st.get("pnl"), st.get("pnl_pct"),
                st.get("status", "OPEN"), st.get("mode"), st.get("strategy"),
                st.get("opened_at"), st.get("closed_at"), st.get("exchange", "binance"),
                st.get("is_paper", 1), st.get("agent_id", "legacy"), st.get("dca_step", 1),
                st.get("exit_reason")
            ))
            existing_trade_ids.add(tid)
            inserted_count += 1
            
        print(f"[+] Trades nuevos fusionados desde Snapshot Cloud: {inserted_count}")
        
        # Actualizar wallet con el balance del snapshot ($15.23 USD)
        snap_wallet = snap_data.get("wallet")
        if snap_wallet and "balance_usd" in snap_wallet:
            cur.execute("""
                UPDATE digital_wallet 
                SET balance_usd = ?
                WHERE id = 1
            """, (snap_wallet["balance_usd"],))
            print(f"[+] Saldo de digital_wallet actualizado a: ${snap_wallet['balance_usd']:.4f} USD")
            
        # Actualizar tabla portfolio
        snap_portfolio = snap_data.get("portfolio", [])
        if snap_portfolio:
            cur.execute("DELETE FROM portfolio;")
            for p in snap_portfolio:
                cur.execute("""
                    INSERT INTO portfolio (
                        wallet_id, asset, quantity, avg_price, current_price,
                        unrealized_pnl, updated_at, is_paper, agent_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p.get("wallet_id"), p.get("asset"), p.get("quantity", 0.0),
                    p.get("avg_price", 0.0), p.get("current_price", 0.0),
                    p.get("unrealized_pnl", 0.0), p.get("updated_at"),
                    p.get("is_paper", 1), p.get("agent_id", "legacy")
                ))
            print(f"[+] Registros de Portfolio restaurados: {len(snap_portfolio)}")
            
        conn.commit()
        
    # Verificar conteo final
    final_trades_count = cur.execute("SELECT count(*) FROM trades").fetchone()[0]
    final_wallet = cur.execute("SELECT balance_usd, reserve_usd FROM digital_wallet WHERE id = 1").fetchone()
    final_portfolio_count = cur.execute("SELECT count(*) FROM portfolio").fetchone()[0]
    final_candles_count = cur.execute("SELECT count(*) FROM candles").fetchone()[0]
    
    print(f"\n[=== VERIFICACIÓN DE INTEGRIDAD ===]")
    print(f"Total trades consolidados: {final_trades_count}")
    print(f"Billetera: ${final_wallet[0]} USD | Reserva: ${final_wallet[1]} USD")
    print(f"Activos en Portafolio: {final_portfolio_count}")
    print(f"Velas históricas (ML dataset): {final_candles_count}")
    
    # Limpieza y optimización
    cur.execute("PRAGMA quick_check;")
    qc = cur.fetchone()[0]
    if qc != "ok":
        raise RuntimeError(f"Fallo en PRAGMA quick_check: {qc}")
    print(f"Integridad SQLite: {qc.upper()}")
    
    conn.close()
    
    # 3. Establecer como Golden Backup
    shutil.copy2(temp_restored, GOLDEN_DB)
    print(f"[+] Golden Backup inmutable creado: {GOLDEN_DB} ({os.path.getsize(GOLDEN_DB):,} bytes)")
    
    # 4. Establecer como BD persistente
    shutil.copy2(temp_restored, PERSISTENT_DB)
    print(f"[+] Base persistente restablecida: {PERSISTENT_DB} ({os.path.getsize(PERSISTENT_DB):,} bytes)")
    
    # 5. Establecer en RAM
    os.makedirs(os.path.dirname(RAM_DB), exist_ok=True)
    shutil.copy2(temp_restored, RAM_DB)
    print(f"[+] Base activa en RAM restablecida: {RAM_DB} ({os.path.getsize(RAM_DB):,} bytes)")
    
    # 6. Guardar en backups_db
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    b_file = os.path.join(BACKUP_DIR, f"tradingbot.db.bak_{ts}")
    shutil.copy2(temp_restored, b_file)
    print(f"[+] Respaldo rotativo de seguridad: {b_file}")
    
    # Limpiar temporal
    os.remove(temp_restored)
    print("\n[SUCCESS] ¡Restauración completa y blindada exitosamente!")

if __name__ == "__main__":
    restore()
