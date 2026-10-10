#!/usr/bin/env python3
"""
scripts/cloud_sync_exporter.py

Script para probar o ejecutar la sincronización manual hacia la nube
(Turso libSQL / Neon / Webhook Vercel) y exportar snapshot local a /home/shifu/documentos-agy/.
"""

import os
import sys
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingbot.database.cloud_sync import CloudSyncProvider
from tradingbot.core.config import get_settings


def main():
    settings = get_settings()
    active_path = settings.active_db_path if os.path.exists(settings.active_db_path) else settings.persistent_db_path

    print("☁️ Iniciando exportador / replicador Cloud...")
    provider = CloudSyncProvider.from_settings(local_db_path=active_path)

    # 1. Extraer payload consolidado
    payload = provider.extract_sync_payload()
    if not payload:
        print("❌ Error: No se pudieron extraer datos de la base de datos.")
        sys.exit(1)

    print(f"📊 Datos extraídos:")
    print(f"  • Billetera: ${payload.get('wallet', {}).get('balance_usd', 0):.2f} USD")
    print(f"  • Activos en portafolio: {len(payload.get('portfolio', []))}")
    print(f"  • Trades recuperados: {len(payload.get('trades', []))}")
    print(f"  • PnL realizado acumulado: ${payload.get('metrics', {}).get('realized_pnl_usd', 0):.2f} USD")

    # 2. Guardar snapshot JSON en /home/shifu/documentos-agy/
    docs_dir = "/home/shifu/documentos-agy"
    os.makedirs(docs_dir, exist_ok=True)
    snapshot_filename = f"cloud_snapshot_tradingbot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    snapshot_path = os.path.join(docs_dir, snapshot_filename)

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"📄 Snapshot local exportado exitosamente en:\n   {snapshot_path}")

    # 3. Replicar a la nube si está habilitado
    if provider.enabled:
        print(f"🚀 Replicando a la nube (Proveedor: {provider.provider})...")
        res = provider.sync_now()
        if res.get("success"):
            print(f"✅ Replicación en la nube completada exitosamente.")
        else:
            print(f"⚠️ Aviso en replicación: {res.get('error') or res.get('message')}")
    else:
        print("ℹ️ Replicación remota deshabilitada (CLOUD_SYNC_ENABLED=false). Para activarla, configure las variables en .env.")


if __name__ == "__main__":
    main()
