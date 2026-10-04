# Product Design Document (PDD) / Backlog

Este documento actúa como la hoja de ruta y backlog oficial del Tredding Agent Bot para el desarrollo futuro.

---

## 🚀 Nuevas Arquitecturas y Expansiones (Backlog Futuro)

### 1. Sistema Multi-Arquitectura (Micro y Macro Transacciones Simultáneas)
- **Descripción**: Actualmente el bot soporta operar en 3 modos (`trend`, `target`, `scalper`), pero solo 1 a la vez. El objetivo a futuro es desarrollar un motor "Multi-Arquitectura" que permita operar simultáneamente múltiples estrategias utilizando clases derivadas y un `StrategyRouter`.
- **Estrategias Investigadas (Fase 9)**: 
  - *Statistical Arbitrage & Mean Reversion*: Operar con Bandas de Bollinger, RSI, y Z-Score.
  - *Momentum Breakout*: Filtros direccionales usando MACD, ADX y Volumen Relativo.
- **Justificación**: Maximiza las oportunidades del mercado y diversifica el riesgo. Permite tener sub-bots dentro del bot general corriendo en paralelo con partición de capital por sub-pool.
- **Estado**: En Backlog. (La teoría matemática ya está redactada en Obsidian).

### 2. Integración Forex (USD/CLP, EUR/USD, etc.)
- **Descripción**: Expandir el ecosistema del bot para que no solo opere criptomonedas, sino que pueda leer gráficos y ejecutar operaciones en mercados fiduciarios tradicionales (Forex), específicamente atacando pares estables como **USD/CLP**.
- **Justificación**: El mercado de divisas fiduciarias ofrece tendencias mucho más estables y macroeconómicas. Integrar brokers de Forex (Ej. OANDA, MetaTrader, Interactive Brokers) o consumir APIs de divisas permitiría al bot capitalizar el constante cambio de valor del Dólar contra el Peso Chileno u otras monedas duras.
- **Requisitos Técnicos**: 
  - Integrar una nueva librería o conector API que soporte Forex (CCXT es exclusivo de Cripto).
  - Adaptar los cálculos de "Tamaño de Posición" ya que Forex usa Lotes y Apalancamiento en vez de cantidad nominal.
- **Estado**: En Backlog.

---

## 🛠️ Deuda Técnica Pendiente (Priorizada)

### 1. [Prioridad BAJA] Soporte de Inventario Negativo para Operaciones Cortas (Shorts)
- **Problema**: `_update_portfolio_entry` reinicia el inventario a cero cuando la cantidad vendida iguala o excede el balance, lo cual es ideal para Spot pero imposibilita el seguimiento de ventas en corto (Shorts apalancados en Futuros).
- **Solución Propuesta**:
  - Permitir inventario negativo cuando se habilite el módulo de margen/futuros y calcular PnL según lado activo de la posición.
- **Estado**: Pendiente (requiere habilitar trading con derivados).

---

## ✅ Tareas Resueltas Recientemente

### 1. Migración de SQLite a Motor Asíncrono (`aiosqlite` + `SQLAlchemy Async` + WAL Mode) (Fase 11.7)
- **Solución Implementada**:
  - Se integró `aiosqlite` y `greenlet` con `create_async_engine` y `async_sessionmaker` en `DatabaseSession`.
  - Se habilitó SQLite en modo **WAL (Write-Ahead Logging)** con `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=15000;`, permitiendo lecturas y escrituras simultáneas de múltiples subagentes concurrentes sin bloqueos de tabla (`database is locked`).
  - Se dotó a `PortfolioManager` y `TradeEngine` de corrutinas asíncronas completas (`record_open_trade_async`, `record_close_trade_async`, `update_asset_price_async`, `record_decisions_bulk_async`, `get_cashflow_summary_async`, `get_portfolio_summary_async`).
  - `DataCollector` ahora persiste lotes de velas históricas de forma 100% asíncrona sin bloquear el event loop.

### 2. Confirmación Interactiva de Órdenes Manuales Telegram (`/buy`, `/sell`) (Fase 11.8)
- **Solución Implementada**:
  - Se implementó un flujo interactivo de seguridad para `/buy` y `/sell` mediante teclados inline con botones `[ ✅ Confirmar Compra/Venta ]` y `[ ❌ Cancelar ]`.
  - Las órdenes pendientes se resguardan en memoria con un token temporal y un TTL de 30 segundos; si el usuario no confirma dentro del plazo, expiran automáticamente evitando ejecuciones desfasadas o accidentales.
  - Se implementó `execute_manual_order` en `OrchestratorBot` con conciliación inteligente de trades y asignación al subagente correspondiente.

