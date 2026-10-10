"""
tradingbot/database/db_storage_manager.py

Gestor de Almacenamiento Híbrido RAM (tmpfs) y Persistencia en Disco para SQLite.

Arquitectura:
- Capa Caliente (RAM): Operación en tiempo real en `/dev/shm/tradingbot.db`.
  Elimina el 100% de micro-escrituras aleatorias a la tarjeta MicroSD de la Raspberry Pi,
  proporcionando latencia inferior a 0.05 ms y protegiendo la memoria Flash NAND contra desgaste.
- Capa Persistente (Disco): Sincronización atómica periódica (cada 5 minutos) y al apagar
  hacia `/home/shifu/tredding-agent/tradingbot.db` mediante la API Online Backup de SQLite.
- Copias de Seguridad (Snapshots): Historial rotativo en `/home/shifu/tredding-agent/backups_db/`.
- Housekeeping: Purgado automático de micro-decisiones 'HOLD' y velas antiguas para mantener
  la base de datos compacta y veloz.
"""

import os
import sys
import time
import shutil
import sqlite3
import logging
import threading
import atexit
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any

log = logging.getLogger("tradingbot.database.db_storage_manager")
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


class DBStorageManager:
    """
    Controlador central para la base de datos en RAM y persistencia asíncrona.
    Implementa el patrón Singleton para garantizar un único sincronizador en el proceso.
    """

    _instance: Optional["DBStorageManager"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        active_db_path: str = "/dev/shm/tradingbot.db",
        persistent_db_path: str = "/home/shifu/tredding-agent/tradingbot.db",
        backup_dir: str = "/home/shifu/tredding-agent/backups_db",
        sync_interval_seconds: int = 300,
        max_backups: int = 5,
    ):
        self.active_db_path = active_db_path
        self.persistent_db_path = persistent_db_path
        self.backup_dir = backup_dir
        self.sync_interval_seconds = sync_interval_seconds
        self.max_backups = max_backups

        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_sync_time: Optional[datetime] = None
        self._last_housekeeping_time: Optional[datetime] = None
        self._handlers_registered = False

        # Asegurar directorio de backups
        os.makedirs(self.backup_dir, exist_ok=True)

    @classmethod
    def get_instance(
        cls,
        active_db_path: str = "/dev/shm/tradingbot.db",
        persistent_db_path: str = "/home/shifu/tredding-agent/tradingbot.db",
        backup_dir: str = "/home/shifu/tredding-agent/backups_db",
        sync_interval_seconds: int = 300,
    ) -> "DBStorageManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(
                    active_db_path=active_db_path,
                    persistent_db_path=persistent_db_path,
                    backup_dir=backup_dir,
                    sync_interval_seconds=sync_interval_seconds,
                )
            return cls._instance

    # ─────────────────────────────────────────────────────────────────────────
    # Inicialización e Integridad
    # ─────────────────────────────────────────────────────────────────────────

    def check_db_integrity(self, db_path: str) -> bool:
        """Verifica la integridad de un archivo SQLite mediante PRAGMA quick_check."""
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            return False
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            cur = conn.cursor()
            cur.execute("PRAGMA quick_check;")
            res = cur.fetchone()
            conn.close()
            return res is not None and res[0] == "ok"
        except Exception as e:
            log.warning(f"[DBStorage] Error comprobando integridad de {db_path}: {e}")
            return False

    def ensure_ram_db_initialized(self) -> str:
        """
        Garantiza que la base de datos en RAM esté disponible y sea consistente.
        Si no existe en RAM, la copia desde el archivo persistente en disco o backups.
        Retorna la ruta absoluta activa a utilizar.
        """
        ram_dir = os.path.dirname(self.active_db_path)
        if not os.path.exists(ram_dir):
            try:
                os.makedirs(ram_dir, exist_ok=True)
            except Exception as e:
                log.error(f"[DBStorage] No se pudo crear directorio RAM {ram_dir}: {e}. Usando disco directo.")
                return self.persistent_db_path

        # Si ya existe en RAM y es íntegra, reutilizarla (ej: reinicio rápido del bot)
        if os.path.exists(self.active_db_path) and os.path.getsize(self.active_db_path) > 0:
            if self.check_db_integrity(self.active_db_path):
                log.info(f"[DBStorage] Base de datos en RAM ya activa e íntegra en: {self.active_db_path} ({os.path.getsize(self.active_db_path):,} bytes)")
                self.register_shutdown_handlers()
                return self.active_db_path
            else:
                log.warning(f"[DBStorage] Archivo en RAM corrupto o dañado. Se restaurará desde disco persistente.")
                try:
                    os.remove(self.active_db_path)
                except Exception:
                    pass

        # Copiar desde la base de datos persistente si existe
        if os.path.exists(self.persistent_db_path) and os.path.getsize(self.persistent_db_path) > 0:
            if self.check_db_integrity(self.persistent_db_path):
                log.info(f"[DBStorage] Cargando base de datos persistente ({self.persistent_db_path}) hacia RAM ({self.active_db_path})...")
                self._safe_copy_online(self.persistent_db_path, self.active_db_path)
                log.info(f"[DBStorage] Base de datos cargada exitosamente en RAM ({os.path.getsize(self.active_db_path):,} bytes).")
                self.register_shutdown_handlers()
                return self.active_db_path
            else:
                log.warning(f"[DBStorage] Base de datos en disco {self.persistent_db_path} no supera verificación. Buscando en backups...")

        # Si la persistente no existe o está corrupta, buscar el backup más reciente
        latest_backup = self._get_latest_valid_backup()
        if latest_backup:
            log.info(f"[DBStorage] Restaurando desde backup más reciente: {latest_backup} hacia RAM...")
            self._safe_copy_online(latest_backup, self.active_db_path)
            self.register_shutdown_handlers()
            return self.active_db_path

        log.info(f"[DBStorage] No se encontró base de datos previa. Inicializando nueva en RAM: {self.active_db_path}")
        self.register_shutdown_handlers()
        return self.active_db_path

    def _safe_copy_online(self, src_path: str, dst_path: str) -> bool:
        """Copia segura entre bases de datos usando sqlite3.Connection.backup."""
        try:
            src_conn = sqlite3.connect(src_path, timeout=10.0)
            dst_conn = sqlite3.connect(dst_path, timeout=10.0)
            with dst_conn:
                src_conn.backup(dst_conn, pages=100)
            dst_conn.close()
            src_conn.close()
            return True
        except Exception as e:
            log.warning(f"[DBStorage] Error en backup online de {src_path} a {dst_path}: {e}. Fallback a copia estándar.")
            try:
                shutil.copy2(src_path, dst_path)
                return True
            except Exception as e2:
                log.error(f"[DBStorage] Error crítico copiando archivo de DB: {e2}")
                return False

    def _get_latest_valid_backup(self) -> Optional[str]:
        if not os.path.exists(self.backup_dir):
            return None
        backups = sorted(
            [os.path.join(self.backup_dir, f) for f in os.listdir(self.backup_dir) if f.startswith("tradingbot.db.bak_")],
            key=os.path.getmtime,
            reverse=True,
        )
        for b in backups:
            if self.check_db_integrity(b):
                return b
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Sincronización Atómica RAM -> Disco
    # ─────────────────────────────────────────────────────────────────────────

    def sync_to_disk(self, create_timestamped_backup: bool = False) -> Dict[str, Any]:
        """
        Sincroniza de forma atómica y sin bloquear la base de datos en RAM
        hacia el almacenamiento persistente en la MicroSD / disco.

        Utiliza la API Online Backup de SQLite hacia un archivo temporal y luego
        realiza un reemplazo atómico con os.replace, garantizando tolerancia absoluta
        a cortes imprevistos de electricidad o caídas del sistema operativo.
        """
        start_time = time.time()
        if not os.path.exists(self.active_db_path):
            return {"success": False, "error": f"Base de datos activa en RAM no encontrada en {self.active_db_path}"}

        temp_disk_path = f"{self.persistent_db_path}.tmp_sync"
        try:
            # 1. Copia online atómica hacia archivo temporal en disco
            src_conn = sqlite3.connect(self.active_db_path, timeout=10.0)
            dst_conn = sqlite3.connect(temp_disk_path, timeout=10.0)
            with dst_conn:
                src_conn.backup(dst_conn, pages=200)
            dst_conn.close()
            src_conn.close()

            # 2. Verificar integridad del archivo temporal recién escrito
            if not self.check_db_integrity(temp_disk_path):
                if os.path.exists(temp_disk_path):
                    os.remove(temp_disk_path)
                return {"success": False, "error": "Verificación de integridad falló en el archivo temporal sincronizado"}

            # 3. Reemplazo atómico (atomic swap) hacia el archivo persistente
            os.replace(temp_disk_path, self.persistent_db_path)

            file_size = os.path.getsize(self.persistent_db_path)
            duration_ms = (time.time() - start_time) * 1000.0
            self._last_sync_time = datetime.now(timezone.utc)

            # 4. Generación de snapshot rotativo si fue solicitado
            if create_timestamped_backup:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_target = os.path.join(self.backup_dir, f"tradingbot.db.bak_{ts}")
                shutil.copy2(self.persistent_db_path, backup_target)
                self._rotate_backups()

            log.info(
                f"[DBStorage] Sincronización RAM -> Disco completada en {duration_ms:.1f}ms "
                f"({file_size:,} bytes). Desgaste en SD contenido exitosamente."
            )
            return {
                "success": True,
                "synced_at": self._last_sync_time.isoformat(),
                "file_size": file_size,
                "duration_ms": duration_ms,
            }
        except Exception as e:
            log.error(f"[DBStorage] Error durante sincronización RAM -> Disco: {e}", exc_info=True)
            if os.path.exists(temp_disk_path):
                try:
                    os.remove(temp_disk_path)
                except Exception:
                    pass
            return {"success": False, "error": str(e)}

    def _rotate_backups(self):
        """Mantiene solo los max_backups más recientes en backup_dir."""
        try:
            backups = sorted(
                [os.path.join(self.backup_dir, f) for f in os.listdir(self.backup_dir) if f.startswith("tradingbot.db.bak_")],
                key=os.path.getmtime,
                reverse=True,
            )
            if len(backups) > self.max_backups:
                for old in backups[self.max_backups:]:
                    try:
                        os.remove(old)
                        log.debug(f"[DBStorage] Backup antiguo rotado y eliminado: {old}")
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"[DBStorage] Error rotando backups: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Housekeeping y Optimización de Tablas
    # ─────────────────────────────────────────────────────────────────────────

    def run_housekeeping(
        self,
        retention_days_hold: int = 3,
        retention_days_candles: int = 7,
        retention_days_logs: int = 14,
    ) -> Dict[str, Any]:
        """
        Purga registros redundantes antiguos de micro-decisiones 'HOLD' y velas
        para evitar que la base de datos en RAM crezca de forma indefinida.
        Preserva de manera estricta todos los trades, balances, portfolio y logs críticos.
        """
        if not os.path.exists(self.active_db_path):
            return {"success": False, "error": "Base de datos en RAM no existe."}

        now_utc = datetime.now(timezone.utc)
        cutoff_hold = (now_utc - timedelta(days=retention_days_hold)).strftime("%Y-%m-%d %H:%M:%S")
        cutoff_candles = (now_utc - timedelta(days=retention_days_candles)).strftime("%Y-%m-%d %H:%M:%S")
        cutoff_logs = (now_utc - timedelta(days=retention_days_logs)).strftime("%Y-%m-%d %H:%M:%S")

        try:
            conn = sqlite3.connect(self.active_db_path, timeout=10.0)
            cur = conn.cursor()

            # 1. Eliminar decisiones 'HOLD' antiguas (alta frecuencia y nulo valor histórico)
            cur.execute("DELETE FROM decision_logs WHERE decision = 'HOLD' AND timestamp < ?", (cutoff_hold,))
            deleted_hold = cur.rowcount

            # 2. Eliminar otros logs no críticos con más de 14 días
            cur.execute(
                "DELETE FROM decision_logs WHERE decision NOT IN ('BUY', 'BUY_DCA_1', 'BUY_DCA_2', 'CLOSED') AND timestamp < ?",
                (cutoff_logs,),
            )
            deleted_other_logs = cur.rowcount

            # 3. Eliminar velas antiguas de más de 7 días
            cur.execute("DELETE FROM candles WHERE timestamp < ?", (cutoff_candles,))
            deleted_candles = cur.rowcount

            conn.commit()

            # 4. Desfragmentar páginas libres si se eliminó una cantidad significativa
            total_deleted = deleted_hold + deleted_other_logs + deleted_candles
            if total_deleted > 5000:
                cur.execute("VACUUM;")

            conn.close()
            self._last_housekeeping_time = now_utc

            log.info(
                f"[DBStorage Housekeeping] Purgado completado: {deleted_hold:,} HOLDs, "
                f"{deleted_other_logs:,} logs antiguos, {deleted_candles:,} velas eliminadas."
            )
            return {
                "success": True,
                "deleted_hold": deleted_hold,
                "deleted_other_logs": deleted_other_logs,
                "deleted_candles": deleted_candles,
                "executed_at": now_utc.isoformat(),
            }
        except Exception as e:
            log.warning(f"[DBStorage] Error en rutina de housekeeping: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    # Sincronización en Segundo Plano y Handlers de Apagado
    # ─────────────────────────────────────────────────────────────────────────

    def start_background_sync(self, interval_seconds: Optional[int] = None):
        """Inicia el hilo daemon en segundo plano para sincronizaciones periódicas."""
        if interval_seconds:
            self.sync_interval_seconds = interval_seconds

        with self._lock:
            if self._sync_thread is not None and self._sync_thread.is_alive():
                log.debug("[DBStorage] Hilo de sincronización periódica ya está activo.")
                return

            self._stop_event.clear()
            self._sync_thread = threading.Thread(
                target=self._sync_loop,
                name="DBStorage-SyncWorker",
                daemon=True,
            )
            self._sync_thread.start()
            log.info(f"[DBStorage] Hilo de sincronización periódica iniciado (intervalo: {self.sync_interval_seconds}s).")

    def _sync_loop(self):
        """Ciclo continuo del trabajador de sincronización en segundo plano."""
        iteration_count = 0
        while not self._stop_event.is_set():
            # Esperar el intervalo indicado permitiendo cancelación inmediata
            if self._stop_event.wait(timeout=self.sync_interval_seconds):
                break

            try:
                # Sincronización atómica periódica a disco
                # Cada 6 ciclos (~30 min con intervalo 300s) genera un snapshot rotativo
                save_backup = (iteration_count % 6 == 0)
                self.sync_to_disk(create_timestamped_backup=save_backup)

                # Cada 12 ciclos (~60 min) ejecuta housekeeping preventivo
                if iteration_count % 12 == 0:
                    self.run_housekeeping()

                iteration_count += 1
            except Exception as e:
                log.warning(f"[DBStorage] Error en ciclo de sincronización periódica: {e}")

    def stop_background_sync(self):
        """Detiene el hilo de sincronización y realiza un último volcado limpio."""
        log.info("[DBStorage] Deteniendo hilo de sincronización y ejecutando flush final a disco...")
        self._stop_event.set()
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)
        self.sync_to_disk(create_timestamped_backup=True)

    def register_shutdown_handlers(self):
        """Registra atexit y señales del sistema operativo para persistir la RAM al cerrar."""
        if self._handlers_registered:
            return
        self._handlers_registered = True

        atexit.register(self._on_process_exit)

        def sig_handler(signum, frame):
            log.info(f"[DBStorage] Señal capturada ({signum}). Persistiendo base de datos en RAM a disco antes de salir...")
            try:
                self.sync_to_disk(create_timestamped_backup=True)
            except Exception as e:
                log.error(f"[DBStorage] Error en persistencia final por señal: {e}")
            sys.exit(0)

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, sig_handler)
            except Exception:
                pass

    def _on_process_exit(self):
        """Hook invocado automáticamente al finalizar el proceso Python."""
        try:
            can_log = True
            for h in log.handlers:
                if getattr(h, "stream", None) and getattr(h.stream, "closed", False):
                    can_log = False
                    break
            if can_log:
                log.info("[DBStorage atexit] Persistiendo estado final de RAM hacia almacenamiento persistente...")
        except Exception:
            pass
        finally:
            try:
                self.sync_to_disk(create_timestamped_backup=False)
            except Exception:
                pass
