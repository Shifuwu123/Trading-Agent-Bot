#!/usr/bin/env python3
"""
CLI Conversor de Horarios: Chile (America/Santiago) ⇄ UTC
Permite consultar la hora actual, ver las ventanas de volatilidad y convertir horas específicas.
Uso:
    python scripts/horarios.py
    python scripts/horarios.py 13:00 UTC
    python scripts/horarios.py 10:30 CL
"""

import sys
import os
from pathlib import Path

# Añadir raíz del proyecto al path
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tradingbot.utils.tz import (
    now_chile,
    now_utc,
    utc_to_chile,
    chile_to_utc,
    format_chile,
    format_chile_human,
    format_dual_tz,
    get_chile_offset_str,
    get_active_hours_info,
    parse_datetime
)


def print_dashboard():
    info = get_active_hours_info(start_utc=13, end_utc=17)
    status = "🟢 ACTIVO (Timeframe 1m / Alta Volatilidad)" if info["is_active_now"] else "⏸️ PASIVO (Timeframe 5m / Normal)"
    
    print("=" * 65)
    print(" 🇨🇱 CONVERSOR & MONITOR DE HORARIOS (CHILE ⇄ UTC)")
    print("=" * 65)
    print(f" • Hora Local Chile:       {info['current_chile_full']} ({info['offset_str']})")
    print(f" • Hora Servidores (UTC):  {info['current_utc_str']} UTC")
    print("-" * 65)
    print(" ⚡ VENTANA DE HORAS ACTIVAS (SCALPER / ALTA VOLATILIDAD):")
    print(f" • Horario en Chile:       {info['active_range_chile']}")
    print(f" • Horario en UTC:         {info['active_range_utc']}")
    print(f" • Estado en este instante:{status}")
    print("-" * 65)
    print(" 💡 NOTA:")
    print("   Binance y los exchanges operan en UTC.")
    print(f"   Tu zona horaria actual tiene una diferencia de {info['offset_str']} respecto a UTC.")
    print("=" * 65)


def convert_custom(time_arg: str, source_tz: str = "UTC"):
    time_arg = time_arg.strip()
    source_tz = source_tz.upper().strip()
    
    # Si viene formato HH:MM
    if ":" in time_arg and len(time_arg.split(":")) in (2, 3):
        parts = time_arg.split(":")
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        now_dt = now_chile()
        
        if source_tz in ("UTC", "GMT", "Z"):
            from datetime import datetime, timezone
            dt_src = datetime(now_dt.year, now_dt.month, now_dt.day, h, m, s, tzinfo=timezone.utc)
            dt_tgt = utc_to_chile(dt_src)
            print(f"🕒 {time_arg} UTC  ➡️  {dt_tgt.strftime('%H:%M:%S')} Chile ({get_chile_offset_str()})")
        else:
            from zoneinfo import ZoneInfo
            from datetime import datetime
            dt_src = datetime(now_dt.year, now_dt.month, now_dt.day, h, m, s, tzinfo=ZoneInfo("America/Santiago"))
            dt_tgt = chile_to_utc(dt_src)
            print(f"🕒 {time_arg} Chile ({get_chile_offset_str()})  ➡️  {dt_tgt.strftime('%H:%M:%S')} UTC")
    else:
        # Parsear fecha completa
        parsed = parse_datetime(time_arg)
        if parsed:
            cl = utc_to_chile(parsed)
            u = chile_to_utc(cl)
            print(f"🕒 Entrada: {time_arg}")
            print(f"🇨🇱 Chile:   {cl.strftime('%Y-%m-%d %H:%M:%S')} ({get_chile_offset_str(cl)})")
            print(f"🌐 UTC:     {u.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        else:
            print(f"❌ Formato no reconocido: '{time_arg}'. Ejemplos válidos: '13:00 UTC', '10:00 CL', '2026-10-08 14:00:00'")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_dashboard()
    elif len(sys.argv) == 2:
        convert_custom(sys.argv[1], "UTC")
    elif len(sys.argv) >= 3:
        convert_custom(sys.argv[1], sys.argv[2])
