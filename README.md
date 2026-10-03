# Tredding Agent Bot

Un agente de trading automatizado y asíncrono con interfaz interactiva vía Telegram.

## 🚀 Características
- **Market Connector:** Conexión directa a Binance Testnet mediante CCXT.
- **Estrategia (EMA Crossover):** Estrategia de cruce de medias móviles exponenciales usando pandas nativo.
- **Paper Trading:** Simulación completa con una **Billetera Digital** aislada que lleva la contabilidad precisa sin gastar dinero real.
- **Gestor de Riesgo:** Reglas estrictas de asignación por slot (`(capital * 0.70) / max_open_positions`), protección permanente del 30% como Fondo de Reserva (DCA/emergencias), y Stop Loss máximo por trade (2%) con límite de pérdida diaria (5%).
- **Telegram UI & Cash Flow:** Control total por chat. Comandos de trading (`/buy`, `/sell` con cierre automático de trades coincidentes), cambio de modos (`/mode`), billetera y holdings independientes (`/wallet`, `/billetera`), y contabilidad avanzada (`/cashflow`, `/deposit`, `/expense`).
- **Logger Estructurado:** Reportes históricos en formato CSV (`log_general.csv`, `log_errores.csv`, `log_reportes.csv`).
- **Conversor CLP:** Integración con la API de `mindicador.cl` para traducir tus ganancias de dólares (USD) a pesos chilenos (CLP).

---

## 🛠️ Requisitos e Instalación

1. **Clonar o descargar** este repositorio en tu sistema.
2. **Crear el entorno virtual** e instalar dependencias:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Configurar el entorno (`.env`)**:
   Crea un archivo `.env` en la raíz copiando la estructura de `.env.example`.
   > ⚠️ **IMPORTANTE DE SEGURIDAD**: ¡Nunca expongas tu archivo `.env` ni hagas commit de él! Asegúrate de que exista un archivo `.gitignore` que excluya el `.env` para proteger tus claves API y tokens.
   - Agrega tu `TELEGRAM_BOT_TOKEN` (desde BotFather).
   - Agrega tu `TELEGRAM_CHAT_ID` (para asegurar que solo tú controles el bot).
   - Agrega las credenciales de Binance Testnet (`exchange_api_key`, `exchange_api_secret`).
4. **Configuración de variables (`config.yaml` y `.env`)**: ¡Ambos archivos están completamente comentados línea por línea en su interior para entender qué hace cada variable!
   Puedes ajustar el temporalidad (ej. `1m`, `1h`), las criptomonedas a transar, o el modo de trading (`trading_mode: "trend"` o `"target"`).

---

## 💻 Ejecución y Uso

Dispones de un comando global llamado **`Tredding_Agent_Bot`** instalado en tu sistema.

Simplemente abre una terminal en tu entorno Linux y escribe:
```bash
Tredding_Agent_Bot
```

Se abrirá un menú interactivo (`Zenity`) preguntándote cómo deseas iniciar el bot:
- **0 (SIN TERMINAL):** El bot se ejecutará invisible en segundo plano usando `tmux`. Puedes cerrar la consola.
- **1 (CON TERMINAL):** El bot abrirá tu emulador de terminal nativo y te mostrará los logs en tiempo real.

> **TIP:** Si lanzaste el bot en modo "SIN TERMINAL" y más tarde quieres revisarlo en vivo, simplemente vuelve a ejecutar `Tredding_Agent_Bot` en otra terminal. El sistema detectará que ya está corriendo y te preguntará si deseas "Engancharte" a la sesión.

---

## 🤖 Modos de Operación (Trading Modes)

Puedes alterar el comportamiento (personalidad) del bot modificando `trading_mode` en `config.yaml` o mediante el comando `/mode` en Telegram:

1. **Trend Mode (`trend`)**: *Sigue la tendencia*. Su regla de oro es "Cortar pérdidas rápido". Si el mercado se voltea en contra, el bot aplicará el Stop Loss agresivamente. Excelente en mercados alcistas (Bull Market) para minimizar pérdidas y maximizar ganancias sostenidas.
2. **Target Mode (`target`)**: *Target absoluto*. Nunca vende a pérdida (ignora el Stop Loss y las señales de reversión). Mantiene las monedas compradas hasta que tocan tu ganancia objetivo (Take Profit). Garantiza 100% de operaciones ganadoras al cierre, ideal para mercados laterales, pero puede congelar capital si hay caídas macroeconómicas abruptas.

---

## 🚀 Roadmap Futuro (Fase de Inteligencia Artificial)

El objetivo final del proyecto es evolucionar desde un modelo reactivo (Matemático/EMA) a un **modelo predictivo (Machine Learning & NLP)**. 

**Plan de Escalabilidad:**
1. **Recolección Silenciosa (Actualidad):** Actualmente, el bot está recolectando y guardando miles de velas históricas en tu base de datos local en cada ciclo. Está armando silenciosamente un dataset masivo de entrenamiento sin que tengas que hacer nada.
2. **Financiamiento:** Utilizar las ganancias generadas por la estrategia matemática básica (y el capital simulado validado) para escalar el hardware del servidor (añadiendo una GPU con núcleos CUDA, dado que el i5 y la GT710 actuales no permiten entrenamiento profundo).
3. **Entrenamiento Local:** Inyectar el dataset histórico recolectado en una Red Neuronal (Ej: LSTM) para predecir movimientos de precio, y acoplar un modelo de Análisis de Sentimiento (para leer noticias financieras) que se anticipe a las caídas del mercado.

---

## 🧠 ¿Qué es y qué hace el `run_cycle`?

Si revisas los logs, verás constantemente mensajes del `run_cycle`.

El `run_cycle` es el **corazón y cerebro del bot**. Es un bucle repetitivo (ejecutado por un programador de tareas asíncrono) que funciona como la respiración del sistema. 
El bot se despierta religiosamente cada 60 segundos, pero gracias a los **Timeframes Dinámicos Híbridos**, es sumamente inteligente respecto a cómo gasta ese minuto:

1. **Modo Agresivo (Alta Volatilidad):** Si estamos dentro de las horas activas (ej. 13:00 - 17:00 UTC), descargará velas de `1m` y operará rápido para aprovechar el alto volumen del mercado.
2. **Modo Conservador (Baja Volatilidad):** Si estamos fuera de horario, pasará a modo `5m`. Para evitar falsos positivos (Repainting), el bot mirará la hora en cada ciclo. Si el minuto actual no es múltiplo de 5 (ej. son las 20:03), se volverá a dormir sin procesar datos. Solo operará cuando la vela de 5 minutos esté 100% cerrada (ej. 20:05, 20:10).

El `run_cycle` es la prueba vital de que tu bot está despierto, protegiendo tu capital y esperando el momento matemático exacto para actuar.
