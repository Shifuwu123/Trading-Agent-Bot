import os
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

def registrar_log(tipo_registro: str, descripcion: str):
    """
    Registra un evento en los logs CSV.
    También imprime en consola para facilitar el debugging cuando se corre 'CON TERMINAL'.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, tipo_registro.upper(), descripcion]
    
    # Imprimir a consola
    print(f"[{timestamp}] [{tipo_registro.upper()}] {descripcion}")
    
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
