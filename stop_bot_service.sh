#!/usr/bin/env bash
SESSION_NAME="bot"
BOT_DIR="/home/shifu/tredding-agent"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "💾 Sincronizando estado final de base de datos desde RAM a disco..."
    if [ -f "${BOT_DIR}/.venv/bin/python" ] && [ -f "${BOT_DIR}/scripts/sync_db_ram_to_disk.py" ]; then
        "${BOT_DIR}/.venv/bin/python" "${BOT_DIR}/scripts/sync_db_ram_to_disk.py" || true
    fi
    echo "🛑 Deteniendo sesión tmux '${SESSION_NAME}'..."
    tmux kill-session -t "${SESSION_NAME}"
    echo "✅ Sesión tmux '${SESSION_NAME}' detenida."
else
    echo "ℹ️ La sesión tmux '${SESSION_NAME}' no estaba en ejecución."
fi

