#!/usr/bin/env bash
# Script de parada segura y ordenada para Tredding Agent Bot

SESSION_NAME="bot"
BOT_DIR="/home/shifu/tredding-agent"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "🛑 Enviando señal de apagado ordenado al proceso de Trading Bot..."
    # Buscar PID de main.py
    BOT_PID=$(pgrep -f "${BOT_DIR}/main.py" 2>/dev/null | head -n 1)
    if [ -n "${BOT_PID}" ]; then
        kill -SIGINT "${BOT_PID}" 2>/dev/null || true
        # Esperar hasta 5 segundos para que los handlers atexit/señales guarden en disco
        for i in {1..5}; do
            if ! kill -0 "${BOT_PID}" 2>/dev/null; then
                echo "💾 Proceso guardó el estado en disco y finalizó limpiamente."
                break
            fi
            sleep 1
        done
    fi

    echo "💾 Ejecutando verificación de sincronización final RAM -> Disco..."
    if [ -f "${BOT_DIR}/.venv/bin/python" ] && [ -f "${BOT_DIR}/scripts/sync_db_ram_to_disk.py" ]; then
        "${BOT_DIR}/.venv/bin/python" "${BOT_DIR}/scripts/sync_db_ram_to_disk.py" || true
    fi

    echo "🛑 Cerrando sesión tmux '${SESSION_NAME}'..."
    tmux kill-session -t "${SESSION_NAME}" 2>/dev/null || true
    echo "✅ Sesión tmux '${SESSION_NAME}' detenida con éxito."
else
    echo "ℹ️ La sesión tmux '${SESSION_NAME}' no estaba en ejecución."
fi