### 3. Rebalanceo y Reinicio de Billetera Digital a $20.00 USD (Preservación Deep Learning) (Fase 11.9)
- **Solución Implementada**:
  - Se migró el balance base y por defecto de la billetera digital paper trading de 10,000 USD a **$20.00 USD**, reflejando las condiciones operativas de producción.
  - Se recalibró el dimensionamiento de posición en `RiskManager` y `TradeEngine` (`min_order_usd`) para admitir cuentas pequeñas sin pulverizar las órdenes ni violar restricciones mínimas.
  - Se preservó con 100% de integridad todo el histórico de velas (`candles`) y registros de decisiones (`decision_logs`) recolectados para el futuro modelo predictivo de Deep Learning.

### 4. Dimensionamiento de Posición y Fondo de Reserva (Fase 11.1)
- **Solución Implementada**: Se corrigió el cálculo de tamaño de orden en `risk_manager.py` y `trade_engine.py`. Ahora el capital utilizable (descontando el 30% del fondo de reserva) se fracciona equitativamente entre las posiciones máximas configuradas (`max_open_positions`), evitando que una sola orden intente consumir el 100% del saldo y sea bloqueada por exposición.

### 5. Conciliación de Órdenes Manuales Telegram (Fase 11.2)
- **Solución Implementada**: La función `execute_manual_order` en `bot.py` ahora concilia órdenes del lado opuesto. Al ejecutar un `/sell` manual, se cierran formalmente los trades abiertos coincidentes en la base de datos en vez de dejar registros huérfanos con estado `OPEN`.

### 6. Unrealized PnL en Portfolio y Cálculo Integral de ROI (Fase 11.3)
- **Solución Implementada**:
  - Se implementó el cálculo y persistencia en tiempo real de `unrealized_pnl` en el modelo `Portfolio` ante variaciones de posición y en cada ciclo de mercado mediante `update_asset_price()`.
  - La función `get_cashflow_summary()` en `portfolio_manager.py` ahora desglosa con precisión las ganancias realizadas (`realized_pnl`), las ganancias activas flotantes (`unrealized_pnl`), el beneficio total neto y el ROI global considerando tanto el capital liquidado como las posiciones activas abiertas.
  - El detalle de holdings ahora muestra la ganancia/pérdida no realizada por activo.

### 7. Migración de Telegram a HTML y Botones Interactivos Inline (Fase 11.4)
- **Solución Implementada**:
  - Se eliminó completamente la dependencia de Markdown v1 en `telegram_listener.py`, sustituyéndola por **HTML estructurado**, eliminando excepciones y fallos silenciosos por caracteres especiales en pares y precios.
  - Se agregaron **menús con botones interactivos (`InlineKeyboardMarkup` y `CallbackQueryHandler`)**:
    - **Panel de Estado:** Botón de refresco rápido, acceso a flujo de caja, cambio de modos, consulta de bloqueos y botón dinámico para Pausar/Reanudar.
    - **Selector de Modo:** Botones instantáneos para alternar entre `TREND`, `TARGET` y `SCALPER` con un solo toque y persistencia automática en `config.yaml`.
    - **Estadísticas Dinámicas:** Botones para filtrar decisiones entre *Hoy*, *Últimas 6 horas* y *Últimas 24 horas*.
    - **Flujo de Caja:** Botón de actualización inmediata y retorno al panel principal.

### 8. Separación de Flujo de Caja y Billetera Independiente en Telegram (Fase 11.5)
- **Solución Implementada**:
  - Se desacopló la consulta financiera en dos vistas claras e independientes:
    - **Flujo de Caja (`/cashflow`):** Reporte contable puro (capital base, depósitos, retiros, gastos, PnL realizado/activo y ROI) sin mezclar la lista de posiciones.
    - **Billetera (`/wallet` y `/billetera`):** Vista dedicada que detalla el saldo líquido en USDT, PnL flotante consolidado, posiciones activas por criptomoneda y el histórico de ganancias realizadas por símbolo.
  - **Botonera Interactiva:** Se agregó el botón directo `👝 Billetera` al teclado inline principal de `/status`, y botones de navegación cruzada entre Billetera y Flujo de Caja.

### 9. Sanitización de Datos Sensibles, Purga de Secretos y Hardening para Open Source (Fase 11.6)
- **Solución Implementada**:
  - **Purga de Historial Git:** Se eliminó de raíz el archivo de base de datos SQLite histórico (`tradingbot.db.bak`) de todo el historial de commits y objetos Git utilizando `git-filter-repo`, garantizando que ninguna información de billetera, holdings, IDs de chat o trades quede en el historial público.
  - **Protección Git y Plantilla Segura:** Se endureció `.gitignore` con exclusiones completas para cualquier variante de `.env*`, llaves, certificados, backups y bases de datos. Se creó `.env.example` estructurado con placeholders sin credenciales.
  - **Sanitizador en Tiempo Real (`SensitiveDataFilter`):** Se implementó `sanitize_sensitive_data()` en `logger.py` y `notifier.py` para enmascarar automáticamente patrones de tokens de Telegram, tokens de GitHub, tokens Bearer y credenciales del entorno en logs CSV, salida de terminal y alertas críticas por Telegram.

