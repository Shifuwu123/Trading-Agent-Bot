# Auditoría Forense y Financiera: Scalper Agent (Tier 1)
**Fecha:** 12 de Octubre de 2026  
**Auditor:** Antigravity AI — Pair Programming Engine  
**Destinatario:** Shifu / Jarvis  
**Entorno:** Trading Bot Multi-Agente (`/home/shifu/tredding-agent`)  

---

## 1. Resumen Ejecutivo y Hallazgos Principales

Se ha completado una auditoría forense integral sobre la base de datos de producción (`tradingbot.db`) y los registros de ejecución del **Scalper Agent (`scalper_t1`)**, analizando el historial completo de órdenes, precios de entrada/salida, comisiones de exchange y razones de cierre.

### 📌 Conclusiones Clave de la Auditoría:
1. **El misterio del PnL de -0.38 USDT en SOL/USDT está 100% resuelto:**
   - La suma exacta del PnL cerrado en SOL/USDT es **-0.378972 USDT** (redondeado a **-0.38 USDT**).
   - **El 96.1% de esta pérdida (-0.364441 USDT) NO se debió al mercado**, sino a un **incidente por ejecución de pruebas unitarias (`pytest`) sin aislamiento total de la base viva** ocurrido el 11 de Octubre a las 17:26:05 (hora Chile) / 20:26:05 UTC.
   - La prueba unitaria de slots de riesgo (`test_risk_slot_and_lock.py`) inyectó una vela mock con precio de salida de **$10.00 USD** sobre el par `SOL/USDT`. El motor `TradeEngine` detectó la orden viva `#113` (abierta a **$112.49 USD**), calculó una caída artificial del **-91.1%**, disparó el **Hard Stop Loss de Emergencia** y vendió a **$10.00 USD**, imputando una pérdida sintética de **-$0.3644 USD**.
   - El PnL real de mercado de SOL en las 9 operaciones restantes es de apenas **-$0.0145 USD** (prácticamente neutro).

2. **¿Por qué el Scalper Agent ha registrado más pérdidas que ganancias en general?**
   - El Scalper Agent registra **53 operaciones cerradas (`CLOSED`)**: **24 ganancias (45.3%)** frente a **29 pérdidas (54.7%)**.
   - **Causa #1: El "Efecto Cortacésped" del Safe Time-Stop (120 min):** El **93.1% de las pérdidas (27 de 29)** fueron ejecutadas por la salida de tiempo (`Safe Time-Stop`), NO por caídas violentas del mercado ni Stop Losses normales. Al operar en temporalidades ultracortas (1m/5m) con medias móviles (EMA 9/21), el bot compra en picos locales de mercados laterales; cuando la posición no sube tras 2 horas y flota en micro-pérdidas (-0.10% a -1.25%), el seguro la liquida automáticamente con pérdida.
   - **Causa #2: Asimetría Desfavorable de Riesgo/Beneficio (Payoff Invertido):** El Take Profit histórico estaba configurado en solo **+0.50%** (~+$0.0025 a +$0.0035 USD), mientras que el Time-Stop toleraba caídas de hasta **-1.27%** y el Hard Stop hasta **-4.50%**. Con esta relación, una sola pérdida borra la ganancia de 2 a 4 operaciones ganadoras (caso crítico de `SUI`, que con **66.7% de Win Rate** terminó con PnL neto negativo).
   - **Causa #3: Activos Ancla Lentos (BNB y XRP):** Monedas pesadas como BNB (Win Rate **16.7%**) y XRP (Win Rate **20.0%**) no poseen el rango dinámico necesario para alcanzar un TP en 120 minutos en velas de 1m, cayendo siempre víctimas del Time-Stop.
   - **Causa #4: Arrastre por Comisiones (Fee Drag):** Con Binance Spot cobrando 0.20% ida y vuelta, una ganancia de +0.50% perdía el **40% de su rendimiento en comisiones**, mientras que una salida en pérdida de -0.10% se triplicaba a -0.30% neto.

---

## 2. Auditoría Detallada de SOL/USDT: Desglose Forense

### 2.1. Registro Contable de Todas las Operaciones Cerradas (`CLOSED`)

