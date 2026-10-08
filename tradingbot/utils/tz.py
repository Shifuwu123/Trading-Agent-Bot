"""
Módulo de Conversión y Formateo de Horarios para Chile (America/Santiago) y UTC.
Proporciona utilidades para estandarizar el manejo de zonas horarias en informes,
mensajes de Telegram, logs, interfaces y consultas a la base de datos.
"""

import re
from datetime import datetime, timezone, timedelta, date, time
from typing import Union, Optional, Tuple, Dict, Any
from zoneinfo import ZoneInfo

CHILE_TZ_NAME = "America/Santiago"
CHILE_TZ = ZoneInfo(CHILE_TZ_NAME)
UTC_TZ = timezone.utc


def now_chile() -> datetime:
    """Retorna la fecha y hora actual con zona horaria de Chile (America/Santiago)."""
    return datetime.now(CHILE_TZ)


def now_utc() -> datetime:
    """Retorna la fecha y hora actual con zona horaria UTC."""
    return datetime.now(UTC_TZ)


def parse_datetime(dt_val: Union[datetime, str, float, int, None], default_tz=UTC_TZ) -> Optional[datetime]:
    """
    Parsea de forma flexible un datetime, string ISO/SQL o timestamp Unix.
    Si el datetime resultante es naive (sin zona horaria), se le asigna default_tz (por defecto UTC).
    """
    if dt_val is None:
        return None
    if isinstance(dt_val, (int, float)):
        return datetime.fromtimestamp(dt_val, tz=default_tz)
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=default_tz)
        return dt_val
    if isinstance(dt_val, str):
        val = dt_val.strip()
        if not val or val.lower() in ("none", "null", "n/a"):
            return None
        # Intentar fromisoformat primero
        try:
            iso_val = val.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso_val)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=default_tz)
            return parsed
        except ValueError:
            pass

        # Formatos comunes de bases de datos y logs
        formats = [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%Y%m%d_%H%M%S",
            "%Y%m%d%H%M%S",
        ]
        for fmt in formats:
            try:
                parsed = datetime.strptime(val, fmt)
                return parsed.replace(tzinfo=default_tz)
            except ValueError:
                continue

    return None


def utc_to_chile(dt_val: Union[datetime, str, float, int, None]) -> Optional[datetime]:
    """
    Convierte cualquier fecha/hora UTC (datetime, string o timestamp) a zona horaria de Chile.
    """
    dt = parse_datetime(dt_val, default_tz=UTC_TZ)
    if dt is None:
        return None
    return dt.astimezone(CHILE_TZ)


def chile_to_utc(dt_val: Union[datetime, str, float, int, None]) -> Optional[datetime]:
    """
    Convierte cualquier fecha/hora de Chile (datetime, string o timestamp) a UTC.
    """
    dt = parse_datetime(dt_val, default_tz=CHILE_TZ)
    if dt is None:
        return None
    return dt.astimezone(UTC_TZ)


# Alias prácticos
to_chile = utc_to_chile
to_utc = chile_to_utc


def format_chile(
    dt_val: Union[datetime, str, float, int, None],
    fmt: str = "%Y-%m-%d %H:%M:%S",
    include_tz: bool = False,
    default_str: str = "N/A"
) -> str:
    """
    Formatea una fecha/hora en horario de Chile según el formato especificado.
    """
    dt_cl = utc_to_chile(dt_val)
    if dt_cl is None:
        return default_str
    res = dt_cl.strftime(fmt)
    if include_tz:
        offset = get_chile_offset_str(dt_cl)
        res = f"{res} ({offset})"
    return res


def format_chile_human(dt_val: Union[datetime, str, float, int, None], default_str: str = "N/A") -> str:
    """
    Retorna un formato legible para humanos en Chile: '08/10/2026 11:30:00 (Chile / UTC-3)'.
    """
    dt_cl = utc_to_chile(dt_val)
    if dt_cl is None:
        return default_str
    offset = get_chile_offset_str(dt_cl)
    return dt_cl.strftime(f"%d/%m/%Y %H:%M:%S (Chile / {offset})")


def format_chile_time_only(dt_val: Union[datetime, str, float, int, None], default_str: str = "N/A") -> str:
    """
    Retorna solo la hora en formato 'HH:MM:SS'.
    """
    dt_cl = utc_to_chile(dt_val)
    if dt_cl is None:
        return default_str
    return dt_cl.strftime("%H:%M:%S")


def format_dual_tz(dt_val: Union[datetime, str, float, int, None], default_str: str = "N/A") -> str:
    """
    Retorna visualización dual: '11:30:00 (Chile UTC-3) | 14:30:00 (UTC)'.
    """
    dt = parse_datetime(dt_val, default_tz=UTC_TZ)
    if dt is None:
        return default_str
    dt_utc = dt.astimezone(UTC_TZ)
    dt_cl = dt.astimezone(CHILE_TZ)
    offset = get_chile_offset_str(dt_cl)
    return f"{dt_cl.strftime('%H:%M:%S')} (Chile {offset}) | {dt_utc.strftime('%H:%M:%S')} (UTC)"


