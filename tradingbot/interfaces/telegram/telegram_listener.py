from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log, registrar_log

class TelegramListener:
    def __init__(self, bot_instance):
        self.bot_instance = bot_instance
        self.settings = get_settings()
        import os
        self.token = getattr(self.settings, 'telegram_bot_token', os.getenv('TELEGRAM_BOT_TOKEN', ''))
        self.allowed_chat_id = str(getattr(self.settings, 'telegram_chat_id', os.getenv('TELEGRAM_CHAT_ID', '')))

    async def verify_user(self, update: Update) -> bool:
        if str(update.effective_chat.id) != self.allowed_chat_id:
            log.warning(f"Unauthorized access attempt from chat id: {update.effective_chat.id}")
            await update.message.reply_text("⛔ Acceso denegado. No tienes permisos para operar este bot.")
            return False
        return True

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        state = "Pausado ⏸️" if self.bot_instance.paused else "Corriendo ▶️"
        capital_usd = await self.bot_instance.get_current_capital()
        capital_clp = self.bot_instance.clp_converter.convert_usd_to_clp(capital_usd)
        open_pos = self.bot_instance.trade_engine.get_open_positions_count()
        
        msg = f"📊 *Estado del Bot*\n\n"
        msg += f"Estado: {state}\n"
        msg += f"Posiciones Abiertas: {open_pos}\n"
        msg += f"Capital Est.: ${capital_usd:,.2f} USD\n"
        msg += f"Capital Est. (CLP): ${capital_clp:,.0f} CLP"
        
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def pause_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        self.bot_instance.paused = True
        await update.message.reply_text("⏸️ El bot ha sido *pausado*. Las reglas de mercado no se evaluarán hasta usar /resume.", parse_mode="Markdown")

    async def resume_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        self.bot_instance.paused = False
        await update.message.reply_text("▶️ El bot ha sido *reanudado*. Volviendo a operar.", parse_mode="Markdown")

    async def buy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        if len(context.args) < 2:
            await update.message.reply_text("Uso correcto: `/buy <symbol> <cantidad>`\nEj: `/buy BTC/USDT 0.01`", parse_mode="Markdown")
            return
            
        symbol = context.args[0].upper()
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("Error: La cantidad debe ser un número.")
            return
            
        await update.message.reply_text(f"⏳ Intentando ejecutar compra manual de {amount} {symbol}...")
        try:
            res = await self.bot_instance.execute_manual_order(symbol, "BUY", amount)
            
            report_msg = f"Operación MANUAL ejecutada: BUY de {amount} {symbol} a {res.get('price', 'N/A')} USD"
            registrar_log("REPORTE", report_msg)
            
            await update.message.reply_text(f"✅ Compra ejecutada exitosamente.\nID: {res['order_id']}\nPrecio: {res['price']} USDT")
        except Exception as e:
            await update.message.reply_text(f"❌ Error ejecutando orden: {e}")

    async def sell_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        if len(context.args) < 2:
            await update.message.reply_text("Uso correcto: `/sell <symbol> <cantidad>`\nEj: `/sell BTC/USDT 0.01`", parse_mode="Markdown")
            return
            
        symbol = context.args[0].upper()
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("Error: La cantidad debe ser un número.")
            return
            
        # Check holdings before allowing a sell (prevent Naked Shorts)
        portfolio = self.bot_instance.portfolio_manager.get_portfolio_summary()
        base_asset = symbol.split('/')[0]
        
        held_quantity = 0.0
        for item in portfolio:
            if item['asset'] == base_asset:
                held_quantity = item['quantity']
                break
                
        if amount > held_quantity:
            await update.message.reply_text(f"❌ Error: Saldo insuficiente. Intentas vender {amount} {base_asset}, pero solo tienes {held_quantity} {base_asset} en tu billetera.")
            return
            
        await update.message.reply_text(f"⏳ Intentando ejecutar venta manual de {amount} {symbol}...")
        try:
            res = await self.bot_instance.execute_manual_order(symbol, "SELL", amount)
            # In a real bot, you'd close the specific trade, but recording it as an open trade suffices for this PDD
            
            report_msg = f"Operación MANUAL ejecutada: SELL de {amount} {symbol} a {res.get('price', 'N/A')} USD"
            registrar_log("REPORTE", report_msg)
            
            await update.message.reply_text(f"✅ Venta ejecutada exitosamente.\nID: {res['order_id']}\nPrecio: {res['price']} USDT")
        except Exception as e:
            await update.message.reply_text(f"❌ Error ejecutando orden: {e}")

    async def mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        current_mode = getattr(self.bot_instance.config.bot, "trading_mode", "trend")
        
        if len(context.args) == 0:
            if current_mode == "trend":
                desc = "Cortar pérdidas rápido (Protector)"
            elif current_mode == "scalper":
                desc = "Micro-ganancias 0.5% (Agresivo)"
            else:
                desc = "Nunca vender a pérdida (Victorioso)"
                
            await update.message.reply_text(f"⚙️ El modo actual es: *{current_mode.upper()}*\n_{desc}_\n\nPara cambiarlo usa: `/mode trend`, `/mode target` o `/mode scalper`", parse_mode="Markdown")
            return
            
        new_mode = context.args[0].lower()
        if new_mode not in ["trend", "target", "scalper"]:
            await update.message.reply_text("❌ Modo inválido. Opciones: `trend`, `target` o `scalper`", parse_mode="Markdown")
            return
            
        # Update memory
        self.bot_instance.config.bot.trading_mode = new_mode
        
        # Update file so it persists
        try:
            import yaml
            config_path = "config.yaml"
            with open(config_path, "r") as f:
                data = yaml.safe_load(f)
            if "bot" in data:
                data["bot"]["trading_mode"] = new_mode
            with open(config_path, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                
            registrar_log("REPORTE", f"Modo de trading cambiado a {new_mode.upper()}")
            await update.message.reply_text(f"✅ Modo de trading cambiado exitosamente a: *{new_mode.upper()}*", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"⚠️ Modo cambiado temporalmente a {new_mode}, pero hubo error al guardar config.yaml: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        from tradingbot.database.models import DecisionLog
        from tradingbot.execution.portfolio_manager import DatabaseSession
        from datetime import datetime, timedelta
        
        session = DatabaseSession.get_session()
        try:
            now = datetime.utcnow()
            # Por defecto: hoy desde medianoche UTC
            time_filter_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            title_suffix = "Hoy (Desde 00:00 UTC)"
            
            # Revisar si el usuario envió un parámetro (ej. /stats 12)
            if context.args and len(context.args) > 0:
                try:
                    hours = int(context.args[0])
                    time_filter_start = now - timedelta(hours=hours)
                    title_suffix = f"Últimas {hours} hora(s)"
                except ValueError:
                    await update.message.reply_text("❌ Error: El parámetro debe ser el número de horas (ej: `/stats 12`).", parse_mode="Markdown")
                    return
            
            logs = session.query(DecisionLog).filter(DecisionLog.timestamp >= time_filter_start).all()
            
            total = len(logs)
            holds = sum(1 for l in logs if l.decision == "HOLD")
            blocked = sum(1 for l in logs if l.decision == "BLOCKED")
            buys = sum(1 for l in logs if l.decision == "BUY")
            sells = sum(1 for l in logs if l.decision == "SELL")
            errors = sum(1 for l in logs if l.decision == "ERROR")
            
            msg = f"📊 *Estadísticas: {title_suffix}*\n\n"
            msg += f"• Total Evaluaciones: {total:,}\n"
            msg += f"• ⏸️ HOLD (Esperando): {holds:,}\n"
            msg += f"• 🛡️ Operaciones Bloqueadas: {blocked:,}\n"
            msg += f"• 🟢 Compras (BUY): {buys:,}\n"
            msg += f"• 🔴 Ventas (SELL): {sells:,}\n"
            if errors > 0:
                msg += f"• ❌ Errores: {errors:,}\n"
                
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al consultar estadísticas: {e}")
        finally:
            session.close()

    async def deposit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        if len(context.args) < 1:
            await update.message.reply_text("Uso: `/deposit <monto> [descripción]`\nEj: `/deposit 1000 Inversión inicial`", parse_mode="Markdown")
            return
            
        try:
            amount = float(context.args[0])
            desc = " ".join(context.args[1:]) if len(context.args) > 1 else "Depósito"
            
            res = self.bot_instance.portfolio_manager.add_cashflow_record("DEPOSIT", amount, desc)
            await update.message.reply_text(f"✅ Depósito registrado: +${amount:,.2f} USD\nNota: {desc}\nNuevo Balance: ${res['new_balance']:,.2f} USD")
            registrar_log("CASHFLOW", f"DEPOSIT: {amount} USD - {desc}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al registrar depósito: {e}")

    async def expense_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        if len(context.args) < 1:
            await update.message.reply_text("Uso: `/expense <monto> [descripción]`\nEj: `/expense 20 Pago VPS`", parse_mode="Markdown")
            return
            
        try:
            amount = float(context.args[0])
            desc = " ".join(context.args[1:]) if len(context.args) > 1 else "Gasto Operativo"
            
            res = self.bot_instance.portfolio_manager.add_cashflow_record("EXPENSE", amount, desc)
            await update.message.reply_text(f"💸 Gasto registrado: -${amount:,.2f} USD\nNota: {desc}\nNuevo Balance: ${res['new_balance']:,.2f} USD")
            registrar_log("CASHFLOW", f"EXPENSE: {amount} USD - {desc}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al registrar gasto: {e}")

    async def cashflow_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        try:
            summary = self.bot_instance.portfolio_manager.get_cashflow_summary()
            
            # Formatear el mensaje
            msg = f"📊 *Reporte Financiero (Flujo de Caja)*\n\n"
            msg += f"💼 *Inversión Inicial (Base)*: $10,000.00 USD\n"
            
            if summary['deposits'] > 0:
                msg += f"📥 *Depósitos Adicionales*: +${summary['deposits']:,.2f} USD\n"
                
            if summary['expenses'] > 0:
                msg += f"💸 *Gastos Operativos (APIs/VPS)*: -${summary['expenses']:,.2f} USD\n"
                
            if summary['withdrawals'] > 0:
                msg += f"📤 *Retiros*: -${summary['withdrawals']:,.2f} USD\n"
                
            pnl_emoji = "🟢" if summary['pnl'] >= 0 else "🔴"
            msg += f"\n📈 *Ganancias Netas (PnL Trading)*: {pnl_emoji} ${summary['pnl']:,.2f} USD\n"
            
            msg += f"\n🏦 *Capital Liquidado Disponible*: ${summary['balance']:,.2f} USD\n"
            
            roi = summary['roi_pct']
            roi_emoji = "🚀" if roi > 0 else "📉"
            msg += f"🎯 *ROI Neto*: {roi_emoji} {roi:.2f}%\n"
            
            await update.message.reply_text(msg, parse_mode="Markdown")
            
            # Segundo mensaje con el detalle del portafolio
            portfolio = self.bot_instance.portfolio_manager.get_portfolio_summary()
            
            port_msg = f"👝 *Detalle de tu Billetera (Holdings)*\n\n"
            if not portfolio:
                port_msg += "Tu billetera está vacía (Solo tienes USDT líquidos)."
            else:
                for item in portfolio:
                    asset = item['asset']
                    qty = item['quantity']
                    avg_px = item['avg_price']
                    cur_px = item['current_price']
                    
                    pnl_usd = (cur_px - avg_px) * qty
                    pnl_pct = (cur_px - avg_px) / avg_px if avg_px > 0 else 0.0
                    emoji = "🟢" if pnl_usd >= 0 else "🔴"
                    
                    port_msg += f"🔸 *{asset}*: {qty:.8f}\n"
                    port_msg += f"   Precio Compra (Promedio): ${avg_px:,.2f} USDT\n"
                    port_msg += f"   Precio Actual: ${cur_px:,.2f} USDT\n"
                    port_msg += f"   Ganancia/Pérdida Activa: {emoji} ${pnl_usd:,.2f} USDT ({pnl_pct*100:.2f}%)\n\n"
            
            # Tercer sección: Histórico de PnL por moneda
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
                    port_msg += "\n🏛️ *Histórico de Ganancias Realizadas (Monedas Cerradas)*\n\n"
                    for sym, pnl in pnl_by_symbol:
                        p_usd = float(pnl) if pnl else 0.0
                        emoji = "🟢" if p_usd >= 0 else "🔴"
                        port_msg += f"🔸 *{sym}*: {emoji} ${p_usd:,.2f} USDT\n"
            finally:
                session.close()
                    
            await update.message.reply_text(port_msg, parse_mode="Markdown")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error al generar reporte financiero: {e}")

    async def why_block_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self.verify_user(update): return
        
        from tradingbot.database.models import DecisionLog
        from tradingbot.execution.portfolio_manager import DatabaseSession
        
        session = DatabaseSession.get_session()
        try:
            # Consultar las últimas 10 operaciones bloqueadas
            logs = session.query(DecisionLog).filter(
                DecisionLog.decision == "BLOCKED"
            ).order_by(DecisionLog.timestamp.desc()).limit(10).all()
            
            if not logs:
                await update.message.reply_text("✅ No tienes operaciones bloqueadas recientes.", parse_mode="Markdown")
                return
                
            msg = "🛡️ *Últimas Operaciones Bloqueadas*\n\n"
            for idx, log_entry in enumerate(logs, 1):
                ts = log_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                msg += f"*{idx}. {log_entry.symbol}* ({ts})\n"
                msg += f"   Motivo: {log_entry.reason}\n\n"
                
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al consultar bloqueos: {e}")
        finally:
            session.close()

    def start_polling(self):
        if not self.token:
            log.error("No Telegram token available. Cannot start listener.")
            return
        
        app = ApplicationBuilder().token(self.token).build()
        app.add_handler(CommandHandler("status", self.status_command))
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
        
        log.info("Iniciando modo interactivo (Polling) de Telegram...")
        app.run_polling()
