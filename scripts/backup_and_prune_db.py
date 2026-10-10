#!/usr/bin/env python3
"""
scripts/backup_and_prune_db.py

Script de mantenimiento preventivo y optimización de base de datos.
- Crea un backup atómico de seguridad en backups_db/
- Purga micro-decisiones 'HOLD' antiguas (> 3 días) y velas (> 7 días)
- Ejecuta VACUUM para compactar y desfragmentar el archivo
- Reporta la reducción de tamaño y filas
"""

import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone

# Agregar raíz del proyecto al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingbot.database.db_storage_manager import DBStorageManager
from tradingbot.core.config import get_settings


def main():
    settings = get_settings()
    active_path = settings.active_db_path if os.path.exists(settings.active_db_path) else settings.persistent_db_path
    if not os.path.exists(active_path):
        active_path = "/home/shifu/tredding-agent/tradingbot.db"

    if not os.path.exists(active_path):
        print(f"❌ Error: Base de datos no encontrada en {active_path}")
        sys.exit(1)

    print(f"📦 Base de datos objetivo: {active_path}")
    size_before = os.path.getsize(active_path)
    print(f"📊 Tamaño inicial: {size_before / (1024 * 1024):.2f} MB ({size_before:,} bytes)")

    mgr = DBStorageManager.get_instance(
        active_db_path=active_path,
        persistent_db_path=settings.persistent_db_path,
        backup_dir=settings.db_backup_dir,
    )

    # 1. Crear backup de seguridad
    print("💾 Creando backup de seguridad en backups_db/...")
    backup_res = mgr.sync_to_disk(create_timestamped_backup=True)
    if backup_res.get("success"):
        print(f"✅ Backup creado exitosamente.")
    else:
        print(f"⚠️ Aviso en backup: {backup_res.get('error')}")

    # 2. Housekeeping
    print("🧹 Ejecutando purgado de tablas de alta frecuencia...")
    hk_res = mgr.run_housekeeping(
        retention_days_hold=3,
        retention_days_candles=7,
        retention_days_logs=14
    )
    if hk_res.get("success"):
        print(f"  • HOLDs eliminados: {hk_res.get('deleted_hold', 0):,}")
        print(f"  • Logs secundarios eliminados: {hk_res.get('deleted_other_logs', 0):,}")
        print(f"  • Velas antiguas eliminadas: {hk_res.get('deleted_candles', 0):,}")
    else:
        print(f"❌ Error en housekeeping: {hk_res.get('error')}")

    # 3. VACUUM
    print("🗜️ Ejecutando VACUUM para compactar páginas...")
    conn = sqlite3.connect(active_path)
    conn.execute("VACUUM;")
    conn.close()

    # 4. Sincronizar de vuelta a disco persistente si estábamos en RAM
    if "/dev/shm" in active_path:
        print("🔄 Sincronizando base de datos compactada de RAM a disco...")
        mgr.sync_to_disk(create_timestamped_backup=False)

    size_after = os.path.getsize(active_path)
    diff = size_before - size_after
    pct = (diff / size_before) * 100.0 if size_before > 0 else 0.0

    print(f"\n🎉 Mantenimiento completado con éxito:")
    print(f"  • Tamaño final: {size_after / (1024 * 1024):.2f} MB ({size_after:,} bytes)")
    print(f"  • Espacio liberado: {diff / (1024 * 1024):.2f} MB ({pct:.1f}% de reducción)")


if __name__ == "__main__":
    main()