def get_chile_offset_str(dt: Optional[datetime] = None) -> str:
    """
    Retorna el offset UTC de Chile (ej: 'UTC-3' o 'UTC-4') según la fecha/hora actual o indicada.
    """
    if dt is None:
        dt = now_chile()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=CHILE_TZ)
    else:
        dt = dt.astimezone(CHILE_TZ)

    offset_delta = dt.utcoffset()
    if offset_delta is None:
        return "UTC-3"
    total_seconds = int(offset_delta.total_seconds())
    hours = total_seconds // 3600
    minutes = abs(total_seconds % 3600) // 60
    if minutes:
        return f"UTC{hours:+d}:{minutes:02d}"
    return f"UTC{hours:+d}"


def get_chile_day_range_in_utc(target_date: Optional[date] = None) -> Tuple[datetime, datetime]:
    """
    Calcula el rango [start_utc, end_utc] correspondiente al día en Chile (00:00:00 a 23:59:59.999999).
    Esencial para filtros SQL 'Hoy' en base de datos que almacena UTC.
    """
    if target_date is None:
        target_date = now_chile().date()

    start_cl = datetime.combine(target_date, time.min, tzinfo=CHILE_TZ)
    end_cl = datetime.combine(target_date, time.max, tzinfo=CHILE_TZ)

    start_utc = start_cl.astimezone(UTC_TZ)
    end_utc = end_cl.astimezone(UTC_TZ)
    return start_utc, end_utc


def get_active_hours_info(start_utc: int = 13, end_utc: int = 17) -> Dict[str, Any]:
    """
    Convierte las horas activas configuradas en UTC (ej. 13-17) a horario de Chile,
    e indica si en este momento el mercado se encuentra en la ventana activa.
    """
    now_cl = now_chile()
    now_u = now_utc()
    offset_str = get_chile_offset_str(now_cl)

    # Calcular offset numérico en horas
    offset_delta = now_cl.utcoffset()
    offset_hours = int(offset_delta.total_seconds() // 3600) if offset_delta else -3
    start_cl = (start_utc + offset_hours) % 24
    end_cl = (end_utc + offset_hours) % 24

    curr_u_hour = now_u.hour
    if start_utc < end_utc:
        is_active = start_utc <= curr_u_hour < end_utc
    else:
        is_active = (curr_u_hour >= start_utc) or (curr_u_hour < end_utc)

    return {
        "start_utc": start_utc,
        "end_utc": end_utc,
        "start_chile": start_cl,
        "end_chile": end_cl,
        "offset_str": offset_str,
        "offset_hours": offset_hours,
        "is_active_now": is_active,
        "current_chile_str": now_cl.strftime("%H:%M:%S"),
        "current_utc_str": now_u.strftime("%H:%M:%S"),
        "current_chile_full": now_cl.strftime("%Y-%m-%d %H:%M:%S"),
        "active_range_chile": f"{start_cl:02d}:00 - {end_cl:02d}:00 (Chile)",
        "active_range_utc": f"{start_utc:02d}:00 - {end_utc:02d}:00 (UTC)",
    }


def explain_schedule_message(start_utc: int = 13, end_utc: int = 17) -> str:
    """
    Genera un mensaje explicativo y didáctico sobre los horarios en Chile y UTC para Telegram o informes.
    """
    info = get_active_hours_info(start_utc, end_utc)
    status_emoji = "🟢 <b>ACTIVA (Alta Volatilidad / 1m)</b>" if info["is_active_now"] else "⏸️ <b>PASIVA (Normal / 5m)</b>"

    msg = (
        "🕒 <b>Conversor y Monitor de Horarios (Chile ⇄ UTC)</b>\n\n"
        f"• 🇨🇱 <b>Hora Actual Chile:</b> <code>{info['current_chile_full']}</code> ({info['offset_str']})\n"
        f"• 🌐 <b>Hora Actual Servidores (UTC):</b> <code>{info['current_utc_str']} UTC</code>\n\n"
        "⚡ <b>Ventana de Mayor Volatilidad de Mercado:</b>\n"
        f"• <b>Horario Chile:</b> <code>{info['active_range_chile']}</code>\n"
        f"• <b>Horario UTC:</b> <code>{info['active_range_utc']}</code>\n"
        f"• <b>Estado en este momento:</b> {status_emoji}\n\n"
        "💡 <b>¿Por qué existe esta diferencia?</b>\n"
        f"Binance, CCXT y los exchanges internacionales operan con horario estándar global (UTC). "
        f"Chile se ubica en <b>{info['offset_str']}</b>, por lo que las operaciones de las 13:00 UTC ocurren exactamente a las {info['start_chile']:02d}:00 hora de Santiago.\n\n"
        "<i>Todos los informes, mensajes de Telegram, cierres de posiciones y paneles del bot ahora se visualizan en tu hora local chilena.</i>"
    )
    return msg


if __name__ == "__main__":
    print("=" * 60)
    print("🕒 CONVERSOR DE HORARIOS CHILE (America/Santiago) & UTC")
    print("=" * 60)
    info = get_active_hours_info(13, 17)
    print(f"Hora Actual Chile:   {info['current_chile_full']} ({info['offset_str']})")
    print(f"Hora Actual UTC:     {info['current_utc_str']} UTC")
    print(f"Ventana Activa (CL): {info['active_range_chile']}")
    print(f"Ventana Activa (UTC):{info['active_range_utc']}")
    print(f"Estado Actual:       {'ACTIVO (1m)' if info['is_active_now'] else 'PASIVO (5m)'}")
    print("=" * 60)
