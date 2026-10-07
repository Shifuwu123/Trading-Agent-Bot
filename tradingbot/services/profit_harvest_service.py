import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any, Optional
from tradingbot.core.config import ProfitHarvestConfig
from tradingbot.utils.logger import log, registrar_log

class ProfitHarvestEngine:
    """
    Motor de Cosecha Automática de Ganancias (Profit Harvester).
    Monitorea posiciones en cartera y asegura beneficios extraordinarios cuando un activo
    supera los umbrales configurados (ej. +100% de ROI o >$15 USD de ganancia neta).
    """
    def __init__(self, config: Optional[ProfitHarvestConfig] = None, portfolio_manager = None, notifier = None):
        self.config = config or ProfitHarvestConfig()
        self.portfolio_manager = portfolio_manager
        self.notifier = notifier
        self.enabled = getattr(self.config, "enabled", True)
        self.threshold_pct = getattr(self.config, "threshold_pct", 1.00)  # +100%
        self.threshold_usd = getattr(self.config, "threshold_usd", 15.00) # $15 USD

    async def scan_and_harvest(self, order_executor = None) -> List[Dict[str, Any]]:
        """
        Escanea la cartera en busca de activos elegibles para cosecha de beneficios.
        """
        if not self.enabled or not self.portfolio_manager:
            return []

        harvested = []
        try:
            summary = await self.portfolio_manager.get_portfolio_summary_async()
            for item in summary:
                asset = item["asset"]
                qty = float(item["quantity"])
                avg_px = float(item["avg_price"])
                cur_px = float(item["current_price"])
                u_pnl = float(item["unrealized_pnl"])

                if qty <= 0 or avg_px <= 0:
                    continue

                cost_basis = qty * avg_px
                pnl_pct = u_pnl / cost_basis if cost_basis > 0 else 0.0

                should_harvest = (pnl_pct >= self.threshold_pct) or (u_pnl >= self.threshold_usd)

                if should_harvest:
                    log.info(
                        f"[ProfitHarvest] Activo {asset} califica para cosecha: "
                        f"PnL +${u_pnl:.2f} USD (+{pnl_pct*100:.1f}%) >= umbral (${self.threshold_usd:.2f} / +{self.threshold_pct*100:.0f}%)"
                    )

                    res = await self.portfolio_manager.monetize_asset_async(asset, cur_px)
                    if res.get("status") == "success":
                        harvested.append(res)
                        msg = (
                            f"💰 <b>COSECHA AUTOMÁTICA DE GANANCIAS (Profit Harvest)</b>\n\n"
                            f"🎉 Se liquidó la posición extraordinaria en <b>{asset}</b> para asegurar ganancias:\n"
                            f"• <b>Cantidad:</b> {qty:.4f} {asset}\n"
                            f"• <b>Precio Venta:</b> ${cur_px:,.4f} USD\n"
                            f"• <b>Ganancia Realizada:</b> +${res['realized_pnl']:,.2f} USD (+{pnl_pct*100:.1f}%)\n"
                            f"• <b>Capital Acreditado a Billetera:</b> +${res['total_credited']:,.2f} USD\n"
                            f"• <b>Nuevo Saldo Líquido Disponible:</b> ${res['new_wallet_balance']:,.2f} USDT"
                        )
                        if self.notifier:
                            self.notifier.send_message(msg)
                        registrar_log("CASHFLOW", f"PROFIT_HARVEST_{asset}: +${res['realized_pnl']:.2f} USD acreditado a balance")

        except Exception as e:
            log.error(f"[ProfitHarvest] Error durante el escaneo de cosecha: {e}")

        return harvested
