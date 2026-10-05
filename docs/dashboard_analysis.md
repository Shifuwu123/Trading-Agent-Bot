# Análisis Estadístico para Dashboard en Tiempo Real (Fase 12)

Este documento contiene el mapeo de los datos generados por la base de datos `tradingbot.db` hacia el Dashboard web interactivo.

## Orígenes de Datos (SQLite)
1. **Capital y Flujo de Caja (`digital_wallet`, `cash_flow`)**
   - **Indicadores Clave:** Capital disponible, Total invertido (USD/CLP).
   - **Cálculo de PnL y ROI:** Cruce de sumatorias en `cash_flow` (Deposits vs Withdrawals) y `trades` (Ganancias/Pérdidas cerradas).

2. **Portafolio en Vivo (`portfolio`, `trades`)**
   - **Indicadores Clave:** Inventario de criptomonedas compradas, precio promedio de entrada, precio actual y PnL No Realizado (Ganancia/Pérdida flotante).
   - **Objetivo:** Mostrar una grilla actualizada que permita evaluar la salud de cada moneda retenida.

3. **Bitácora de Decisiones (`decision_logs`)**
   - **Indicadores Clave:** Registro milisegundo a milisegundo de las alertas y bloqueos del bot (por límites de exposición o DCA).
   - **Objetivo:** Proveer un componente estilo "Terminal Web" o "Feed" para depuración en vivo sin necesidad de entrar por SSH.

## Arquitectura de Interacción (Botones de Control)
El dashboard no solo será de lectura, sino de escritura controlada. Para evitar problemas de concurrencia en la memoria de Python (el bot corriendo en Tmux y el servidor FastAPI separados), se implementará una tabla intermedia:

- **Tabla `bot_commands` (Nueva)**: 
  - Columnas: `id`, `command`, `args`, `status`, `timestamp`
  - Flujo: El usuario pulsa "Pausar" en el dashboard web. FastAPI inserta `PAUSE` en `bot_commands`. El bot en su ciclo periódico (`TradeEngine`) lee la tabla, ejecuta la orden, y marca el comando como `PROCESSED`.

## Diseño de UI/UX
Se utilizará Vanilla JS con **CSS Moderno (Glassmorphism)**:
- **Tema:** Dark Mode profundo.
- **Micro-interacciones:** Tarjetas que brillan al hover, animaciones suaves al cargar estadísticas y botones de acción rápida responsivos.
- **Responsive:** Adaptabilidad total a pantallas de dispositivos móviles (Smartphones) a través de resoluciones fluidas.
