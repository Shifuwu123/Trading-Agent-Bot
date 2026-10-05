import os
import re
import csv
from datetime import datetime
from pathlib import Path
from tradingbot.core.config import get_settings

# Configurar directorio de logs
settings = get_settings()
# El directorio principal del proyecto dentro de los logs
PROJECT_LOG_DIR = os.path.join(getattr(settings, "base_log_dir", str(Path.home() / ".log")), "Tredding Agent")

# Crear los directorios si no existen
Path(PROJECT_LOG_DIR).mkdir(parents=True, exist_ok=True)

# Definir rutas de los archivos CSV
LOG_GENERAL_PATH = os.path.join(PROJECT_LOG_DIR, "log_general.csv")
LOG_ERRORES_PATH = os.path.join(PROJECT_LOG_DIR, "log_errores.csv")
LOG_REPORTES_PATH = os.path.join(PROJECT_LOG_DIR, "log_reportes.csv")

def _initialize_csv(filepath):
    """Crea el archivo CSV con encabezados si no existe"""
    if not os.path.exists(filepath):
        with open(filepath, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Tipo_Registro", "Descripcion"])

# Inicializar los 3 archivos
_initialize_csv(LOG_GENERAL_PATH)
_initialize_csv(LOG_ERRORES_PATH)
_initialize_csv(LOG_REPORTES_PATH)

_TELEGRAM_TOKEN_REGEX = re.compile(r'\b\d{6,13}:[A-Za-z0-9_-]{30,50}\b')
_TELEGRAM_BOT_URL_REGEX = re.compile(r'bot(\d{6,13}:[A-Za-z0-9_-]{30,50})')
_GITHUB_TOKEN_REGEX = re.compile(r'ghp_[A-Za-z0-9]{36}')
_GENERIC_BEARER_REGEX = re.compile(r'(Bearer\s+)[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE)

def sanitize_sensitive_data(text: str) -> str:
    """
    Sanitiza cadenas de texto para evitar que credenciales sensibles
    (Tokens de Telegram, API Keys, Passwords, etc.) queden expuestas en logs o alertas.
    """
    if not text or not isinstance(text, str):
        return str(text) if text is not None else ""

    # 1. Enmascarar patrones de tokens vía expresiones regulares
    sanitized = _TELEGRAM_BOT_URL_REGEX.sub(r'bot***REDACTED_TELEGRAM_TOKEN***', text)
    sanitized = _TELEGRAM_TOKEN_REGEX.sub(r'***REDACTED_TELEGRAM_TOKEN***', sanitized)
    sanitized = _GITHUB_TOKEN_REGEX.sub(r'***REDACTED_GITHUB_TOKEN***', sanitized)
    sanitized = _GENERIC_BEARER_REGEX.sub(r'\1***REDACTED_TOKEN***', sanitized)

    # 2. Enmascarar valores específicos definidos en configuración o variables de entorno
    try:
        secret_keys = [
            getattr(settings, 'telegram_bot_token', None),
            getattr(settings, 'exchange_api_key', None),
            getattr(settings, 'exchange_api_secret', None),
            os.getenv('SMTP_PASSWORD', None),
            os.getenv('EXCHANGE_API_SECRET', None),
            os.getenv('TELEGRAM_BOT_TOKEN', None),
        ]
        for secret in secret_keys:
            if secret and isinstance(secret, str) and len(secret.strip()) >= 5:
                sanitized = sanitized.replace(secret.strip(), '***REDACTED***')
    except Exception:
        pass

    return sanitized

def registrar_log(tipo_registro: str, descripcion: str):
    """
    Registra un evento en los logs CSV de forma sanitizada.
    También imprime en consola para facilitar el debugging cuando se corre 'CON TERMINAL'.
    """
    safe_desc = sanitize_sensitive_data(descripcion)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, tipo_registro.upper(), safe_desc]
    
    # Imprimir a consola
    print(f"[{timestamp}] [{tipo_registro.upper()}] {safe_desc}")
    
    # Guardar en log_general siempre
    with open(LOG_GENERAL_PATH, mode='a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(row)
        
    # Guardar en archivos específicos
    if tipo_registro.upper() == "ERROR":
        with open(LOG_ERRORES_PATH, mode='a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row)
    elif tipo_registro.upper() == "REPORTE":
        with open(LOG_REPORTES_PATH, mode='a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row)

# Mantenemos un objeto falso `log` por compatibilidad hacia atrás en partes que usan log.info, log.error
class LegacyLogger:
    def debug(self, msg): registrar_log("DEBUG", msg)
    def info(self, msg): registrar_log("INFO", msg)
    def warning(self, msg): registrar_log("WARNING", msg)
    def error(self, msg): registrar_log("ERROR", msg)

log = LegacyLogger()
