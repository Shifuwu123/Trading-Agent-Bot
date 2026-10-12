"""
tradingbot/database/migrations/manager.py

Gestor institucional de migraciones de base de datos para SQLite.
Garantiza:
1. Versionado estricto e idempotente registrado en la tabla `schema_migrations`.
2. Estrategia de Rollback bidireccional (funciones up() y down()).
3. Respaldo atómico de punto en el tiempo (point-in-time snapshot) antes de cualquier migración o rollback.
4. Auto-reversión en caso de error: si una migración falla a mitad de camino, se restaura
   inmediatamente el snapshot previo para garantizar cero corrupción.
"""

import os
import sys
import shutil
import sqlite3
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from tradingbot.utils.logger import log


class MigrationError(Exception):
    """Excepción lanzada cuando falla una migración o rollback."""
    pass


class MigrationManager:
    """
    Controlador central de migraciones y reversiones (rollbacks) seguras.
    """

    MIGRATIONS_TABLE = "schema_migrations"

    def __init__(
        self,
        db_path: str,
        migrations_dir: Optional[str] = None,
        backup_dir: Optional[str] = None
    ):
        self.db_path = os.path.abspath(db_path)
        if migrations_dir is None:
            self.migrations_dir = os.path.abspath(os.path.dirname(__file__))
        else:
            self.migrations_dir = os.path.abspath(migrations_dir)

        if backup_dir is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            self.backup_dir = os.path.join(project_root, "backups_db")
        else:
            self.backup_dir = os.path.abspath(backup_dir)

        os.makedirs(self.backup_dir, exist_ok=True)
        self._ensure_migrations_table()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_migrations_table(self):
        """Crea la tabla de control schema_migrations si no existe."""
        if not os.path.exists(self.db_path):
            return

        with self._get_connection() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.MIGRATIONS_TABLE} (
                    version VARCHAR(50) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    applied_at DATETIME NOT NULL,
                    checksum VARCHAR(64)
                );
            """)
            conn.commit()

    def create_pre_migration_backup(self) -> Optional[str]:
        """
        Crea una copia física íntegra de la base de datos antes de aplicar o revertir cambios.
        Usa la API de backup online de SQLite para no bloquear lecturas concurrentes.
        """
        if not os.path.exists(self.db_path) or os.path.getsize(self.db_path) == 0:
            return None

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"pre_migration_snapshot_{now_str}.db"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        try:
            src_conn = sqlite3.connect(self.db_path, timeout=10.0)
            dst_conn = sqlite3.connect(backup_path, timeout=10.0)
            with dst_conn:
                src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            log.info(f"[MigrationManager] Respaldo pre-migración creado exitosamente en: {backup_path}")
            return backup_path
        except Exception as e:
            log.warning(f"[MigrationManager] Falló SQLite online backup ({e}), recurriendo a copia directa...")
            try:
                shutil.copy2(self.db_path, backup_path)
                return backup_path
            except Exception as ce:
                log.error(f"[MigrationManager] Error crítico creando snapshot de seguridad: {ce}")
                return None

    def restore_backup(self, backup_path: str):
        """Restaura la base de datos desde un snapshot de seguridad."""
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Snapshot no encontrado en {backup_path}")

        log.warning(f"[MigrationManager] Restaurando base de datos desde snapshot: {backup_path}")
        shutil.copy2(backup_path, self.db_path)
        log.info("[MigrationManager] Base de datos restaurada correctamente.")

    def get_applied_versions(self) -> List[str]:
        """Retorna lista ordenada de versiones ya aplicadas."""
        if not os.path.exists(self.db_path):
            return []

        self._ensure_migrations_table()
        with self._get_connection() as conn:
            rows = conn.execute(
                f"SELECT version FROM {self.MIGRATIONS_TABLE} ORDER BY version ASC;"
            ).fetchall()
            return [r["version"] for r in rows]

    def discover_migrations(self) -> List[Dict[str, Any]]:
        """
        Descubre todos los módulos de migración válidos en `migrations_dir`.
        Convención de nombre: `<version>_<nombre>.py` (ej: `001_initial_schema.py`).
        """
        migrations: List[Dict[str, Any]] = []
        if not os.path.exists(self.migrations_dir):
            return migrations

        for entry in sorted(os.listdir(self.migrations_dir)):
            if entry.endswith(".py") and not entry.startswith("__") and not entry.startswith("manager"):
                filepath = os.path.join(self.migrations_dir, entry)
                parts = entry[:-3].split("_", 1)
                version = parts[0]
                name = parts[1] if len(parts) > 1 else entry[:-3]

                # Cargar dinámicamente el módulo
                spec = importlib.util.spec_from_file_location(f"migration_{version}", filepath)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "up") and hasattr(mod, "down"):
                        migrations.append({
                            "version": str(version),
                            "name": getattr(mod, "NAME", name),
                            "file": filepath,
                            "module": mod
                        })
                    else:
                        log.warning(f"[MigrationManager] Omitiendo {entry}: no implementa up() y down().")

        migrations.sort(key=lambda m: m["version"])
        return migrations

    def apply_all(self) -> List[str]:
        """
        Aplica todas las migraciones pendientes en orden.
        Si alguna falla, revierte automáticamente al snapshot previo.
        """
        applied_versions = set(self.get_applied_versions())
        available_migrations = self.discover_migrations()
        pending = [m for m in available_migrations if m["version"] not in applied_versions]

        if not pending:
            return []

        log.info(f"[MigrationManager] Detectadas {len(pending)} migraciones pendientes para aplicar.")
        snapshot_path = self.create_pre_migration_backup()
        applied_now = []

        try:
            for mig in pending:
                v = mig["version"]
                name = mig["name"]
                log.info(f"[MigrationManager] Aplicando migración [{v}] {name}...")

                conn = self._get_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE;")
                    mig["module"].up(conn)
                    conn.execute(
                        f"INSERT INTO {self.MIGRATIONS_TABLE} (version, name, applied_at) VALUES (?, ?, ?);",
                        (v, name, datetime.now(timezone.utc).isoformat())
                    )
                    conn.commit()
                    applied_now.append(v)
                    log.info(f"[MigrationManager] Migración [{v}] {name} completada con éxito.")
                except Exception as me:
                    conn.rollback()
                    raise MigrationError(f"Fallo aplicando migración [{v}] {name}: {me}") from me
                finally:
                    conn.close()

            return applied_now

        except Exception as err:
            log.critical(f"[MigrationManager] Error durante la migración: {err}. Iniciando rollback de emergencia...")
            if snapshot_path:
                self.restore_backup(snapshot_path)
            raise

    def rollback_last(self) -> Optional[str]:
        """Revierte la última migración aplicada ejecutando su down()."""
        applied_versions = self.get_applied_versions()
        if not applied_versions:
            log.info("[MigrationManager] No hay migraciones aplicadas para revertir.")
            return None

        last_version = applied_versions[-1]
        available_migrations = {m["version"]: m for m in self.discover_migrations()}

        if last_version not in available_migrations:
            raise MigrationError(f"No se encontró el módulo de migración para la versión {last_version}")

        mig = available_migrations[last_version]
        log.warning(f"[MigrationManager] Revertiendo migración [{last_version}] {mig['name']}...")

        snapshot_path = self.create_pre_migration_backup()

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            mig["module"].down(conn)
            conn.execute(f"DELETE FROM {self.MIGRATIONS_TABLE} WHERE version = ?;", (last_version,))
            conn.commit()
            log.info(f"[MigrationManager] Migración [{last_version}] revertida exitosamente.")
            return last_version
        except Exception as re:
            conn.rollback()
            log.critical(f"[MigrationManager] Error al revertir [{last_version}]: {re}. Restaurando snapshot...")
            if snapshot_path:
                self.restore_backup(snapshot_path)
            raise MigrationError(f"Fallo al revertir [{last_version}]: {re}") from re
        finally:
            conn.close()

    def rollback_to(self, target_version: str) -> List[str]:
        """
        Revierte todas las migraciones superiores a target_version.
        target_version="0" o "base" revierte todas las migraciones.
        """
        applied = self.get_applied_versions()
        if not applied:
            return []

        if target_version in ("0", "base", "zero"):
            to_rollback = list(reversed(applied))
        else:
            if target_version not in applied:
                raise ValueError(f"Versión objetivo {target_version} no se encuentra en las migraciones aplicadas: {applied}")
            idx = applied.index(target_version)
            to_rollback = list(reversed(applied[idx + 1:]))

        rolled_back = []
        for v in to_rollback:
            rb_ver = self.rollback_last()
            if rb_ver:
                rolled_back.append(rb_ver)

        return rolled_back

    def status(self) -> List[Dict[str, Any]]:
        """Retorna el estado de todas las migraciones disponibles."""
        applied_versions = set(self.get_applied_versions())
        available = self.discover_migrations()

        result = []
        for m in available:
            is_applied = m["version"] in applied_versions
            result.append({
                "version": m["version"],
                "name": m["name"],
                "applied": is_applied,
                "file": m["file"]
            })
        return result
