"""
tradingbot/database/db_storage_manager.py

Gestor de Almacenamiento Híbrido RAM (tmpfs) y Persistencia en Disco para SQLite.
Blindado con:
- Capa Caliente (RAM): Operación en tiempo real en `/dev/shm/tradingbot.db`.
- Capa Persistente (Disco): Sincronización atómica periódica hacia `/home/shifu/tredding-agent/tradingbot.db`.
- Schema & Data Guard: Prohibición absoluta de sobreescribir disco si la base en RAM carece de tablas o registros críticos.
- Golden Snapshot Inmutable: Respaldado permanente en `tradingbot_golden_backup.db`.
- Rotación Segura de Backups: Protección contra purgas accidentales.
- Migraciones Dinámicas Ligeras: Verificación automática de campos fiscales y reservas.
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
from typing import Optional, Dict, Any, Set

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
    REQUIRED_TABLES: Set[str] = {"trades", "digital_wallet", "portfolio"}

    def __init__(
        self,
        active_db_path: str = "/dev/shm/tradingbot.db",
        persistent_db_path: str = "/home/shifu/tredding-agent/tradingbot.db",
        backup_dir: str = "/home/shifu/tredding-agent/backups_db",
        golden_backup_path: str = "/home/shifu/tredding-agent/tradingbot_golden_backup.db",
        sync_interval_seconds: int = 300,
        max_backups: int = 5,
    ):
        self.active_db_path = active_db_path
        self.persistent_db_path = persistent_db_path
        self.backup_dir = backup_dir
        self.golden_backup_path = golden_backup_path
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
        golden_backup_path: str = "/home/shifu/tredding-agent/tradingbot_golden_backup.db",
        sync_interval_seconds: int = 300,
    ) -> "DBStorageManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(
                    active_db_path=active_db_path,
                    persistent_db_path=persistent_db_path,
                    backup_dir=backup_dir,
                    golden_backup_path=golden_backup_path,
                    sync_interval_seconds=sync_interval_seconds,
                )
            return cls._instance

    # ─────────────────────────────────────────────────────────────────────────
    # Inicialización, Integridad y Schema Guard
    # ─────────────────────────────────────────────────────────────────────────

    def check_db_integrity(self, db_path: str) -> bool:
        """Verifica la integridad física básica de un archivo SQLite mediante PRAGMA quick_check."""
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

    def check_db_schema_and_data(self, db_path: str, min_trades: int = 1) -> bool:
        """
        Schema Guard: Valida que la base de datos contenga las tablas obligatorias del sistema
        y que contenga al menos min_trades operaciones registradas.
        Evita catastróficos falsos positivos de PRAGMA quick_check en bases de datos vacías de 0 o 4KB.
        """
        if not self.check_db_integrity(db_path):
            return False
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            cur = conn.cursor()
            tables = set(r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall())
            
            missing_tables = self.REQUIRED_TABLES - tables
            if missing_tables:
                log.warning(f"[DBStorage SchemaGuard] Tablas faltantes en {db_path}: {missing_tables}")
                conn.close()
                return False

            cur.execute("SELECT count(*) FROM trades;")
            trade_count = cur.fetchone()[0]
            conn.close()

            if trade_count < min_trades:
                log.warning(f"[DBStorage SchemaGuard] {db_path} contiene {trade_count} trades (esperado >= {min_trades}).")
                return False

            return True
        except Exception as e:
            log.warning(f"[DBStorage SchemaGuard] Error validando esquema/datos de {db_path}: {e}")
            return False

    def _ensure_schema_migrations(self, db_path: str):
        """Aplica migraciones ligeras no destructivas para campos fiscales, de comisiones y reserva."""
        if not os.path.exists(db_path):
            return
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            cur = conn.cursor()
            
            # 1. Tabla trades
            trade_cols = set(r[1] for r in cur.execute("PRAGMA table_info(trades);").fetchall())
            new_trade_cols = [
                ("fee_usd", "NUMERIC(18, 8) DEFAULT 0.0"),
                ("pnl_net_usd", "NUMERIC(18, 8) DEFAULT 0.0"),
                ("clp_exchange_rate", "NUMERIC(18, 8)"),
                ("pnl_clp", "NUMERIC(18, 8)"),
            ]
            for col_name, col_type in new_trade_cols:
                if col_name not in trade_cols:
                    log.info(f"[DBStorage Migrations] Añadiendo columna {col_name} a tabla trades en {db_path}")
                    cur.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type};")

            # 2. Tabla digital_wallet
            wallet_cols = set(r[1] for r in cur.execute("PRAGMA table_info(digital_wallet);").fetchall())
            if "reserve_usd" not in wallet_cols:
                log.info(f"[DBStorage Migrations] Añadiendo columna reserve_usd a tabla digital_wallet en {db_path}")
                cur.execute("ALTER TABLE digital_wallet ADD COLUMN reserve_usd NUMERIC(18, 8) DEFAULT 0.0;")

            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"[DBStorage Migrations] Error aplicando migraciones en {db_path}: {e}")

    def ensure_ram_db_initialized(self) -> str:
        """
        Garantiza que la base de datos en RAM esté disponible, íntegra y con esquema válido.
        Orden de resolución jerárquica:
        1. RAM activa existente (si pasa Schema & Data Guard).
        2. Almacenamiento persistente en disco (si pasa Schema & Data Guard).
        3. Golden Backup inmutable (`tradingbot_golden_backup.db`).
        4. Último backup rotativo verificado.
        """
        ram_dir = os.path.dirname(self.active_db_path)
        if not os.path.exists(ram_dir):
            try:
                os.makedirs(ram_dir, exist_ok=True)
            except Exception as e:
                log.error(f"[DBStorage] No se pudo crear directorio RAM {ram_dir}: {e}. Usando disco directo.")
                return self.persistent_db_path

        # 1. Verificar si la base en RAM ya es válida y funcional
        if os.path.exists(self.active_db_path) and os.path.getsize(self.active_db_path) > 0:
            if self.check_db_schema_and_data(self.active_db_path):
                log.info(
                    f"[DBStorage] Base de datos en RAM ya activa, íntegra y validada en: {self.active_db_path} "
                    f"({os.path.getsize(self.active_db_path):,} bytes)."
                )
                self._ensure_schema_migrations(self.active_db_path)
                self.register_shutdown_handlers()
                return self.active_db_path
            else:
                log.warning("[DBStorage] Base en RAM dañada, vacía o sin esquema válido. Se purgará para restaurar.")
                try:
                    os.remove(self.active_db_path)
                except Exception:
                    pass

        # 2. Copiar desde base de datos persistente si cumple Schema Guard
        if os.path.exists(self.persistent_db_path) and os.path.getsize(self.persistent_db_path) > 0:
            if self.check_db_schema_and_data(self.persistent_db_path):
                log.info(f"[DBStorage] Cargando base de datos persistente ({self.persistent_db_path}) hacia RAM...")
                self._safe_copy_online(self.persistent_db_path, self.active_db_path)
                self._ensure_schema_migrations(self.active_db_path)
                log.info(f"[DBStorage] Base de datos cargada en RAM ({os.path.getsize(self.active_db_path):,} bytes).")
                self.register_shutdown_handlers()
                return self.active_db_path
            else:
                log.warning(f"[DBStorage] Base en disco {self.persistent_db_path} no superó el Schema Guard.")

        # 3. Restaurar desde Golden Snapshot inmutable
        if os.path.exists(self.golden_backup_path) and self.check_db_schema_and_data(self.golden_backup_path):
            log.info(f"[DBStorage] Restaurando desde Golden Snapshot Inmutable: {self.golden_backup_path}...")
            self._safe_copy_online(self.golden_backup_path, self.active_db_path)
            self._safe_copy_online(self.golden_backup_path, self.persistent_db_path)
            self._ensure_schema_migrations(self.active_db_path)
            self.register_shutdown_handlers()
            return self.active_db_path

        # 4. Buscar el backup rotativo más reciente válido
        latest_backup = self._get_latest_valid_backup()
        if latest_backup:
            log.info(f"[DBStorage] Restaurando desde backup rotativo válido: {latest_backup}...")
            self._safe_copy_online(latest_backup, self.active_db_path)
            self._safe_copy_online(latest_backup, self.persistent_db_path)
            self._ensure_schema_migrations(self.active_db_path)
            self.register_shutdown_handlers()
            return self.active_db_path

        log.error(f"[DBStorage CRITICAL] Ningún respaldo válido superó el Schema Guard. Inicializando base vacía en {self.active_db_path}")
        self.register_shutdown_handlers()
        return self.active_db_path

    def restore_from_golden_backup(self) -> bool:
        """Procedimiento explícito de auto-sanación desde el Golden Backup."""
        if not os.path.exists(self.golden_backup_path):
            log.error(f"[DBStorage] Golden Backup no existe en {self.golden_backup_path}")
            return False

        if not self.check_db_schema_and_data(self.golden_backup_path):
            log.error(f"[DBStorage] Golden Backup corrupto o no supera Schema Guard.")
            return False

        try:
            log.info(f"[DBStorage] Auto-sanación: Restaurando RAM y Disco desde Golden Backup...")
            self._safe_copy_online(self.golden_backup_path, self.active_db_path)
            self._safe_copy_online(self.golden_backup_path, self.persistent_db_path)
            self._ensure_schema_migrations(self.active_db_path)
            return True
        except Exception as e:
            log.error(f"[DBStorage] Error en restore_from_golden_backup: {e}")
            return False

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
            if self.check_db_schema_and_data(b):
                return b
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Sincronización Atómica RAM -> Disco con Schema Guard
    # ─────────────────────────────────────────────────────────────────────────

    def sync_to_disk(self, create_timestamped_backup: bool = False, suppress_logging: bool = False) -> Dict[str, Any]:
        """
        Sincroniza de forma atómica y sin bloquear la base de datos en RAM
        hacia el almacenamiento persistente en MicroSD / disco.

        Schema Guard Activo:
        Verifica que la base de datos de origen en RAM contenga las tablas esenciales
        y datos de trades antes de tocar o sobreescribir el disco.
        """
        start_time = time.time()
        if not os.path.exists(self.active_db_path):
            return {"success": False, "error": f"Base de datos activa en RAM no encontrada en {self.active_db_path}"}

        # SCHEMA GUARD PREVIO: Prohibir sincronizar si la base en RAM está corrupta o vacía
        if not self.check_db_schema_and_data(self.active_db_path):
            err_msg = "[DBStorage SchemaGuard] Abortando sincronización a disco: la base activa en RAM no contiene esquema válido ni trades."
            if not suppress_logging:
                log.error(err_msg)
            return {"success": False, "error": err_msg}

        temp_disk_path = f"{self.persistent_db_path}.tmp_sync"
        try:
            # 1. Copia online atómica hacia archivo temporal en disco
            src_conn = sqlite3.connect(self.active_db_path, timeout=10.0)
            dst_conn = sqlite3.connect(temp_disk_path, timeout=10.0)
            with dst_conn:
                src_conn.backup(dst_conn, pages=200)
            dst_conn.close()
            src_conn.close()

            # 2. SCHEMA GUARD POSTERIOR: Verificar que el archivo sincronizado sea idéntico en integridad y esquema
            if not self.check_db_schema_and_data(temp_disk_path):
                if os.path.exists(temp_disk_path):
                    os.remove(temp_disk_path)
                return {"success": False, "error": "Schema Guard falló en el archivo temporal sincronizado"}

            # 3. Reemplazo atómico (atomic swap) hacia el archivo persistente
            os.replace(temp_disk_path, self.persistent_db_path)

            file_size = os.path.getsize(self.persistent_db_path)
            duration_ms = (time.time() - start_time) * 1000.0
            self._last_sync_time = datetime.now(timezone.utc)

            # 4. Generación de snapshot rotativo seguro si fue solicitado
            if create_timestamped_backup:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_target = os.path.join(self.backup_dir, f"tradingbot.db.bak_{ts}")
                shutil.copy2(self.persistent_db_path, backup_target)
                self._rotate_backups()

            if not suppress_logging:
                try:
                    log.info(
                        f"[DBStorage] Sincronización RAM -> Disco blindada completada en {duration_ms:.1f}ms "
                        f"({file_size:,} bytes). MicroSD protegida exitosamente."
                    )
                except Exception:
                    pass
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
        """Mantiene solo los max_backups más recientes en backup_dir, preservando copias válidas."""
        try:
            backups = sorted(
                [os.path.join(self.backup_dir, f) for f in os.listdir(self.backup_dir) if f.startswith("tradingbot.db.bak_")],
                key=os.path.getmtime,
                reverse=True,
            )
            if len(backups) > self.max_backups:
                for old in backups[self.max_backups:]:
                    try:
                        # Nunca borrar el Golden Backup si estuviera en este directorio
                        if "golden" in os.path.basename(old):
                            continue
                        os.remove(old)
                        log.debug(f"[DBStorage] Backup rotado: {old}")
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
        Purga registros redundantes de micro-decisiones 'HOLD' y velas antiguas.
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

            # 1. Eliminar decisiones 'HOLD' antiguas
            cur.execute("DELETE FROM decision_logs WHERE decision = 'HOLD' AND timestamp < ?", (cutoff_hold,))
            deleted_hold = cur.rowcount

            # 2. Eliminar logs no críticos con más de 14 días
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
                f"{deleted_other_logs:,} logs, {deleted_candles:,} velas."
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
            if self._stop_event.wait(timeout=self.sync_interval_seconds):
                break

            try:
                save_backup = (iteration_count % 6 == 0)
                self.sync_to_disk(create_timestamped_backup=save_backup)

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
                self.sync_to_disk(create_timestamped_backup=False, suppress_logging=True)
            except Exception:
                pass
