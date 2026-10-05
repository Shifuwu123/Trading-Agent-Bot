#!/usr/bin/env bash
# Script de inicio robusto para Tredding Agent Bot (servicio 24/7 en tmux)

SESSION_NAME="bot"
BOT_DIR="/home/shifu/tredding-agent"
VENV_PYTHON="${BOT_DIR}/.venv/bin/python"

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

echo "🚀 Iniciando Trading Bot en sesión tmux '${SESSION_NAME}'..."
tmux new-session -d -s "${SESSION_NAME}" "bash -c 'cd ${BOT_DIR} && ${VENV_PYTHON} main.py; echo \"[TradingBot finalizado con código \$?]\"; exec bash'"

sleep 2
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "✅ Trading Bot iniciado exitosamente en tmux '${SESSION_NAME}'."
    exit 0
else
    echo "❌ Error al iniciar la sesión tmux '${SESSION_NAME}'."
    exit 1
fi
