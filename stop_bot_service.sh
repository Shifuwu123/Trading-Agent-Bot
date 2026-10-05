#!/usr/bin/env bash
SESSION_NAME="bot"
if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "🛑 Deteniendo sesión tmux '${SESSION_NAME}'..."
    tmux kill-session -t "${SESSION_NAME}"
    echo "✅ Sesión tmux '${SESSION_NAME}' detenida."
else
    echo "ℹ️ La sesión tmux '${SESSION_NAME}' no estaba en ejecución."
fi
