#!/usr/bin/env python3
"""
scripts/monetize_asset.py

Script para monetizar y liquidar posiciones en cartera a saldo líquido disponible en USDT.
Utilizado para realizar beneficios históricos (ej. SOL +$38.00 USD) o cualquier activo a pedido.

Uso:
    python scripts/monetize_asset.py SOL
    python scripts/monetize_asset.py DOGE --price 0.095
"""
import sys
import os
import argparse
import asyncio

# Asegurar path del proyecto
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradingbot.execution.portfolio_manager import PortfolioManager, DatabaseSession
from tradingbot.market.ccxt_connector import CCXTConnector
from tradingbot.interfaces.telegram.notifier import TelegramNotifier
from tradingbot.utils.logger import log, registrar_log


async def main_async(symbol_or_asset: str, override_price: float = None):
    asset = symbol_or_asset.split('/')[0].upper()
    trading_pair = f"{asset}/USDT"

    log.info(f"Iniciando monetización de activo: {asset} ({trading_pair})...")
    pm = PortfolioManager()
    notifier = TelegramNotifier()

    price = override_price
    if price is None or price <= 0:
        connector = CCXTConnector()
        try:
            ticker = await connector.fetch_ticker(trading_pair)
            price = float(ticker.get('last') or ticker.get('close') or 0.0)
            log.info(f"Precio de mercado obtenido para {trading_pair}: ${price:,.4f} USDT")
        except Exception as e:
            log.warning(f"No se pudo obtener precio en vivo vía CCXT ({e}). Usando precio registrado en base de datos.")
            price = None
        finally:
            await connector.close()

    res = await pm.monetize_asset_async(asset, price=price, is_paper=True)
    if res.get("status") == "error":
        print(f"❌ Error: {res.get('message')}")
        return 1

    print("\n" + "="*60)
    print(f"✅ MONETIZACIÓN EXITOSA: {asset}")
    print("="*60)
    print(f"• Cantidad liquidada:     {res['quantity']:.4f} {asset}")
    print(f"• Precio de ejecución:    ${res['price']:,.4f} USDT")
    print(f"• Total bruto liquidado:  +${res['total_credited']:,.2f} USD")
    print(f"• Ganancia neta (PnL):    +${res['realized_pnl']:,.2f} USD (+{res['pnl_pct']*100:.1f}%)")
    print(f"• Nuevo saldo en caja:    ${res['new_wallet_balance']:,.2f} USDT")
    print("="*60 + "\n")

    # Notificar a Telegram
    msg = (
        f"💰 <b>REALIZACIÓN DE BENEFICIOS / MONETIZACIÓN DE {asset}</b>\n\n"
        f"🎉 Se ha liquidado la posición histórica en <b>{asset}</b> y acreditado a la cartera líquida:\n\n"
        f"• <b>Cantidad:</b> {res['quantity']:.4f} {asset}\n"
        f"• <b>Precio Venta:</b> ${res['price']:,.4f} USDT\n"
        f"• <b>Ganancia Neta (PnL):</b> 🟢 <b>+${res['realized_pnl']:,.2f} USD</b> (+{res['pnl_pct']*100:.1f}%)\n"
        f"• <b>Capital Acreditado a USDT:</b> +${res['total_credited']:,.2f} USD\n"
        f"• <b>Nuevo Saldo Líquido Disponible:</b> <b>${res['new_wallet_balance']:,.2f} USDT</b>\n\n"
        f"<i>El capital ahora está listo para rotar en las estrategias multi-agente con reserva segura.</i>"
    )
    notifier.send_message(msg)
    registrar_log("CASHFLOW", f"MONETIZACION_{asset}: +${res['realized_pnl']:.2f} USD realizado. Saldo actual: ${res['new_wallet_balance']:.2f} USDT")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Monetize / Harvest asset profits to digital wallet")
    parser.add_argument("symbol", type=str, help="Asset or symbol to monetize (e.g. SOL, DOGE, SOL/USDT)")
    parser.add_argument("--price", type=float, default=None, help="Optional manual execution price override")
    args = parser.parse_args()

    exit_code = asyncio.run(main_async(args.symbol, args.price))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
