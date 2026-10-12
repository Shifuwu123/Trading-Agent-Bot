#!/usr/bin/env python3
"""
scripts/manage_migrations.py

Herramienta CLI para gestionar migraciones de base de datos del Trading Bot.
Uso:
    python scripts/manage_migrations.py --status
    python scripts/manage_migrations.py --apply
    python scripts/manage_migrations.py --rollback-last
    python scripts/manage_migrations.py --rollback-to 001
"""

import sys
import argparse
import os

# Asegurar path del proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingbot.core.config import get_settings
from tradingbot.database.migrations.manager import MigrationManager


def main():
    parser = argparse.ArgumentParser(description="Gestor de Migraciones de Base de Datos - Trading Bot")
    parser.add_argument("--db-path", type=str, default=None, help="Ruta de la base de datos (por defecto: activa en settings)")
    parser.add_argument("--status", action="store_true", help="Muestra el estado de las migraciones")
    parser.add_argument("--apply", action="store_true", help="Aplica todas las migraciones pendientes")
    parser.add_argument("--rollback-last", action="store_true", help="Revierte la última migración aplicada")
    parser.add_argument("--rollback-to", type=str, default=None, help="Revierte hasta la versión especificada (ej. 001 o 0)")

    args = parser.parse_args()

    settings = get_settings()
    db_path = args.db_path or settings.active_db_path
    if not os.path.exists(db_path) and os.path.exists(settings.persistent_db_path):
        db_path = settings.persistent_db_path

    print(f"📦 Conectando a Base de Datos: {db_path}")
    manager = MigrationManager(db_path=db_path)

    if args.apply:
        print("🚀 Aplicando migraciones pendientes...")
        applied = manager.apply_all()
        if applied:
            print(f"✅ Migraciones aplicadas exitosamente: {', '.join(applied)}")
        else:
            print("✨ La base de datos ya está completamente actualizada. No hay cambios pendientes.")

    elif args.rollback_last:
        print("⚠️ Revirtiendo última migración...")
        rb = manager.rollback_last()
        if rb:
            print(f"✅ Migración {rb} revertida exitosamente.")
        else:
            print("ℹ️ No hay migraciones para revertir.")

    elif args.rollback_to:
        target = args.rollback_to
        print(f"⚠️ Revirtiendo migraciones hasta versión: {target}...")
        rolled = manager.rollback_to(target)
        if rolled:
            print(f"✅ Migraciones revertidas: {', '.join(rolled)}")
        else:
            print("ℹ️ No se requirieron reversiones.")

    else:
        # Estado por defecto
        status_list = manager.status()
        print("\n📋 Estado de Migraciones:")
        print("------------------------------------------------------------")
        print(f"{'Versión':<10} {'Nombre':<30} {'Estado':<12}")
        print("------------------------------------------------------------")
        for s in status_list:
            state_str = "✅ APLICADA" if s["applied"] else "⏳ PENDIENTE"
            print(f"{s['version']:<10} {s['name']:<30} {state_str:<12}")
        print("------------------------------------------------------------\n")


if __name__ == "__main__":
    main()