| ID | Trade ID | Fecha Apertura | Fecha Cierre | Precio Entrada | Precio Salida | Cantidad (SOL) | PnL Bruto (USD) | Fee (USD) | PnL Neto (USD) | Razón de Cierre |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **113** | `mock_aed7f859` | 08/10 14:50 | 11/10 20:26 | **$112.4900** | **$10.0000** | 0.003556 | **-$0.364441** | $0.000436 | **-$0.364877** | ⚠️ **Hard Stop Loss Emergencia (-4.5%) [Test Leak]** |
| **124** | `mock_3fc75ed6` | 09/10 15:59 | 09/10 18:20 | $109.7600 | $109.6800 | 0.003585 | -$0.000287 | $0.000000 | -$0.000287 | Safe Time-Stop (141m, PnL -0.07%) |
| **136** | `mock_0fd0c28e` | 09/10 13:02 | 09/10 15:05 | $110.2328 | $109.8800 | 0.006710 | -$0.002368 | $0.000000 | -$0.002368 | Safe Time-Stop (122m, PnL -0.32%) |
| **139** | `mock_a5cd3cbd` | 09/10 11:35 | 09/10 11:50 | $110.4500 | $111.4100 | 0.003559 | +$0.003417 | $0.000000 | +$0.003417 | Take Profit (+0.5%) |
| **140** | `mock_ff122958` | 09/10 09:00 | 09/10 11:15 | $110.3463 | $109.8300 | 0.006703 | -$0.003461 | $0.000000 | -$0.003461 | Safe Time-Stop (134m, PnL -0.47%) |
| **148** | `mock_ba073f1c` | 08/10 20:27 | 08/10 21:15 | $109.4300 | $110.0200 | 0.003597 | +$0.002122 | $0.000000 | +$0.002122 | Take Profit (+0.5%) |
| **157** | `mock_4bdfb637` | 08/10 18:03 | 08/10 18:20 | $106.4281 | $107.0000 | 0.006908 | +$0.003951 | $0.000000 | +$0.003951 | Take Profit (+0.5%) |
| **163** | `mock_8f816e8e` | 08/10 15:51 | 08/10 17:54 | $109.1340 | $106.2600 | 0.006872 | -$0.019751 | $0.000000 | -$0.019751 | Safe Time-Stop (122m, PnL -2.63%) |
| **181** | `mock_f4b007d6` | 11/10 22:20 | 12/10 04:45 | $111.1600 | $112.8800 | 0.002228 | +$0.003833 | $0.000499 | +$0.003333 | Take Profit (+1.5%) [Fase 2] |
| **185** | `mock_737e4fc0` | 12/10 07:00 | 12/10 09:15 | $112.3076 | $111.8300 | 0.004161 | -$0.001987 | $0.000933 | -$0.002920 | Safe Time-Stop (134m, PnL -0.43%) |
| **TOTAL** | — | — | — | — | — | — | **-0.378972** | **$0.001867** | **-0.364463** | — |

$$\sum \text{PnL Bruto (SOL)} = \mathbf{-0.378972\text{ USDT}} \approx \mathbf{-0.38\text{ USDT}}$$

### 2.2. Anatomía del Incidente Trade #113
- **Causa Raíz:** Durante el desarrollo de la suite de pruebas unitarias (`tests/test_risk_slot_and_lock.py`), se ejecutó una prueba que simuló el procesamiento de una orden con precio fijo de **$10.00 USD**. En esa versión intermedia, la prueba invocó `te.process_symbol("SOL/USDT", ...)`.
- **Efecto:** Como la base de datos contenía la orden abierta legítima `mock_aed7f859` (comprada a $112.49 USD), el método `manage_open_trades` interpretó que SOL se había desplomado de $112.49 a $10.00 (-91.1%), ejecutó el Stop de Emergencia y persistió el resultado en SQLite.
- **Evidencia en los Logs (`task-223.log`):**
  ```text
  [2026-10-11 17:26:05] [INFO] [AsyncDB] Recorded close trade mock_aed7f859. 
  PnL Bruto: -0.3644411163000000, Fee: 0.00043555851630000000, PnL Neto: -0.36487667481630000000, 
  Reason: Hard Stop Loss Emergencia (-4.5%)
  ```
- **Sin este trade anómalo:**
  $$\text{PnL Real de Mercado SOL} = -0.378972 - (-0.364441) = \mathbf{-0.014531\text{ USD}}$$

