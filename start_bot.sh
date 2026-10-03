#!/bin/bash
# Moverse al directorio del script
cd "$(dirname "$0")"

# Lanzar ventana emergente
CHOICE=$(zenity --list --radiolist \
    --title="TradingBot Launcher" \
    --text="Selecciona el modo de ejecución del bot:" \
    --column="Selección" --column="ID" --column="Modo" \
    FALSE "0" "SIN TERMINAL (Segundo plano silencioso)" \
    TRUE "1" "CON TERMINAL (Ventana visible)" \
    --print-column=2 --hide-column=2 --width=400 --height=200)

if [ "$CHOICE" = "1" ]; then
    # CON TERMINAL
    if command -v alacritty &> /dev/null; then
        alacritty -e bash -c "source .venv/bin/activate && python main.py; exec bash" &
    elif command -v kitty &> /dev/null; then
        kitty bash -c "source .venv/bin/activate && python main.py; exec bash" &
    elif command -v foot &> /dev/null; then
        foot bash -c "source .venv/bin/activate && python main.py; exec bash" &
    else
        # Fallback genérico
        x-terminal-emulator -e bash -c "source .venv/bin/activate && python main.py; exec bash" &
    fi
elif [ "$CHOICE" = "0" ]; then
    # SIN TERMINAL
    # Usar tmux para poder retomarlo después
    if tmux has-session -t tradingbot 2>/dev/null; then
        zenity --info --title="TradingBot" --text="El bot ya está corriendo en segundo plano." --width=300
    else
        tmux new-session -d -s tradingbot "source .venv/bin/activate && python main.py"
        zenity --info --title="TradingBot" --text="✅ El bot se ha iniciado exitosamente en segundo plano (tmux: tradingbot)." --width=350
    fi
fi
