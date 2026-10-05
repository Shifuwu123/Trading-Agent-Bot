# 🤖 Tredding Agent Bot

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Asyncio](https://img.shields.io/badge/framework-asyncio-orange.svg)](https://docs.python.org/3/library/asyncio.html)
[![CCXT](https://img.shields.io/badge/exchange-CCXT-informational.svg)](https://github.com/ccxt/ccxt)
[![Telegram UI](https://img.shields.io/badge/interface-Telegram_Bot-2CA5E0.svg)](https://telegram.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Un sistema de **Trading Algorítmico Cuantitativo y Multi-Agente** asíncrono de alto rendimiento para criptomonedas, con conexión modular a exchanges vía CCXT, gestión estricta de riesgo y control remoto bidireccional mediante interfaz interactiva en Telegram.

---

## 📋 Tabla de Contenidos

- [Características Principales](#-características-principales)
- [Arquitectura del Sistema](#-arquitectura-del-sistema)
- [Requisitos Previos](#-requisitos-previos)
- [Instalación Paso a Paso](#-instalación-paso-a-paso)
- [Configuración](#-configuración)
  - [Variables de Entorno (`.env`)](#variables-de-entorno-env)
  - [Configuración de Estrategias y Agentes](#configuración-de-estrategias-y-agentes)
- [Ejecución](#-ejecución)
  - [Modo Multi-Agente (Recomendado)](#1-modo-multi-agente-recomendado)
  - [Servicio Continuo 24/7 (tmux)](#2-servicio-continuo-247-en-segundo-plano)
  - [Modo Legacy y Modo Test](#3-modo-legacy-y-modo-test)
- [Control Remoto vía Telegram](#-control-remoto-vía-telegram)
  - [Comandos Disponibles](#comandos-disponibles)
  - [Teclados Interactivos](#teclados-interactivos-inline)
- [Gestión de Riesgo y Portafolio](#-gestión-de-riesgo-y-portafolio)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Seguridad](#-seguridad)
- [Solución de Problemas (FAQ)](#-solución-de-problemas-faq)

---

## 🚀 Características Principales

- **Arquitectura Multi-Agente Concurrente:** 4 sub-agentes independientes operando en paralelo con diferentes horizontes temporales y perfiles de riesgo:
  - ⚡ **Scalper (Tier 1):** Captura micro-volatilidad en velas de 1 minuto (RSI + MACD + filtro ATR).
  - 🚀 **Momentum (Tier 2):** Identifica rupturas y tendencias en 5m/15m con confirmación de volumen.
  - 🐋 **MacroTrader (BTC/ETH):** Sigue la tendencia mayor en temporalidad de 1 hora para activos clave.
  - ⚠️ **Speculative (Tier 3):** Detección oportunista de rebotes y picos de volatilidad en tokens seleccionados.
- **Conector de Mercado Resiliente (CCXT):** Conexión robusta a Binance (Testnet y Live), con reconexión exponencial automática, caché offline para caídas de red y timeout adaptativo.
- **Gestión Estricta de Capital & Paper Trading:** 
  - Simulación completa en billetera aislada (Paper Trading sin riesgo de dinero real).
  - **Fondo de Reserva Intocable:** 30% del capital protegido permanentemente contra liquidaciones o caídas sistémicas.
  - Asignación inteligente por slot: `(Capital Operativo * 0.70) / max_open_positions`.
- **Centro de Comando Telegram Interactivo:** Control total desde tu móvil con botones inline, confirmación de órdenes en 2 pasos con expiración a los 30s, métricas financieras en tiempo real y conversión automática USD a CLP.
- **Persistencia Asíncrona (SQLite + WAL):** Base de datos optimizada en modo Write-Ahead Logging con SQLAlchemy y aiosqlite, evitando bloqueos entre procesos concurrentes.

---

## 🧠 Arquitectura del Sistema

```
                  ┌────────────────────────────────────────┐
                  │          Telegram Bot Center           │
                  │   (Menús interactivos, alertas, cmds)  │
                  └──────────────────┬─────────────────────┘
                                     │
                  ┌──────────────────▼─────────────────────┐
                  │            OrchestratorBot             │
                  │   (Coordinador del ciclo asíncrono)    │
                  └───────┬──────────┬──────────┬──────────┘
                          │          │          │
         ┌────────────────┴─┐ ┌──────┴──────┐ ┌─┴────────────────┐
         │   Scalper (1m)   │ │Momentum (5m)│ │ MacroTrader (1h) │
         │   (Sub-Agente)   │ │(Sub-Agente) │ │   (Sub-Agente)   │
         └────────────────┬─┘ └──────┬──────┘ └─┬────────────────┘
                          │          │          │
                  ┌───────▼──────────▼──────────▼──────────┐
                  │            PortfolioManager            │
                  │  (Billetera, slots, PnL, Fondo 30%)    │
                  └──────────────────┬─────────────────────┘
                                     │
                  ┌──────────────────▼─────────────────────┐
                  │         CCXT Resilient Connector       │
                  │        (Binance API / Testnet)         │
                  └────────────────────────────────────────┘
```

---

## 🛠️ Requisitos Previos

- **Sistema Operativo:** Linux (Ubuntu 20.04+, Debian 11+, Raspberry Pi OS 64-bit) o macOS.
- **Python:** Versión `3.10` o superior instalada.
- **Git:** Para control de versiones.
- **Tmux:** (Opcional, pero recomendado para ejecución 24/7).
- **Cuenta de Telegram:** Para crear el bot de control mediante `@BotFather`.
- **Cuenta de Binance:** Con API Key generada (puedes usar **Binance Testnet** para pruebas sin dinero real).

---

## 📥 Instalación Paso a Paso

### 1. Clonar el repositorio

```bash
git clone https://github.com/Shifuwu123/Trading-Agent-Bot.git
cd Trading-Agent-Bot
```

### 2. Crear y activar el entorno virtual de Python

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar las dependencias del proyecto

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ Configuración

### Variables de Entorno (`.env`)

Copia la plantilla de ejemplo para crear tu archivo `.env`:

```bash
cp .env.example .env
```

Abre `.env` con tu editor de texto favorito (ej. `nano .env`) y completa tus credenciales:

```env
# --- Conexión al Exchange (CCXT) ---
EXCHANGE_ID=binance
EXCHANGE_API_KEY=tu_api_key_aqui
EXCHANGE_API_SECRET=tu_api_secret_aqui
EXCHANGE_TESTNET=true                  # 'true' para Testnet, 'false' para fondos reales

# --- Control y Notificaciones por Telegram ---
TELEGRAM_BOT_TOKEN=123456789:ABCdef... # Obtenido de @BotFather
TELEGRAM_CHAT_ID=987654321             # Tu Chat ID numérico (ej. de @userinfobot)

# --- Base de Datos y Modo de Ejecución ---
DATABASE_URL=sqlite:///tradingbot.db
PAPER_TRADING=true                     # 'true' para operar en simulación virtual
LOG_LEVEL=INFO
```

> [!WARNING]
> **Seguridad Crítica:** Nunca subas tu archivo `.env` a GitHub ni lo compartas. El archivo `.gitignore` del proyecto ya viene configurado para proteger automáticamente tus secretos.

### Configuración de Estrategias y Agentes

- **`config.yaml`**: Parámetros globales de la aplicación (límites de Stop Loss diario, timeouts de órdenes, lista de pares generales).
- **`configs/agent_scalper.yaml`**: Parámetros del agente Scalper (RSI, ATR, umbrales de Take Profit rápido).
- **`configs/agent_momentum.yaml`**: Configuración de cruces de medias, filtros de volumen y trailing stops para Momentum.
- **`configs/agent_macro.yaml`**: Estrategia de tendencia mayor para Bitcoin y Ethereum.
- **`configs/agent_speculative.yaml`**: Monitoreo de activos de alta volatilidad.

---

## 💻 Ejecución

Asegúrate de tener el entorno virtual activado antes de ejecutar (`source .venv/bin/activate`).

### 1. Modo Multi-Agente (Recomendado)

Inicia el orquestador principal con todos los agentes activos y el listener de Telegram:

```bash
python main.py
```

### 2. Servicio Continuo 24/7 en Segundo Plano

Para mantener el bot corriendo sin interrupciones incluso si cierras tu sesión SSH o tu terminal:

**Iniciar en sesión tmux aislada:**
```bash
./start_bot_service.sh
```

**Ver los logs en vivo:**
```bash
tmux attach -t bot
```
*(Para salir de la vista sin detener el bot, presiona `Ctrl + B` y luego la tecla `D`).*

**Detener el servicio:**
```bash
./stop_bot_service.sh
```

### 3. Modo Legacy y Modo Test

- **Modo Test (sin órdenes reales ni conexión):**
  ```bash
  python main.py --test
  ```
- **Modo Legacy (monolítico anterior de un solo agente):**
  ```bash
  python main.py --legacy
  ```

---

## 📱 Control Remoto vía Telegram

El bot incluye un listener interactivo que solo responderá a los mensajes del `TELEGRAM_CHAT_ID` configurado.

### Comandos Disponibles

| Comando | Descripción |
|---|---|
| `/status` | Muestra el estado global, capital actual (USD/CLP) y resumen de agentes. |
| `/wallet` (o `/billetera`) | Lista el saldo disponible, activos retenidos y posiciones abiertas. |
| `/cashflow` | Reporte financiero de depósitos, retiros y rendimiento neto (ROI). |
| `/reset_pnl` | Archiva trades pasados y reinicia el contador de PnL a $0.00 USD. |
| `/stats [horas]` | Métricas de decisiones (HOLD, BUY, SELL, BLOCKED) en las últimas horas o hoy. |
| `/why_block` | Diagnóstico de las últimas 10 operaciones bloqueadas por las reglas de riesgo. |
| `/mode [trend\|target\|scalper]` | Consulta o modifica la política de toma de beneficios y salidas. |
| `/buy <PAR> <CANTIDAD>` | Solicita compra manual (ej: `/buy BTC/USDT 0.005`) con confirmación interactiva. |
| `/sell <PAR> <CANTIDAD>` | Solicita venta manual verificando el saldo disponible en billetera. |
| `/pause` / `/resume` | Pausa o reanuda la toma de decisiones global del bot. |
| `/status_<agente>` | Consulta el estado detallado de un agente (`scalper`, `momentum`, `macro`, `speculative`). |
| `/pause_<agente>` | Pausa individualmente a un agente sin afectar a los demás. |
| `/resume_<agente>` | Reactiva individualmente a un agente. |

### Teclados Interactivos (Inline)

Todas las respuestas principales incluyen botones táctiles:
- **Navegación Fluida:** Alterna entre Estado, Flujo de Caja, Billetera y Métricas con un solo toque.
- **Inspección de Agentes:** Entra al detalle de cada sub-agente (`Scalper T1`, `Momentum T2`, etc.) y contrólalos individualmente.
- **Protección Antierror:** Las órdenes manuales muestran un teclado con confirmación (`✅ Confirmar` / `❌ Cancelar`) con un límite de tiempo de 30 segundos.

---

## 🛡️ Gestión de Riesgo y Portafolio

1. **Protección de Reserva (30%):** El 30% del balance de la cuenta está estrictamente bloqueado. El motor de trading calcula el tamaño de las posiciones exclusivamente sobre el 70% restante.
2. **Dimensionamiento por Slots:** Si tienes configurado un máximo de 10 posiciones simultáneas, cada posición utilizará como máximo un 10% del capital operativo disponible.
3. **Stop Loss y Take Profit Dinámicos:**
   - **Trend Mode:** Corta pérdidas rápidamente al tocar el umbral de Stop Loss (-2%).
   - **Target Mode:** Mantiene la posición hasta alcanzar el objetivo de ganancia preestablecido.
   - **Scalper Mode:** Cierres ultrarrápidos al alcanzar micro-beneficios (+0.5%).
4. **Freno de Emergencia Diario:** Si las pérdidas acumuladas en el día alcanzan el límite configurado (ej. 5%), el bot bloquea nuevas compras de forma preventiva.

---

## 📂 Estructura del Proyecto

```text
├── agents/                   # Lógica especializada de los sub-agentes
│   ├── base_agent.py         # Clase base abstracta de agentes
│   ├── macro_agent.py        # Agente de tendencia 1h
│   ├── momentum_agent.py     # Agente de momentum 5m/15m
│   ├── scalper_agent.py      # Agente de micro-volatilidad 1m
│   └── speculative_agent.py  # Agente para activos de alta volatilidad
├── configs/                  # Archivos YAML de configuración por agente
├── tradingbot/
│   ├── core/
│   │   ├── orchestrator.py   # Orquestador del ciclo multi-agente
│   │   ├── bot.py            # Motor principal del bot
│   │   └── config.py         # Validador de esquemas Pydantic
│   ├── database/             # Modelos SQLAlchemy y esquemas de base de datos
│   ├── engine/
│   │   ├── trade_engine.py   # Motor de ejecución y reglas
│   │   └── risk_manager.py   # Gestor de límites y slots de riesgo
│   ├── execution/
│   │   └── portfolio_manager.py # Billetera, PnL y cashflow contable
│   ├── interfaces/telegram/  # Listener, teclados interactivos y notificador
│   ├── market/               # Conectores CCXT y recolectores de velas
│   └── utils/                # Registros, conversor CLP y utilidades
├── scripts/                  # Scripts de mantenimiento y utilidades
├── tests/                    # Suite de pruebas unitarias y de integración
├── main.py                   # Punto de entrada principal
├── start_bot_service.sh      # Script de arranque 24/7 en tmux
├── stop_bot_service.sh       # Script de parada ordenada
├── requirements.txt          # Dependencias fijadas del proyecto
└── .env.example              # Plantilla segura de variables de entorno
```

---

## 🔒 Seguridad y Buenas Prácticas

- **Exclusiones de Git:** Archivos sensibles (`.env`, `*.db`, logs, reportes y carpetas virtuales) están rigurosamente ignorados por el `.gitignore` del proyecto.
- **Sanitización de Logs:** Los logs enmascaran automáticamente cualquier cadena que coincida con tokens de Telegram o API Keys de exchanges.
- **Acceso Restringido en Telegram:** Cualquier usuario de Telegram no registrado en tu `TELEGRAM_CHAT_ID` recibirá un mensaje de acceso denegado y el bot descartará sus solicitudes.

---

## ❓ Solución de Problemas (FAQ)

### ¿Cómo verificar que el bot está operando?
Usa el comando `/status` en Telegram o revisa la sesión tmux con:
```bash
tmux attach -t bot
```

### ¿Qué significa que una operación esté en "BLOCKED"?
Puedes ejecutar `/why_block` en Telegram. Las causas más comunes son:
- No hay fondos disponibles en el slot asignado.
- El par ya tiene una posición abierta y no permite recompras (DCA).
- El mercado se encuentra fuera de horario de volatilidad permitida según la configuración del agente.

### ¿Cómo resetear las ganancias históricas para iniciar una nueva prueba?
Usa el comando `/reset_pnl` en Telegram o presiona el botón **🧹 Reiniciar PnL** en la sección de Flujo de Caja. Tus posiciones abiertas y fondos actuales se mantendrán intactos.

---

## 📄 Licencia

Este proyecto está bajo la Licencia [MIT](LICENSE). Puedes usarlo, modificarlo y adaptarlo a tus necesidades.