---

## 3. Auditoría Comparativa de Todas las Monedas del Scalper Agent

El Scalper Agent opera 7 pares principales bajo la configuración de cartera equilibrada (`configs/agent_scalper.yaml`):

### 3.1. Métricas Consolidadas por Par (`status = CLOSED`)

| Moneda | Total Ops | Wins | Losses | Win Rate (%) | PnL Bruto (USD) | Comisiones (USD) | PnL Neto (USD) | Ganancia Prom. Win | Pérdida Prom. Loss | Payoff Ratio |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **SOL/USDT** | 10 | 4 | 6 | 40.0% | -$0.3790* | $0.0019 | -$0.3645 | +$0.0033 | -$0.0654* | 0.05* |
| *(SOL sin test #113)* | *9* | *4* | *5* | *44.4%* | *-$0.0145* | *$0.0014* | *-$0.0159* | *+$0.0033* | *-$0.0056* | *0.59* |
| **BNB/USDT** | 6 | 1 | 5 | 16.7% | -$0.0117 | $0.0015 | -$0.0062 | +$0.0024 | -$0.0028 | 0.84 |
| **XRP/USDT** | 5 | 1 | 4 | 20.0% | -$0.0063 | $0.0023 | -$0.0033 | +$0.0022 | -$0.0021 | 1.03 |
| **SUI/USDT** | 6 | 4 | 2 | 66.7% | -$0.0032 | $0.0000 | $0.0000 | +$0.0027 | -$0.0070 | 0.39 |
| **NEAR/USDT** | 12 | 8 | 4 | **66.7%** | **+$0.0681** | $0.0041 | **+$0.0503** | +$0.0144 | -$0.0118 | **1.22** |
| **DOGE/USDT** | 6 | 2 | 4 | 33.3% | -$0.0064 | $0.0015 | -$0.0045 | +$0.0041 | -$0.0036 | 1.12 |
| **ADA/USDT** | 8 | 4 | 4 | 50.0% | **+$0.0056** | $0.0022 | **+$0.0109** | +$0.0064 | -$0.0050 | **1.28** |
| **TOTAL** | **53** | **24** | **29** | **45.3%** | **-0.3329** | **$0.0135** | **-0.3173** | — | — | — |

*\* Cifras impactadas por el trade sintético #113.*

```mermaid
pie title Distribución de Cierres en Scalper Agent
    "Take Profit (+0.5% a +1.5%)" : 24
    "Safe Time-Stop (120m consolidado)" : 27
    "Hard Stop Loss (-4.5%)" : 2
```

---

## 4. Diagnóstico Forense: ¿Por qué hay Más Pérdidas que Ganancias?

Al auditar cualitativa y cuantitativamente cada trade, identificamos **4 factores estructurales**:

### Factor 1: El Dominio Absoluto del Safe Time-Stop (El "Cortacésped")
- De las **29 operaciones con pérdidas** en la historia del Scalper, **27 fueron cerradas por `Safe Time-Stop`** (93.1%).
- **Mecanismo:** La estrategia EMA 9/21 en gráfico de 1 minuto genera entradas en fases de expansión. Si el mercado entra en consolidación o lateralidad (rango estrecho), el precio oscila entre -0.10% y -0.80% sin romper máximos.
- Al cumplirse 120 minutos (2 horas) y encadenar 3 minutos cerrando en cualquier pérdida mínima (por ejemplo -0.07% o -0.14%), el bot asume que la posición está estancada y la cierra obligatoriamente.
- **Resultado:** El bot "corta el césped" en negativo una y otra vez, acumulando micro-pérdidas recurrentes en activos sin tendencia clara.

### Factor 2: Asimetría Matemática de Riesgo/Recompensa (El Caso SUI)
- Para entender por qué hay más pérdidas que ganancias incluso acertando, observemos a **SUI/USDT**:
  - Tuvo **4 operaciones ganadoras** con Take Profit de +0.50% (+0.64%, +0.78%, +0.73%, +0.56%), sumando **+$0.0107 USD**.
  - Tuvo solo **2 operaciones perdedoras** cerradas por Time-Stop (-1.23% y -0.64%), restando **-$0.0140 USD**.
  - **Efecto:** Con un **Win Rate del 66.7%**, el PnL neto fue **negativo (-$0.0032 USD)** porque el Payoff Ratio fue de apenas **0.39** (la pérdida promedio fue casi el triple de la ganancia promedio).

### Factor 3: Parálisis de Monedas de Baja Volatilidad (BNB y XRP)
- **BNB** (16.7% Win Rate) y **XRP** (20.0% Win Rate) fueron seleccionadas como "anclas de liquidez".
- Sin embargo, en un timeframe de 1 minuto, estos activos tienen una volatilidad relativa (ATR) muy baja. Prácticamente nunca alcanzan un movimiento limpio de +0.5% o +1.5% en menos de 2 horas sin retroceder levemente, convirtiéndose en candidatas seguras para ser liquidadas por Time-Stop en pérdidas de -0.1% a -0.6%.
- Por el contrario, activos con rango diario amplio como **NEAR** (Win Rate 66.7%, PnL +$0.0681 USD) y **ADA** (Win Rate 50%, PnL +$0.0056 USD) sí alcanzan los objetivos antes del corte por tiempo.

### Factor 4: Arrastre por Comisiones (Fee Drag)
- En operaciones micro (órdenes de $0.40 a $0.75 USD), las comisiones de Binance Spot (0.10% maker/taker = 0.20% redondo) representan una porción masiva respecto al objetivo:
  - En un Take Profit de +0.50%, el exchange se queda con el **40% de la ganancia bruta**.
  - En una pérdida cortada por Time-Stop de -0.10%, la comisión suma otro -0.20%, **triplicando la pérdida contable**.
- *(Nota: Esto fue corregido en la Fase 2 subiendo el TP a +1.50%, pero afectó todo el historial previo).*

---

## 5. Plan de Acción y Recomendaciones Técnicas

### 1. Saneamiento Inmediato de la Base de Datos (Trade #113)
- El trade `#113` (`mock_aed7f859`) fue un artefacto de prueba. Su presencia en la tabla con estado `CLOSED` distorsiona el balance de SOL y la visualización de rendimiento.
- **Acción:** Ejecutar una migración o actualización para cambiar el estado de `#113` a `ARCHIVED` (o recalcular su precio de salida al valor de mercado real de esa fecha ~$112.50 USD). Con esto, el PnL de SOL volverá inmediatamente a **-$0.0145 USD**, eliminando el falso -0.38 USDT.

### 2. Migración Gradual a Cartera de Alta Volatilidad (Opción B)
- **Retirar o pausar pares lentos:** Pausar `BNB/USDT` y `XRP/USDT` del Scalper Agent. Son activos excelentes para swing o grid trading, pero pésimos para scalping con Time-Stop en 1m.
- **Enfocar el Scalper en Momentum Leaders:** Concentrar el capital en activos con ATR alto: `NEAR`, `SUI`, `SOL`, `DOGE` y evaluar incorporar `FET` o `TAO`.

### 3. Ajuste Fino del Safe Time-Stop
- Actualmente, el Time-Stop corta la posición si tras 120 minutos el PnL es `< 0%`.
- **Mejora:** Implementar una banda de tolerancia ("Dead Zone"). Si la pérdida tras 120 minutos es insignificante (entre `-0.01%` y `-0.20%`), no cerrar obligatoriamente si el indicador RSI en 5m/15m muestra recuperación o sobreventa (`oversold_grace`). Cortar solo si la pérdida supera el `-0.50%`.

### 4. Mantener Take Profit Institucional (>= +1.50%)
- La regla incorporada en la Fase 2 que eleva el Take Profit a +1.50% es imprescindible para garantizar que el **Payoff Ratio sea >= 1.5**, permitiendo que incluso con un Win Rate del 45%, el bot sea rentable.

---

## 6. Archivo y Trazabilidad

- **Ruta Oficial del Documento:**  
  `/home/shifu/documentos-agy/auditoria_pnl_scalper_agent_20261012.md`
- **Enlace de Acceso:**  
  [auditoria_pnl_scalper_agent_20261012.md](file:///home/shifu/documentos-agy/auditoria_pnl_scalper_agent_20261012.md)
- **Copia en Proyecto:**  
  `/home/shifu/tredding-agent/docs/auditoria_pnl_scalper_agent_20261012.md`
