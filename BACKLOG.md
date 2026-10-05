# Product Design Document (PDD) / Backlog

Este documento actúa como la hoja de ruta y backlog oficial del Tredding Agent Bot para el desarrollo futuro.

## 🚀 Nuevas Arquitecturas y Expansiones

### 1. Sistema Multi-Arquitectura (Micro y Macro Transacciones Simultáneas)
- **Descripción**: Actualmente el bot soporta operar en 3 modos (`trend`, `target`, `scalper`), pero solo 1 a la vez. El objetivo a futuro es desarrollar un motor "Multi-Arquitectura" que permita operar simultáneamente múltiples estrategias utilizando clases derivadas.
- **Estrategias Investigadas (Fase 9)**: 
  - *Statistical Arbitrage & Mean Reversion*: Operar con Bandas de Bollinger, RSI, y Z-Score.
  - *Momentum Breakout*: Filtros direccionales usando MACD, ADX y Volumen Relativo.
- **Justificación**: Maximiza las oportunidades del mercado y diversifica el riesgo. Permite tener sub-bots dentro del bot general corriendo en paralelo.
- **Estado**: En Backlog. (La teoría matemática ya está redactada en Obsidian).

### 2. Integración Forex (USD/CLP, EUR/USD, etc)
- **Descripción**: Expandir el ecosistema del bot para que no solo opere criptomonedas, sino que pueda leer gráficos y ejecutar operaciones en mercados fiduciarios tradicionales (Forex), específicamente atacando pares estables como **USD/CLP**.
- **Justificación**: El mercado de divisas fiduciarias ofrece tendencias mucho más estables y macroeconómicas. Integrar brokers de Forex (Ej. OANDA, MetaTrader, Interactive Brokers) o consumir APIs de divisas permitiría al bot capitalizar el constante cambio de valor del Dólar contra el Peso Chileno u otras monedas duras.
- **Requisitos Técnicos**: 
  - Integrar una nueva librería o conector API que soporte Forex (CCXT es exclusivo de Cripto).
  - Adaptar los cálculos de "Tamaño de Posición" ya que Forex usa Lotes y Apalancamiento en vez de cantidad nominal.
- **Estado**: En Backlog.

## 🛠️ Deuda Técnica (Tech Debt - Post Auditoría)

Durante la auditoría de agentes, se encontraron las siguientes áreas críticas que requieren refactorización inmediata (Fase 8):

### 1. Cuellos de Botella y Rendimiento (Arquitectura y BD)
- **Problema**: El ciclo principal de `bot.py` bloquea el motor asíncrono (`asyncio`) al hacer llamadas de I/O síncronas a la base de datos (SQLAlchemy).
- **Solución**: Migrar SQLite a `aiosqlite` y `sqlalchemy.ext.asyncio`. Implementar *Locks* lógicos para evitar errores `database is locked` bajo concurrencia.

### 2. Seguridad y Fugas de Datos
- **Problema**: El logger actual en CSV guarda datos crudos. Si el bot crashea y escupe variables de entorno en el Traceback, las credenciales reales quedan escritas en un CSV de texto plano.
- **Solución**: Migrar al módulo estándar `logging` de Python e implementar un Masker/Sanitizer que censure automáticamente tokens (como `TELEGRAM_BOT_TOKEN`) antes de escribirlos.

### 3. Precisión Contable y Finanzas
- **Problema**: El `portfolio_manager.py` prohíbe que el inventario baje de cero, lo que destruye el seguimiento de operaciones en corto (Shorts). Además, el cálculo de ROI ignora el Unrealized PnL.
- **Solución**: Reescribir la función `_update_portfolio_entry` para soportar inventario negativo, y recalcular el ROI utilizando precios de mercado en tiempo real para las posiciones abiertas.

### 4. Usabilidad Telegram UI
- **Problema**: Depender únicamente de escribir comandos es torpe y propenso a errores. El `parse_mode="Markdown"` actual es muy frágil ante caracteres especiales.
- **Solución**: Migrar todas las respuestas a HTML e incorporar Botones de Telegram (`InlineKeyboardMarkup`) para confirmaciones visuales e interfaces interactivas.
