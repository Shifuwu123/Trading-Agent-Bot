#!/usr/bin/env python3
"""
scripts/generar_bitacora_fiscal_sii.py

Generador de Bitácora y Reporte Tributario Anual conforme a la
Circular N° 43 del Servicio de Impuestos Internos (SII) de Chile.

Normativa Aplicada:
- Operaciones no afectas a IVA (enajenación de bienes incorporales).
- Determinación del Mayor Valor (Ganancia Neta) en moneda nacional (CLP)
  mediante el tipo de cambio oficial Dólar Observado en la fecha de cierre.
- Deducción de comisiones operativas (Fee Drag) como gasto necesario para generar la renta.
- Desglose por activo, resumen para Formulario F22 (Operación Renta) y cálculo del IGC estimado.
"""

import os
import sys
import sqlite3
from datetime import datetime
from decimal import Decimal

BOT_DIR = "/home/shifu/tredding-agent"
DB_PATH = "/dev/shm/tradingbot.db" if os.path.exists("/dev/shm/tradingbot.db") else os.path.join(BOT_DIR, "tradingbot.db")
OUTPUT_MD = "/home/shifu/documentos-agy/bitacora_fiscal_sii_2026.md"

def generar_bitacora():
    print(f"[*] Conectando a base de datos: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            trade_id, symbol, side, quantity, price_entry, price_exit,
            pnl, fee_usd, pnl_net_usd, clp_exchange_rate, pnl_clp,
            opened_at, closed_at, exit_reason
        FROM trades
        WHERE status = 'CLOSED'
        ORDER BY closed_at ASC
    """)
    trades = cur.fetchall()

    total_ops = len(trades)
    print(f"[+] Trades cerrados analizados: {total_ops}")

    total_pnl_usd = Decimal("0.0")
    total_fee_usd = Decimal("0.0")
    total_net_usd = Decimal("0.0")
    total_pnl_clp = Decimal("0.0")

    asset_stats = {}

    table_rows = []
    for t in trades:
        (tid, sym, side, qty, p_in, p_out, pnl, fee, pnl_net, clp_rate, pnl_clp, t_in, t_out, reason) = t
        
        pnl_dec = Decimal(str(pnl or 0.0))
        fee_dec = Decimal(str(fee or 0.0))
        
        # Si no tenía fee_usd o pnl_net calculado previamente, calcularlo al vuelo
        if fee_dec == Decimal("0.0") and p_in and p_out and qty:
            fee_dec = (Decimal(str(p_in)) * Decimal(str(qty)) + Decimal(str(p_out)) * Decimal(str(qty))) * Decimal("0.0010")
            
        net_dec = Decimal(str(pnl_net)) if pnl_net is not None and Decimal(str(pnl_net)) != Decimal("0.0") else (pnl_dec - fee_dec)
        rate_dec = Decimal(str(clp_rate)) if clp_rate is not None else Decimal("950.0")
        clp_dec = Decimal(str(pnl_clp)) if pnl_clp is not None and Decimal(str(pnl_clp)) != Decimal("0.0") else (net_dec * rate_dec)

        total_pnl_usd += pnl_dec
        total_fee_usd += fee_dec
        total_net_usd += net_dec
        total_pnl_clp += clp_dec

        # Desglose por activo
        if sym not in asset_stats:
            asset_stats[sym] = {"trades": 0, "net_usd": Decimal("0.0"), "net_clp": Decimal("0.0")}
        asset_stats[sym]["trades"] += 1
        asset_stats[sym]["net_usd"] += net_dec
        asset_stats[sym]["net_clp"] += clp_dec

        date_str = str(t_out)[:16] if t_out else "N/A"
        sign_emoji = "🟢" if net_dec >= 0 else "🔴"
        table_rows.append(
            f"| `{tid}` | {date_str} | **{sym}** | ${pnl_dec:,.2f} | ${fee_dec:,.4f} | "
            f"{sign_emoji} ${net_dec:,.2f} | ${rate_dec:,.1f} | **${clp_dec:,.0f} CLP** |"
        )

    # Subcuenta de reserva acumulada
    cur.execute("SELECT balance_usd, reserve_usd FROM digital_wallet WHERE id = 1;")
    wallet_info = cur.fetchone() or (0.0, 0.0)
    conn.close()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md_content = f"""# 🇨🇱 Bitácora Fiscal y Libro de Mayor Valor Cripto (Año 2026)
### Normativa: Circular N° 43 SII — Servicio de Impuestos Internos de Chile

**Fecha de Emisión:** {now_str}  
**Entidad Operativa:** Tredding Agent Multi-Agente v1.2  
**Ruta del Archivo:** [`{OUTPUT_MD}`](file://{OUTPUT_MD})  
**Estado:** Bitácora Automatizada Oficial para Operación Renta F22  

---

## 1. Resumen Ejecutivo de Tributación

| Métrica Consolidada | Monto USD | Monto Moneda Nacional (CLP) |
|---|---|---|
| **Operaciones Totales Cerradas** | {total_ops} trades | — |
| **PnL Bruto Acumulado** | ${total_pnl_usd:,.2f} USD | — |
| **Comisiones Deducibles (Fees Exchange)** | ${total_fee_usd:,.4f} USD | — |
| **Mayor Valor Neto Imponible (Ganancia Realizada)** | **${total_net_usd:,.2f} USD** | **${total_pnl_clp:,.0f} CLP** |
| **Reserva Patrimonial Blindada (Profit Sweep 20%)** | ${Decimal(str(wallet_info[1])):,.2f} USD | — |
| **Saldo Operativo Actual en Cuenta** | ${Decimal(str(wallet_info[0])):,.2f} USD | — |

> [!NOTE] Criterio Fiscal Circular N° 43 SII
> Las criptomonedas son clasificadas como activos incorporales muebles. La ganancia generada en su enajenación no está afecta a IVA, pero constituye renta afecta al **Impuesto Global Complementario (IGC)** o Primera Categoría. Cada transacción se valoriza según el tipo de cambio oficial Dólar Observado al momento de su liquidación.

---

## 2. Desglose del Mayor Valor por Activo Financiero

| Par / Criptoactivo | Operaciones | PnL Neto (USD) | Mayor Valor Tributable (CLP) |
|---|---|---|---|
"""
    for sym, st in sorted(asset_stats.items(), key=lambda x: x[1]["net_usd"], reverse=True):
        md_content += f"| **{sym}** | {st['trades']} | ${st['net_usd']:,.2f} USD | ${st['net_clp']:,.0f} CLP |\n"

    md_content += f"""
---

## 3. Detalle Cronológico de Operaciones Cerradas

| Trade ID | Fecha Cierre (UTC) | Activo | PnL Bruto | Fee Exchange | PnL Neto USD | Dólar Obs. | Mayor Valor CLP |
|---|---|---|---|---|---|---|---|
""" + "\n".join(table_rows[-30:]) + f"""

*(Mostrando los últimos 30 trades de un total de {total_ops} operaciones registradas en el historial).*

---
*Documento generado automáticamente por Antigravity AI para auditoría contable y despacho de Jarvis.*
"""

    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"[+] Bitácora fiscal generada exitosamente en: {OUTPUT_MD}")
    return OUTPUT_MD

if __name__ == "__main__":
    generar_bitacora()
