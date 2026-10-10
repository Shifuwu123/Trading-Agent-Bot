#!/usr/bin/env python3
"""
scripts/sync_db_ram_to_disk.py

Script para forzar una sincronización atómica e inmediata de la base de datos
desde la memoria RAM (/dev/shm/tradingbot.db) hacia el disco persistente (/home/shifu/tredding-agent/tradingbot.db).
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingbot.database.db_storage_manager import DBStorageManager
from tradingbot.core.config import get_settings


def main():
    settings = get_settings()
    mgr = DBStorageManager.get_instance(
        active_db_path=settings.active_db_path,
        persistent_db_path=settings.persistent_db_path,
        backup_dir=settings.db_backup_dir,
    )
    result = mgr.sync_to_disk(create_timestamped_backup=False)
    if result.get("success"):
        print(f"✅ Sincronización exitosa ({result.get('duration_ms', 0):.1f}ms): {result.get('file_size', 0):,} bytes guardados.")
        sys.exit(0)
    else:
        print(f"❌ Error en sincronización: {result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
