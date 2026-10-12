#!/usr/bin/env bash
# Script de inicio robusto para Tredding Agent Bot (servicio 24/7 en tmux)
# Blindado con Schema Guard, verificación de tablas y fallback a Golden Backup.

SESSION_NAME="bot"
BOT_DIR="/home/shifu/tredding-agent"
VENV_PYTHON="${BOT_DIR}/.venv/bin/python"
RAM_DB="/dev/shm/tradingbot.db"
DISK_DB="${BOT_DIR}/tradingbot.db"
GOLDEN_DB="${BOT_DIR}/tradingbot_golden_backup.db"

cd "${BOT_DIR}" || exit 1

# Si ya existe la sesión tmux 'bot', no duplicar
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "⚠️ La sesión tmux '${SESSION_NAME}' ya se encuentra activa."
    exit 0
fi

# Esperar conexión a red e Internet (vital tras cortes de luz / reinicios de router)
echo "⏳ Verificando conectividad a internet..."
for i in {1..30}; do
    if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1 || curl -s --head https://api.binance.com >/dev/null 2>&1 || curl -s --head https://api.telegram.org >/dev/null 2>&1; then
        echo "🌐 Conexión a internet confirmada."
        break
    fi
    sleep 2
done

# Función auxiliar para validar esquema y trades
verify_db() {
    local target="$1"
    if [ ! -s "${target}" ]; then
        return 1
    fi
    "${VENV_PYTHON}" -c "import sqlite3, sys; c=sqlite3.connect('${target}'); cur=c.cursor(); cur.execute('SELECT 1 FROM trades LIMIT 1'); c.close()" 2>/dev/null
    return $?
}

echo "🔍 Verificando integridad de capas de almacenamiento..."

# 1. Comprobar base activa en RAM
if ! verify_db "${RAM_DB}"; then
    echo "⚠️ Base de datos en RAM (${RAM_DB}) inexistente, vacía o sin esquema."
    
    # 2. Intentar restaurar desde persistente en disco
    if verify_db "${DISK_DB}"; then
        echo "⚡ Restaurando RAM desde disco persistente (${DISK_DB})..."
        cp "${DISK_DB}" "${RAM_DB}" 2>/dev/null || true
    elif verify_db "${GOLDEN_DB}"; then
        echo "🛡️ Restaurando RAM y Disco desde Golden Backup inmutable (${GOLDEN_DB})..."
        cp "${GOLDEN_DB}" "${RAM_DB}" 2>/dev/null || true
        cp "${GOLDEN_DB}" "${DISK_DB}" 2>/dev/null || true
    else
        echo "🚨 ALERTA CRÍTICA: Ninguna base de datos superó la verificación. Ejecutando restaurador de emergencia..."
        "${VENV_PYTHON}" "${BOT_DIR}/scripts/restore_db_golden.py" || true
    fi
else
    echo "✅ Base de datos en RAM verificada con esquema e historial íntegro."
fi

echo "🛡️ Ejecutando Quality Gate pre-deploy (build, lint, tests, migrations)..."
if ! "${BOT_DIR}/scripts/pre_deploy_check.sh"; then
    echo "❌ Quality Gate fallido. Se aborta el despliegue del bot para proteger la operación."
    exit 1
fi

echo "🚀 Iniciando Trading Bot en sesión tmux '${SESSION_NAME}' (Capa RAM activa)..."
tmux new-session -d -s "${SESSION_NAME}" "bash -c 'cd ${BOT_DIR} && ${VENV_PYTHON} main.py; echo \"[TradingBot finalizado con código \$?]\"; exec bash'"

sleep 2
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "✅ Trading Bot iniciado exitosamente en tmux '${SESSION_NAME}'."
    exit 0
else
    echo "❌ Error al iniciar la sesión tmux '${SESSION_NAME}'."
    exit 1
fi
