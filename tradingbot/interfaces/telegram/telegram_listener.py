import os
import html
import yaml
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log, registrar_log


class TelegramListener:
    def __init__(self, bot_instance):
        self.bot_instance = bot_instance
        self.settings = get_settings()
        self.token = getattr(self.settings, 'telegram_bot_token', os.getenv('TELEGRAM_BOT_TOKEN', ''))
        self.allowed_chat_id = str(getattr(self.settings, 'telegram_chat_id', os.getenv('TELEGRAM_CHAT_ID', '')))

    async def verify_user(self, update: Update) -> bool:
        user_id = str(update.effective_chat.id) if update.effective_chat else ""
        if user_id != self.allowed_chat_id:
            log.warning(f"Unauthorized access attempt from chat id: {user_id}")
            if update.effective_message:
                await update.effective_message.reply_text("⛔ <b>Acceso denegado.</b> No tienes permisos para operar este bot.", parse_mode="HTML")
            return False
        return True

    # -------------------------------------------------------------
    # Keyboard Builders
    # -------------------------------------------------------------
    def _build_status_keyboard(self) -> InlineKeyboardMarkup:
        is_paused = self.bot_instance.paused
        toggle_button = (
            InlineKeyboardButton("▶️ Reanudar Bot", callback_data="cmd:resume")
            if is_paused
            else InlineKeyboardButton("⏸️ Pausar Bot", callback_data="cmd:pause")
        )
        keyboard = [
            [
                InlineKeyboardButton("🔄 Actualizar", callback_data="nav:status"),
                InlineKeyboardButton("📈 Flujo de Caja", callback_data="nav:cashflow"),
            ],
            [
                InlineKeyboardButton("👝 Billetera", callback_data="nav:wallet"),
                InlineKeyboardButton("⚙️ Modo de Trading", callback_data="nav:modes"),
            ],
            [
                InlineKeyboardButton("🛡️ Bloqueos", callback_data="nav:why_block"),
                InlineKeyboardButton("📊 Estadísticas", callback_data="stats_h:0"),
            ],
            [
                toggle_button,
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_modes_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🏃 TREND", callback_data="set_mode:trend"),
                InlineKeyboardButton("🎯 TARGET", callback_data="set_mode:target"),
                InlineKeyboardButton("⚡ SCALPER", callback_data="set_mode:scalper"),
            ],
            [
                InlineKeyboardButton("⬅️ Volver a Estado", callback_data="nav:status"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_stats_keyboard(self, active_h: int = 0, hours: Optional[int] = None) -> InlineKeyboardMarkup:
        if hours is not None:
            active_h = hours
        keyboard = [
            [
                InlineKeyboardButton("📅 Hoy" + (" ✅" if active_h == 0 else ""), callback_data="stats_h:0"),
                InlineKeyboardButton("⏱️ 6h" + (" ✅" if active_h == 6 else ""), callback_data="stats_h:6"),
                InlineKeyboardButton("⏱️ 24h" + (" ✅" if active_h == 24 else ""), callback_data="stats_h:24"),
            ],
            [
                InlineKeyboardButton("🔄 Actualizar", callback_data=f"stats_h:{active_h}"),
                InlineKeyboardButton("⬅️ Volver a Estado", callback_data="nav:status"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_cashflow_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🔄 Actualizar", callback_data="nav:cashflow"),
                InlineKeyboardButton("👝 Ver Billetera", callback_data="nav:wallet"),
            ],
            [
                InlineKeyboardButton("⬅️ Volver a Estado", callback_data="nav:status"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_wallet_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🔄 Actualizar", callback_data="nav:wallet"),
                InlineKeyboardButton("📈 Flujo de Caja", callback_data="nav:cashflow"),
            ],
            [
                InlineKeyboardButton("⬅️ Volver a Estado", callback_data="nav:status"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_why_block_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🔄 Actualizar", callback_data="nav:why_block"),
                InlineKeyboardButton("⬅️ Volver a Estado", callback_data="nav:status"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    # -------------------------------------------------------------
    # Message Payloads
    # -------------------------------------------------------------
    async def _get_status_payload(self) -> tuple[str, InlineKeyboardMarkup]:
        state = "Pausado ⏸️" if self.bot_instance.paused else "Corriendo ▶️"
        capital_usd = await self.bot_instance.get_current_capital()
        capital_clp = self.bot_instance.clp_converter.convert_usd_to_clp(capital_usd)
        open_pos = self.bot_instance.trade_engine.get_open_positions_count()
        current_mode = getattr(self.bot_instance.config.bot, "trading_mode", "trend").upper()

        msg = (
            "📊 <b>Estado del Bot</b>\n\n"
            f"• <b>Estado:</b> {state}\n"
            f"• <b>Modo de Trading:</b> <code>{current_mode}</code>\n"
            f"• <b>Posiciones Abiertas:</b> {open_pos}\n"
            f"• <b>Capital Estimado:</b> ${capital_usd:,.2f} USD\n"
            f"• <b>Capital Estimado (CLP):</b> ${capital_clp:,.0f} CLP"
        )
        return msg, self._build_status_keyboard()

    def _get_modes_payload(self) -> tuple[str, InlineKeyboardMarkup]:
        current_mode = getattr(self.bot_instance.config.bot, "trading_mode", "trend").lower()
        if current_mode == "trend":
            desc = "Cortar pérdidas rápido (Protector)"
        elif current_mode == "scalper":
            desc = "Micro-ganancias 0.5% (Agresivo)"
        else:
            desc = "Nunca vender a pérdida (Victorioso)"

        msg = (
            "⚙️ <b>Modos de Operación (Trading Modes)</b>\n\n"
            f"Modo actual: <b>{current_mode.upper()}</b> — <i>{desc}</i>\n\n"
            "Selecciona un modo para cambiarlo al instante:\n"
            "• <b>TREND:</b> Sigue tendencias y ejecuta Stop Loss (-2%).\n"
            "• <b>TARGET:</b> Mantiene operaciones hasta tocar Take Profit.\n"
            "• <b>SCALPER:</b> Cierra en micro-ganancias rápidas al +0.5%."
        )
        return msg, self._build_modes_keyboard()

    def _get_stats_payload(self, hours: int = 0) -> tuple[str, InlineKeyboardMarkup]:
        from tradingbot.database.models import DecisionLog
        from tradingbot.execution.portfolio_manager import DatabaseSession

        session = DatabaseSession.get_session()
        try:
            now = datetime.utcnow()
            if hours > 0:
                time_filter_start = now - timedelta(hours=hours)
                title_suffix = f"Últimas {hours} hora(s)"
            else:
                time_filter_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                title_suffix = "Hoy (Desde 00:00 UTC)"

            logs = session.query(DecisionLog).filter(DecisionLog.timestamp >= time_filter_start).all()

            total = len(logs)
            holds = sum(1 for l in logs if l.decision == "HOLD")
            blocked = sum(1 for l in logs if l.decision == "BLOCKED")
            buys = sum(1 for l in logs if l.decision == "BUY")
            sells = sum(1 for l in logs if l.decision == "SELL")
            errors = sum(1 for l in logs if l.decision == "ERROR")

            msg = (
                f"📊 <b>Estadísticas: {title_suffix}</b>\n\n"
                f"• <b>Total Evaluaciones:</b> {total:,}\n"
                f"• ⏸️ <b>HOLD (Esperando):</b> {holds:,}\n"
                f"• 🛡️ <b>Operaciones Bloqueadas:</b> {blocked:,}\n"
                f"• 🟢 <b>Compras (BUY):</b> {buys:,}\n"
                f"• 🔴 <b>Ventas (SELL):</b> {sells:,}\n"
            )
            if errors > 0:
                msg += f"• ❌ <b>Errores:</b> {errors:,}\n"

            return msg, self._build_stats_keyboard(active_h=hours)
        finally:
            session.close()

    def _get_cashflow_payload(self) -> tuple[str, InlineKeyboardMarkup]:
        summary = self.bot_instance.portfolio_manager.get_cashflow_summary()

        # Reporte Financiero General
        msg = (
            "📊 <b>Reporte Financiero (Flujo de Caja)</b>\n\n"
            "💼 <b>Inversión Inicial (Base):</b> $10,000.00 USD\n"
        )
        if summary['deposits'] > 0:
            msg += f"📥 <b>Depósitos Adicionales:</b> +${summary['deposits']:,.2f} USD\n"
        if summary['expenses'] > 0:
            msg += f"💸 <b>Gastos Operativos (APIs/VPS):</b> -${summary['expenses']:,.2f} USD\n"
        if summary['withdrawals'] > 0:
            msg += f"📤 <b>Retiros:</b> -${summary['withdrawals']:,.2f} USD\n"

        realized = summary.get('realized_pnl', 0.0)
        unrealized = summary.get('unrealized_pnl', 0.0)
        total_pnl = summary['pnl']

        r_emoji = "🟢" if realized >= 0 else "🔴"
        u_emoji = "🟢" if unrealized >= 0 else "🔴"
        t_emoji = "🟢" if total_pnl >= 0 else "🔴"

        msg += (
            f"\n📈 <b>Ganancias Realizadas (Trades cerrados):</b> {r_emoji} ${realized:,.2f} USD\n"
            f"📊 <b>Ganancias Activas (Unrealized PnL):</b> {u_emoji} ${unrealized:,.2f} USD\n"
            f"💰 <b>PnL Total Neto:</b> {t_emoji} ${total_pnl:,.2f} USD\n\n"
            f"🏦 <b>Capital Liquidado Disponible:</b> ${summary['balance']:,.2f} USD\n"
        )

        roi = summary['roi_pct']
        roi_emoji = "🚀" if roi > 0 else "📉"
        msg += f"🎯 <b>ROI Neto Total:</b> {roi_emoji} {roi:.2f}%"

        return msg, self._build_cashflow_keyboard()

    def _get_wallet_payload(self) -> tuple[str, InlineKeyboardMarkup]:
        summary = self.bot_instance.portfolio_manager.get_cashflow_summary()
        liquid_balance = summary.get('balance', 0.0)
        portfolio = self.bot_instance.portfolio_manager.get_portfolio_summary()

        port_msg = (
            "👝 <b>Detalle de tu Billetera (Holdings)</b>\n\n"
            f"💵 <b>Saldo Disponible:</b> ${liquid_balance:,.2f} USDT\n"
        )
        if not portfolio:
            port_msg += "Tu billetera no tiene posiciones activas (Solo USDT líquidos).\n"
        else:
            total_unrealized = sum(item.get('unrealized_pnl', 0.0) for item in portfolio)
            u_emoji = "🟢" if total_unrealized >= 0 else "🔴"
            port_msg += f"📊 <b>PnL Flotante Total:</b> {u_emoji} ${total_unrealized:,.2f} USDT\n\n"
            port_msg += "<b>Posiciones Activas:</b>\n"
            for item in portfolio:
                asset = html.escape(str(item['asset']))
                qty = item['quantity']
                avg_px = item['avg_price']
                cur_px = item['current_price']
                pnl_usd = item.get('unrealized_pnl', (cur_px - avg_px) * qty)
                pnl_pct = (cur_px - avg_px) / avg_px if avg_px > 0 else 0.0
                emoji = "🟢" if pnl_usd >= 0 else "🔴"

                port_msg += (
                    f"🔸 <b>{asset}</b>: {qty:.8f}\n"
                    f"   Precio Compra: ${avg_px:,.2f} USDT\n"
                    f"   Precio Actual: ${cur_px:,.2f} USDT\n"
                    f"   PnL Activo: {emoji} ${pnl_usd:,.2f} USDT ({pnl_pct*100:.2f}%)\n\n"
                )

        # Histórico de Ganancias Realizadas por moneda
        from tradingbot.database.models import Trade
        from tradingbot.execution.portfolio_manager import DatabaseSession
        from sqlalchemy import func

        session = DatabaseSession.get_session()
        try:
            pnl_by_symbol = session.query(
                Trade.symbol,
                func.sum(Trade.pnl).label('total_pnl')
            ).filter(Trade.status == "CLOSED").group_by(Trade.symbol).all()

            if pnl_by_symbol:
                port_msg += "🏛️ <b>Histórico de Ganancias Realizadas (Cerradas)</b>\n\n"
                for sym, pnl in pnl_by_symbol:
                    p_usd = float(pnl) if pnl else 0.0
                    emoji = "🟢" if p_usd >= 0 else "🔴"
                    port_msg += f"🔸 <b>{html.escape(str(sym))}</b>: {emoji} ${p_usd:,.2f} USDT\n"
        finally:
            session.close()

        return port_msg, self._build_wallet_keyboard()

    def _get_cashflow_payloads(self) -> tuple[str, str, InlineKeyboardMarkup]:
        msg, _ = self._get_cashflow_payload()
        port_msg, _ = self._get_wallet_payload()
        return msg, port_msg, self._build_cashflow_keyboard()

    def _get_why_block_payload(self) -> tuple[str, InlineKeyboardMarkup]:
        from tradingbot.database.models import DecisionLog
        from tradingbot.execution.portfolio_manager import DatabaseSession

        session = DatabaseSession.get_session()
        try:
            logs = session.query(DecisionLog).filter(
                DecisionLog.decision == "BLOCKED"
            ).order_by(DecisionLog.timestamp.desc()).limit(10).all()

            if not logs:
                return "✅ <b>No tienes operaciones bloqueadas recientes.</b>", self._build_why_block_keyboard()

            msg = "🛡️ <b>Últimas Operaciones Bloqueadas</b>\n\n"
            for idx, log_entry in enumerate(logs, 1):
                ts = log_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                sym = html.escape(str(log_entry.symbol))
                reason = html.escape(str(log_entry.reason or "Sin detalle"))
                msg += f"<b>{idx}. {sym}</b> ({ts})\n   Motivo: <code>{reason}</code>\n\n"

            return msg, self._build_why_block_keyboard()
        finally:
            session.close()

    # -------------------------------------------------------------
    # Command Handlers
    # -------------------------------------------------------------
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        msg, markup = await self._get_status_payload()
        welcome = (
            "👋 <b>Bienvenido al panel de control de Tredding Agent Bot</b>\n\n"
            "Puedes consultar el estado, alternar modos de trading y ver métricas interactivamente.\n\n"
        )
        await update.message.reply_text(welcome + msg, parse_mode="HTML", reply_markup=markup)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        help_text = (
            "📖 <b>Comandos Disponibles</b>\n\n"
            "• <code>/status</code>: Ver estado general y balance\n"
            "• <code>/wallet</code>: Detalle de billetera (saldo disponible y holdings)\n"
            "• <code>/cashflow</code>: Reporte financiero de flujo de caja y ROI\n"
            "• <code>/mode [trend|target|scalper]</code>: Cambiar modo de operación\n"
            "• <code>/stats [horas]</code>: Estadísticas de decisiones (HOLD, BUY, SELL)\n"
            "• <code>/why_block</code>: Ver últimas 10 operaciones bloqueadas por riesgo\n"
            "• <code>/pause</code>: Pausar el ciclo de operaciones\n"
            "• <code>/resume</code>: Reanudar el ciclo de operaciones\n"
            "• <code>/buy &lt;symbol&gt; &lt;cantidad&gt;</code>: Compra manual (Ej: <code>/buy BTC/USDT 0.01</code>)\n"
            "• <code>/sell &lt;symbol&gt; &lt;cantidad&gt;</code>: Venta manual (Ej: <code>/sell BTC/USDT 0.01</code>)\n"
            "• <code>/deposit &lt;monto&gt; [nota]</code>: Registrar depósito en cuenta simulada\n"
            "• <code>/expense &lt;monto&gt; [nota]</code>: Registrar gasto operativo"
        )
        await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=self._build_status_keyboard())

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        msg, markup = await self._get_status_payload()
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)

    async def pause_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        self.bot_instance.paused = True
        msg, markup = await self._get_status_payload()
        await update.message.reply_text("⏸️ <b>El bot ha sido pausado.</b>\nLas reglas de mercado no se evaluarán hasta reanudar.", parse_mode="HTML", reply_markup=markup)

    async def resume_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        self.bot_instance.paused = False
        msg, markup = await self._get_status_payload()
        await update.message.reply_text("▶️ <b>El bot ha sido reanudado.</b>\nVolviendo a operar normalmente.", parse_mode="HTML", reply_markup=markup)

    async def buy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return

        if len(context.args) < 2:
            await update.message.reply_text(
                "Uso correcto: <code>/buy &lt;symbol&gt; &lt;cantidad&gt;</code>\nEjemplo: <code>/buy BTC/USDT 0.01</code>",
                parse_mode="HTML"
            )
            return

        symbol = context.args[0].upper()
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ <b>Error:</b> La cantidad debe ser un número válido.", parse_mode="HTML")
            return

        await update.message.reply_text(f"⏳ Intentando ejecutar compra manual de <b>{amount}</b> {html.escape(symbol)}...", parse_mode="HTML")
        try:
            res = await self.bot_instance.execute_manual_order(symbol, "BUY", amount)
            report_msg = f"Operación MANUAL ejecutada: BUY de {amount} {symbol} a {res.get('price', 'N/A')} USD"
            registrar_log("REPORTE", report_msg)
            await update.message.reply_text(
                f"✅ <b>Compra ejecutada exitosamente.</b>\n"
                f"<b>ID:</b> <code>{html.escape(str(res['order_id']))}</code>\n"
                f"<b>Precio:</b> ${res['price']} USDT",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error ejecutando orden:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def sell_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return

        if len(context.args) < 2:
            await update.message.reply_text(
                "Uso correcto: <code>/sell &lt;symbol&gt; &lt;cantidad&gt;</code>\nEjemplo: <code>/sell BTC/USDT 0.01</code>",
                parse_mode="HTML"
            )
            return

        symbol = context.args[0].upper()
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ <b>Error:</b> La cantidad debe ser un número válido.", parse_mode="HTML")
            return

        portfolio = self.bot_instance.portfolio_manager.get_portfolio_summary()
        base_asset = symbol.split('/')[0]

        held_quantity = 0.0
        for item in portfolio:
            if item['asset'] == base_asset:
                held_quantity = item['quantity']
                break

        if amount > held_quantity:
            await update.message.reply_text(
                f"❌ <b>Error: Saldo insuficiente.</b>\n"
                f"Intentas vender {amount} {html.escape(base_asset)}, pero solo tienes {held_quantity:.8f} {html.escape(base_asset)} en tu billetera.",
                parse_mode="HTML"
            )
            return

        await update.message.reply_text(f"⏳ Intentando ejecutar venta manual de <b>{amount}</b> {html.escape(symbol)}...", parse_mode="HTML")
        try:
            res = await self.bot_instance.execute_manual_order(symbol, "SELL", amount)
            report_msg = f"Operación MANUAL ejecutada: SELL de {amount} {symbol} a {res.get('price', 'N/A')} USD"
            registrar_log("REPORTE", report_msg)
            await update.message.reply_text(
                f"✅ <b>Venta ejecutada exitosamente.</b>\n"
                f"<b>ID:</b> <code>{html.escape(str(res['order_id']))}</code>\n"
                f"<b>Precio:</b> ${res['price']} USDT",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error ejecutando orden:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return

        if len(context.args) == 0:
            msg, markup = self._get_modes_payload()
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
            return

        new_mode = context.args[0].lower()
        if new_mode not in ["trend", "target", "scalper"]:
            await update.message.reply_text("❌ <b>Modo inválido.</b> Opciones: <code>trend</code>, <code>target</code> o <code>scalper</code>", parse_mode="HTML")
            return

        self._apply_mode_change(new_mode)
        msg, markup = self._get_modes_payload()
        await update.message.reply_text(f"✅ Modo de trading cambiado exitosamente a: <b>{new_mode.upper()}</b>", parse_mode="HTML", reply_markup=markup)

    def _apply_mode_change(self, new_mode: str):
        self.bot_instance.config.bot.trading_mode = new_mode
        try:
            import re
            config_path = "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            new_content = re.sub(
                r'(trading_mode:\s*)"?[a-zA-Z0-9_-]+"?',
                rf'\g<1>"{new_mode}"',
                content
            )
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            registrar_log("REPORTE", f"Modo de trading cambiado a {new_mode.upper()}")
        except Exception as e:
            log.warning(f"Error persisting mode to config.yaml: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        hours = 0
        if context.args and len(context.args) > 0:
            try:
                hours = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ <b>Error:</b> El parámetro debe ser el número de horas (ej: <code>/stats 12</code>).", parse_mode="HTML")
                return

        try:
            msg, markup = self._get_stats_payload(hours=hours)
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error al consultar estadísticas:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def deposit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        if len(context.args) < 1:
            await update.message.reply_text("Uso: <code>/deposit &lt;monto&gt; [descripción]</code>\nEj: <code>/deposit 1000 Inversión inicial</code>", parse_mode="HTML")
            return
        try:
            amount = float(context.args[0])
            desc = " ".join(context.args[1:]) if len(context.args) > 1 else "Depósito"
            res = self.bot_instance.portfolio_manager.add_cashflow_record("DEPOSIT", amount, desc)
            await update.message.reply_text(
                f"✅ <b>Depósito registrado:</b> +${amount:,.2f} USD\n"
                f"<b>Nota:</b> {html.escape(desc)}\n"
                f"<b>Nuevo Balance:</b> ${res['new_balance']:,.2f} USD",
                parse_mode="HTML"
            )
            registrar_log("CASHFLOW", f"DEPOSIT: {amount} USD - {desc}")
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error al registrar depósito:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def expense_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        if len(context.args) < 1:
            await update.message.reply_text("Uso: <code>/expense &lt;monto&gt; [descripción]</code>\nEj: <code>/expense 20 Pago VPS</code>", parse_mode="HTML")
            return
        try:
            amount = float(context.args[0])
            desc = " ".join(context.args[1:]) if len(context.args) > 1 else "Gasto Operativo"
            res = self.bot_instance.portfolio_manager.add_cashflow_record("EXPENSE", amount, desc)
            await update.message.reply_text(
                f"💸 <b>Gasto registrado:</b> -${amount:,.2f} USD\n"
                f"<b>Nota:</b> {html.escape(desc)}\n"
                f"<b>Nuevo Balance:</b> ${res['new_balance']:,.2f} USD",
                parse_mode="HTML"
            )
            registrar_log("CASHFLOW", f"EXPENSE: {amount} USD - {desc}")
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error al registrar gasto:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def cashflow_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        try:
            msg, markup = self._get_cashflow_payload()
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error al generar reporte financiero:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        try:
            msg, markup = self._get_wallet_payload()
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error al consultar billetera:</b> {html.escape(str(e))}", parse_mode="HTML")

    async def why_block_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        try:
            msg, markup = self._get_why_block_payload()
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            await update.message.reply_text(f"❌ <b>Error al consultar bloqueos:</b> {html.escape(str(e))}", parse_mode="HTML")

    # -------------------------------------------------------------
    # Inline Callback Handler
    # -------------------------------------------------------------
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return

        if not await self.verify_user(update):
            await query.answer("Acceso denegado.", show_alert=True)
            return

        data = query.data or ""
        await query.answer()

        try:
            if data == "nav:status":
                msg, markup = await self._get_status_payload()
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=markup)

            elif data == "nav:modes":
                msg, markup = self._get_modes_payload()
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=markup)

            elif data.startswith("set_mode:"):
                new_mode = data.split(":", 1)[1]
                self._apply_mode_change(new_mode)
                msg, markup = self._get_modes_payload()
                await query.edit_message_text(
                    f"✅ <b>Modo cambiado a {new_mode.upper()}</b>\n\n" + msg,
                    parse_mode="HTML",
                    reply_markup=markup
                )

            elif data == "cmd:pause":
                self.bot_instance.paused = True
                msg, markup = await self._get_status_payload()
                await query.edit_message_text(
                    "⏸️ <b>Bot Pausado.</b>\n\n" + msg,
                    parse_mode="HTML",
                    reply_markup=markup
                )

            elif data == "cmd:resume":
                self.bot_instance.paused = False
                msg, markup = await self._get_status_payload()
                await query.edit_message_text(
                    "▶️ <b>Bot Reanudado.</b>\n\n" + msg,
                    parse_mode="HTML",
                    reply_markup=markup
                )

            elif data.startswith("stats_h:"):
                h_str = data.split(":", 1)[1]
                hours = int(h_str) if h_str.isdigit() else 0
                msg, markup = self._get_stats_payload(hours=hours)
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=markup)

            elif data == "nav:why_block":
                msg, markup = self._get_why_block_payload()
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=markup)

            elif data == "nav:cashflow":
                msg, markup = self._get_cashflow_payload()
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=markup)

            elif data == "nav:wallet":
                msg, markup = self._get_wallet_payload()
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=markup)

        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                log.warning(f"Telegram BadRequest in callback handler: {e}")
        except Exception as e:
            log.error(f"Error handling Telegram callback '{data}': {e}")

    # -------------------------------------------------------------
    # Application Runner
    # -------------------------------------------------------------
    def start_polling(self):
        if not self.token:
            log.error("No Telegram token available. Cannot start listener.")
            return

        app = ApplicationBuilder().token(self.token).build()

        # Commands
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(CommandHandler("wallet", self.wallet_command))
        app.add_handler(CommandHandler("billetera", self.wallet_command))
        app.add_handler(CommandHandler("stats", self.stats_command))
        app.add_handler(CommandHandler("pause", self.pause_command))
        app.add_handler(CommandHandler("resume", self.resume_command))
        app.add_handler(CommandHandler("mode", self.mode_command))
        app.add_handler(CommandHandler("buy", self.buy_command))
        app.add_handler(CommandHandler("sell", self.sell_command))
        app.add_handler(CommandHandler("deposit", self.deposit_command))
        app.add_handler(CommandHandler("expense", self.expense_command))
        app.add_handler(CommandHandler("cashflow", self.cashflow_command))
        app.add_handler(CommandHandler("why_block", self.why_block_command))

        # Inline Button Callbacks
        app.add_handler(CallbackQueryHandler(self.callback_handler))

        log.info("Iniciando modo interactivo (Polling) de Telegram con soporte HTML y Botones Inline...")
        app.run_polling()
