"""
tradingbot/database/storage_watchdog.py

Watchdog de Salud y Auto-Sanación (Self-Healing) del Almacenamiento SQLite.
Protege al Orchestrator y a todos los subagentes contra desvinculación de descriptores
de archivo en tmpfs (/dev/shm), caídas de tablas o corrupción en caliente.
"""

import os
import sqlite3
import logging
from typing import Optional, Tuple
from tradingbot.utils.logger import log
from tradingbot.database.db_storage_manager import DBStorageManager

class StorageHealthWatchdog:
    """
    Monitor centinela para comprobar la operatividad de la base de datos antes de cada ciclo
    y auto-restaurar el estado en memoria desde el Golden Backup si ocurre alguna anomalía.
    """

    @classmethod
    def check_health(cls, db_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        Realiza un chequeo rápido de lectura contra las tablas críticas.
        Retorna (is_healthy, detail_message).
        """
        if db_path is None:
            mgr = DBStorageManager.get_instance()
            db_path = mgr.active_db_path

        if not os.path.exists(db_path):
            return False, f"Archivo de base de datos no existe en {db_path}"

        if os.path.getsize(db_path) == 0:
            return False, f"Archivo de base de datos vacío (0 bytes) en {db_path}"

        try:
            conn = sqlite3.connect(db_path, timeout=3.0)
            cur = conn.cursor()

            # 1. Comprobar existencia de tabla trades
            cur.execute("SELECT count(*) FROM trades LIMIT 1;")
            trades_count = cur.fetchone()[0]

            # 2. Comprobar existencia de tabla digital_wallet
            cur.execute("SELECT count(*) FROM digital_wallet LIMIT 1;")
            wallet_count = cur.fetchone()[0]

            conn.close()

            if trades_count == 0:
                return False, "Tabla 'trades' encontrada pero con 0 registros (posible base vacía)"

            return True, f"OK ({trades_count} trades, {wallet_count} wallets)"
        except sqlite3.OperationalError as oe:
            return False, f"OperationalError: {oe}"
        except Exception as e:
            return False, f"Excepción comprobando salud: {e}"

    @classmethod
    def auto_heal(cls, notifier=None) -> bool:
        """
        Procedimiento de auto-sanación en caliente:
        1. Restaura RAM y disco desde el Golden Backup inmutable.
        2. Reinicializa las conexiones de SQLAlchemy en DatabaseSession.
        3. Verifica la salud tras la recuperación.
        """
        log.warning("[StorageWatchdog] ⚠️ Detectada falla de persistencia. Iniciando auto-sanación en caliente...")
        mgr = DBStorageManager.get_instance()
        restored = mgr.restore_from_golden_backup()

        if not restored:
            log.error("[StorageWatchdog] ❌ Fallo al restaurar desde Golden Backup.")
            if notifier:
                notifier.send_error_alert("StorageWatchdog: Fallo crítico de auto-sanación desde Golden Backup.")
            return False

        # Reiniciar motores de SQLAlchemy
        try:
            from tradingbot.execution.portfolio_manager import DatabaseSession
            DatabaseSession.reset_engine()
            DatabaseSession.initialize()
            log.info("[StorageWatchdog] Motores de SQLAlchemy reinicializados exitosamente.")
        except Exception as e:
            log.error(f"[StorageWatchdog] Error reinicializando SQLAlchemy: {e}")

        # Comprobar salud post-restauración
        healthy, detail = cls.check_health(mgr.active_db_path)
        if healthy:
            log.info(f"[StorageWatchdog] ✅ Auto-sanación exitosa: {detail}")
            if notifier:
                notifier.send_message(
                    "🛡️ <b>Almacenamiento Auto-Sanado en Caliente</b> 🛡️\n\n"
                    "Se detectó una desconexión en la memoria RAM. El bot recuperó exitosamente el esquema "
                    "y las transacciones desde el <b>Golden Backup Inmutable</b>.\n"
                    f"Estado actual: <code>{detail}</code>"
                )
            return True
        else:
            log.critical(f"[StorageWatchdog] ❌ Post-restauración fallida: {detail}")
            if notifier:
                notifier.send_error_alert(
                    f"StorageWatchdog: Auto-sanación fallida. Estado post-recuperación: {detail}\n"
                    "Activando Pausa Preventiva de Seguridad (Safe Pause)."
                )
            return False
