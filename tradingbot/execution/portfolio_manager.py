from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional, List
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, select, update, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from tradingbot.database.models import Trade, Portfolio, DigitalWallet, Candle, DecisionLog, CashFlow, Base
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log


class DatabaseSession:
    """
    Gestiona las conexiones a la base de datos tanto síncronas como asíncronas (aiosqlite).
    Configura SQLite con WAL mode y busy_timeout para concurrencia multi-agente sin bloqueos.
    """
    _engine = None
    _SessionLocal = None
    _async_engine = None
    _AsyncSessionLocal = None

    @classmethod
    def initialize(cls):
        if cls._engine is None:
            settings = get_settings()
            is_sqlite = "sqlite" in settings.database_url
            connect_args = {"check_same_thread": False, "timeout": 15} if is_sqlite else {}
            cls._engine = create_engine(settings.database_url, connect_args=connect_args)

            if is_sqlite:
                @event.listens_for(cls._engine, "connect")
                def set_sqlite_pragma(dbapi_connection, connection_record):
                    try:
                        cursor = dbapi_connection.cursor()
                        cursor.execute("PRAGMA journal_mode=WAL")
                        cursor.execute("PRAGMA busy_timeout=15000")
                        cursor.execute("PRAGMA synchronous=NORMAL")
                        cursor.close()
                    except Exception:
                        pass

            Base.metadata.create_all(bind=cls._engine)
            cls._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls._engine)

            # Motor asíncrono para operaciones no bloqueantes
            async_url = settings.database_url
            if "sqlite:///" in async_url and "sqlite+aiosqlite:///" not in async_url:
                async_url = async_url.replace("sqlite:///", "sqlite+aiosqlite:///")

            async_connect_args = {"timeout": 15} if is_sqlite else {}
            cls._async_engine = create_async_engine(async_url, connect_args=async_connect_args, echo=False)
            cls._AsyncSessionLocal = async_sessionmaker(
                bind=cls._async_engine,
                expire_on_commit=False,
                class_=AsyncSession
            )

    @classmethod
    def get_session(cls) -> Session:
        if cls._SessionLocal is None:
            cls.initialize()
        return cls._SessionLocal()

    @classmethod
    @asynccontextmanager
    async def get_async_session(cls):
        if cls._AsyncSessionLocal is None:
            cls.initialize()
        async with cls._AsyncSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


class PortfolioManager:
    """
    Gestiona el estado del portafolio, balances y operaciones en la base de datos.
    Ofrece interfaces síncronas y asíncronas para alta concurrencia.
    """
    def __init__(self):
        DatabaseSession.initialize()
        self.settings = get_settings()

    # ─────────────────────────────────────────────────────────────────────────
    # Sincrónicos (Compatibilidad hacia atrás)
    # ─────────────────────────────────────────────────────────────────────────

    def record_open_trade(self, execution_data: Dict[str, Any], strategy: str = "default", agent_id: str = "legacy") -> Trade:
        """Registra una nueva operación de compra/apertura en la base de datos (sync)."""
        session = DatabaseSession.get_session()
        try:
            trade = Trade(
                trade_id=execution_data["order_id"],
                symbol=execution_data["symbol"],
                side=execution_data["side"],
                order_type=execution_data["type"],
                quantity=execution_data["amount"],
                price_entry=execution_data["price"],
                status="OPEN",
                is_paper=execution_data["is_paper"],
                strategy=strategy,
                exchange=self.settings.exchange_id,
                agent_id=agent_id,
                opened_at=datetime.utcnow()
            )
            session.add(trade)

            self._update_portfolio_entry(
                session,
                execution_data["symbol"],
                execution_data["side"],
                execution_data["amount"],
                execution_data["price"],
                execution_data["is_paper"],
                agent_id=agent_id
            )

            if execution_data["is_paper"]:
                self._update_virtual_wallet(session, execution_data["side"], execution_data["amount"], execution_data["price"])

            session.commit()
            session.refresh(trade)
            log.info(f"Recorded open trade {trade.trade_id} for {trade.symbol} (Agent: {agent_id})")
            return trade
        except Exception as e:
            session.rollback()
            log.error(f"Failed to record open trade: {e}")
            raise
        finally:
            session.close()

    def record_close_trade(self, trade_id: str, execution_data: Dict[str, Any]) -> Optional[Trade]:
        """Registra el cierre de una operación y calcula el PnL (sync)."""
        session = DatabaseSession.get_session()
        try:
            trade = session.query(Trade).filter(Trade.trade_id == trade_id).first()
            if not trade:
                log.warning(f"Trade {trade_id} not found in database to close.")
                return None

            price_exit_dec = Decimal(str(execution_data["price"]))
            trade.price_exit = price_exit_dec
            trade.status = "CLOSED"
            trade.closed_at = datetime.utcnow()

            if trade.side == "BUY":
                trade.pnl = (price_exit_dec - trade.price_entry) * trade.quantity
                trade.pnl_pct = (price_exit_dec - trade.price_entry) / trade.price_entry if trade.price_entry > 0 else 0
            else:
                trade.pnl = (trade.price_entry - price_exit_dec) * trade.quantity
                trade.pnl_pct = (trade.price_entry - price_exit_dec) / trade.price_entry if trade.price_entry > 0 else 0

            self._update_portfolio_entry(
                session,
                execution_data["symbol"],
                execution_data["side"],
                execution_data["amount"],
                execution_data["price"],
                execution_data["is_paper"],
                agent_id=trade.agent_id or "legacy"
            )

            if execution_data["is_paper"]:
                self._update_virtual_wallet(session, execution_data["side"], execution_data["amount"], execution_data["price"])

            session.commit()
            session.refresh(trade)
            log.info(f"Recorded close trade {trade.trade_id}. PnL: {trade.pnl}")
            return trade
        except Exception as e:
            session.rollback()
            log.error(f"Failed to record close trade: {e}")
            raise
        finally:
            session.close()

    def _update_portfolio_entry(self, session: Session, symbol: str, side: str, amount: float, price: float, is_paper: bool, agent_id: str = "legacy"):
        amount_dec = Decimal(str(amount))
        price_dec = Decimal(str(price))
        base_asset = symbol.split('/')[0] if '/' in symbol else symbol

        portfolio = session.query(Portfolio).filter(
            Portfolio.asset == base_asset,
            Portfolio.is_paper == is_paper
        ).first()

        if not portfolio:
            portfolio = Portfolio(
                asset=base_asset,
                quantity=Decimal("0.0"),
                avg_price=Decimal("0.0"),
                current_price=price_dec,
                is_paper=is_paper,
                agent_id=agent_id
            )
            session.add(portfolio)
        else:
            portfolio.agent_id = agent_id

        if side == "BUY":
            total_value = (portfolio.quantity * portfolio.avg_price) + (amount_dec * price_dec)
            portfolio.quantity += amount_dec
            if portfolio.quantity > 0:
                portfolio.avg_price = total_value / portfolio.quantity
        else:
            portfolio.quantity -= amount_dec
            if portfolio.quantity <= 0:
                portfolio.quantity = Decimal("0.0")
                portfolio.avg_price = Decimal("0.0")

        portfolio.current_price = price_dec
        if portfolio.quantity > 0:
            portfolio.unrealized_pnl = (portfolio.current_price - portfolio.avg_price) * portfolio.quantity
        else:
            portfolio.unrealized_pnl = Decimal("0.0")

    def update_asset_price(self, asset: str, current_price: float, is_paper: bool = True):
        session = DatabaseSession.get_session()
        try:
            base_asset = asset.split('/')[0] if '/' in asset else asset
            portfolio = session.query(Portfolio).filter(
                Portfolio.asset == base_asset,
                Portfolio.is_paper == is_paper
            ).first()
            if portfolio:
                price_dec = Decimal(str(current_price))
                portfolio.current_price = price_dec
                if portfolio.quantity > 0:
                    portfolio.unrealized_pnl = (price_dec - portfolio.avg_price) * portfolio.quantity
                else:
                    portfolio.unrealized_pnl = Decimal("0.0")
                session.commit()
        except Exception as e:
            session.rollback()
            log.warning(f"Error updating asset price for {asset}: {e}")
        finally:
            session.close()

    def _update_virtual_wallet(self, session: Session, side: str, amount: float, price: float):
        telegram_id = str(self.settings.telegram_chat_id) or "default"
        wallet = session.query(DigitalWallet).filter(
            DigitalWallet.telegram_id == telegram_id,
            DigitalWallet.is_paper == True
        ).first()

        if not wallet:
            wallet = DigitalWallet(
                telegram_id=telegram_id,
                balance_usd=Decimal("50.0"),
                is_paper=True
            )
            session.add(wallet)

        amount_dec = Decimal(str(amount))
        price_dec = Decimal(str(price))
        cost = amount_dec * price_dec
        current_balance = Decimal(str(wallet.balance_usd))

        if side == "BUY":
            wallet.balance_usd = max(Decimal("0.0"), current_balance - cost)
        else:
            wallet.balance_usd = current_balance + cost

    def record_decision(self, symbol: str, decision: str, reason: str = ""):
        session = DatabaseSession.get_session()
        try:
            log_entry = DecisionLog(
                symbol=symbol,
                decision=decision,
                reason=reason,
                timestamp=datetime.utcnow()
            )
            session.add(log_entry)
            session.commit()
        except Exception as e:
            session.rollback()
            log.warning(f"Error al registrar decision {decision} para {symbol}: {e}")
        finally:
            session.close()

    def record_decisions_bulk(self, decisions: list):
        session = DatabaseSession.get_session()
        try:
            timestamp = datetime.utcnow()
            logs = [
                DecisionLog(
                    symbol=d['symbol'],
                    decision=d['decision'],
                    reason=d.get('reason', ''),
                    timestamp=timestamp
                ) for d in decisions
            ]
            session.bulk_save_objects(logs)
            session.commit()
        except Exception as e:
            session.rollback()
            log.warning(f"Error al registrar bulk decisions: {e}")
        finally:
            session.close()

    def add_cashflow_record(self, record_type: str, amount_usd: float, description: str = "") -> dict:
        session = DatabaseSession.get_session()
        try:
            telegram_id = str(self.settings.telegram_chat_id) or "default"
            amount_dec = Decimal(str(amount_usd))

            cashflow = CashFlow(
                telegram_id=telegram_id,
                type=record_type,
                amount_usd=amount_dec,
                description=description,
                is_paper=True
            )
            session.add(cashflow)

            wallet = session.query(DigitalWallet).filter(
                DigitalWallet.telegram_id == telegram_id,
                DigitalWallet.is_paper == True
            ).first()

            if not wallet:
                wallet = DigitalWallet(telegram_id=telegram_id, balance_usd=Decimal("50.0"), is_paper=True)
                session.add(wallet)

            current_balance = Decimal(str(wallet.balance_usd))
            if record_type == "DEPOSIT":
                wallet.balance_usd = current_balance + amount_dec
            elif record_type in ["EXPENSE", "WITHDRAWAL"]:
                wallet.balance_usd = current_balance - amount_dec

            session.commit()
            return {"status": "success", "new_balance": float(wallet.balance_usd)}
        except Exception as e:
            session.rollback()
            log.error(f"Error recording cashflow: {e}")
            raise
        finally:
            session.close()

    def get_cashflow_summary(self) -> dict:
        session = DatabaseSession.get_session()
        try:
            telegram_id = str(self.settings.telegram_chat_id) or "default"
            cashflows = session.query(CashFlow).filter(
                CashFlow.telegram_id == telegram_id,
                CashFlow.is_paper == True
            ).all()

            total_deposits = sum(float(cf.amount_usd) for cf in cashflows if cf.type == "DEPOSIT")
            total_expenses = sum(float(cf.amount_usd) for cf in cashflows if cf.type == "EXPENSE")
            total_withdrawals = sum(float(cf.amount_usd) for cf in cashflows if cf.type == "WITHDRAWAL")

            trades = session.query(Trade).filter(
                Trade.status == "CLOSED",
                Trade.is_paper == True
            ).all()

            realized_pnl = sum(float(t.pnl) if t.pnl else 0.0 for t in trades)

            portfolio_items = session.query(Portfolio).filter(
                Portfolio.is_paper == True,
                Portfolio.quantity > 0
            ).all()

            unrealized_pnl = 0.0
            for p in portfolio_items:
                if p.unrealized_pnl is not None:
                    unrealized_pnl += float(p.unrealized_pnl)
                elif p.quantity and p.current_price and p.avg_price:
                    unrealized_pnl += float((p.current_price - p.avg_price) * p.quantity)

            total_pnl = realized_pnl + unrealized_pnl

            wallet = session.query(DigitalWallet).filter(
                DigitalWallet.telegram_id == telegram_id,
                DigitalWallet.is_paper == True
            ).first()

            current_balance = float(wallet.balance_usd) if wallet else 50.0
            base_capital = 50.0 + total_deposits - total_expenses
            roi_pct = (total_pnl / base_capital) * 100 if base_capital > 0 else 0.0

            return {
                "deposits": total_deposits,
                "expenses": total_expenses,
                "withdrawals": total_withdrawals,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "pnl": total_pnl,
                "balance": current_balance,
                "roi_pct": roi_pct
            }
        finally:
            session.close()

    def get_portfolio_summary(self) -> list:
        session = DatabaseSession.get_session()
        try:
            portfolio = session.query(Portfolio).filter(
                Portfolio.is_paper == True,
                Portfolio.quantity > 0
            ).all()

            return [
                {
                    "asset": p.asset,
                    "quantity": float(p.quantity),
                    "avg_price": float(p.avg_price),
                    "current_price": float(p.current_price),
                    "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl is not None else float((p.current_price - p.avg_price) * p.quantity),
                    "agent_id": getattr(p, "agent_id", "legacy")
                }
                for p in portfolio
            ]
        finally:
            session.close()

    def reset_pnl(self, is_paper: bool = True) -> dict:
        """
        Archiva todos los trades cerrados históricos para reiniciar el PnL realizado y ROI a 0.00.
        Preserva los trades con status='ARCHIVED' para no perder auditoría ni datos históricos.
        No modifica posiciones abiertas (OPEN).
        """
        session = DatabaseSession.get_session()
        try:
            trades = session.query(Trade).filter(
                Trade.status == "CLOSED",
                Trade.is_paper == is_paper
            ).all()

            count = len(trades)
            archived_pnl = sum(float(t.pnl) if t.pnl else 0.0 for t in trades)

            for t in trades:
                t.status = "ARCHIVED"

            session.commit()
            log.info(f"[PortfolioManager] PnL reset: {count} closed trades archived (Archived PnL: ${archived_pnl:,.2f} USD).")
            return {
                "status": "success",
                "archived_trades_count": count,
                "archived_pnl": archived_pnl
            }
        except Exception as e:
            session.rollback()
            log.error(f"[PortfolioManager] Error resetting PnL: {e}")
            raise
        finally:
            session.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Asíncronos (aiosqlite + AsyncSession para concurrencia limpia)
    # ─────────────────────────────────────────────────────────────────────────

    async def record_open_trade_async(self, execution_data: Dict[str, Any], strategy: str = "default", agent_id: str = "legacy") -> Trade:
        """Registra una nueva operación de compra/apertura asíncronamente."""
        async with DatabaseSession.get_async_session() as session:
            try:
                trade = Trade(
                    trade_id=execution_data["order_id"],
                    symbol=execution_data["symbol"],
                    side=execution_data["side"],
                    order_type=execution_data["type"],
                    quantity=execution_data["amount"],
                    price_entry=execution_data["price"],
                    status="OPEN",
                    is_paper=execution_data["is_paper"],
                    strategy=strategy,
                    exchange=self.settings.exchange_id,
                    agent_id=agent_id,
                    opened_at=datetime.utcnow()
                )
                session.add(trade)

                await self._update_portfolio_entry_async(
                    session,
                    execution_data["symbol"],
                    execution_data["side"],
                    execution_data["amount"],
                    execution_data["price"],
                    execution_data["is_paper"],
                    agent_id=agent_id
                )

                if execution_data["is_paper"]:
                    await self._update_virtual_wallet_async(session, execution_data["side"], execution_data["amount"], execution_data["price"])

                await session.commit()
                log.info(f"[AsyncDB] Recorded open trade {trade.trade_id} for {trade.symbol} (Agent: {agent_id})")
                return trade
            except Exception as e:
                await session.rollback()
                log.error(f"[AsyncDB] Failed to record open trade: {e}")
                raise

    async def record_close_trade_async(self, trade_id: str, execution_data: Dict[str, Any]) -> Optional[Trade]:
        """Registra el cierre de una operación asíncronamente."""
        async with DatabaseSession.get_async_session() as session:
            try:
                result = await session.execute(select(Trade).filter(Trade.trade_id == trade_id))
                trade = result.scalars().first()
                if not trade:
                    log.warning(f"[AsyncDB] Trade {trade_id} not found in database to close.")
                    return None

                price_exit_dec = Decimal(str(execution_data["price"]))
                trade.price_exit = price_exit_dec
                trade.status = "CLOSED"
                trade.closed_at = datetime.utcnow()

                if trade.side == "BUY":
                    trade.pnl = (price_exit_dec - trade.price_entry) * trade.quantity
                    trade.pnl_pct = (price_exit_dec - trade.price_entry) / trade.price_entry if trade.price_entry > 0 else 0
                else:
                    trade.pnl = (trade.price_entry - price_exit_dec) * trade.quantity
                    trade.pnl_pct = (trade.price_entry - price_exit_dec) / trade.price_entry if trade.price_entry > 0 else 0

                await self._update_portfolio_entry_async(
                    session,
                    execution_data["symbol"],
                    execution_data["side"],
                    execution_data["amount"],
                    execution_data["price"],
                    execution_data["is_paper"],
                    agent_id=trade.agent_id or "legacy"
                )

                if execution_data["is_paper"]:
                    await self._update_virtual_wallet_async(session, execution_data["side"], execution_data["amount"], execution_data["price"])

                await session.commit()
                log.info(f"[AsyncDB] Recorded close trade {trade.trade_id}. PnL: {trade.pnl}")
                return trade
            except Exception as e:
                await session.rollback()
                log.error(f"[AsyncDB] Failed to record close trade: {e}")
                raise

    async def _update_portfolio_entry_async(self, session: AsyncSession, symbol: str, side: str, amount: float, price: float, is_paper: bool, agent_id: str = "legacy"):
        amount_dec = Decimal(str(amount))
        price_dec = Decimal(str(price))
        base_asset = symbol.split('/')[0] if '/' in symbol else symbol

        result = await session.execute(
            select(Portfolio).filter(
                Portfolio.asset == base_asset,
                Portfolio.is_paper == is_paper
            )
        )
        portfolio = result.scalars().first()

        if not portfolio:
            portfolio = Portfolio(
                asset=base_asset,
                quantity=Decimal("0.0"),
                avg_price=Decimal("0.0"),
                current_price=price_dec,
                is_paper=is_paper,
                agent_id=agent_id
            )
            session.add(portfolio)
        else:
            portfolio.agent_id = agent_id

        if side == "BUY":
            total_value = (portfolio.quantity * portfolio.avg_price) + (amount_dec * price_dec)
            portfolio.quantity += amount_dec
            if portfolio.quantity > 0:
                portfolio.avg_price = total_value / portfolio.quantity
        else:
            portfolio.quantity -= amount_dec
            if portfolio.quantity <= 0:
                portfolio.quantity = Decimal("0.0")
                portfolio.avg_price = Decimal("0.0")

        portfolio.current_price = price_dec
        if portfolio.quantity > 0:
            portfolio.unrealized_pnl = (portfolio.current_price - portfolio.avg_price) * portfolio.quantity
        else:
            portfolio.unrealized_pnl = Decimal("0.0")

    async def update_asset_price_async(self, asset: str, current_price: float, is_paper: bool = True):
        """Actualiza el precio de mercado y PnL no realizado de forma asíncrona."""
        async with DatabaseSession.get_async_session() as session:
            try:
                base_asset = asset.split('/')[0] if '/' in asset else asset
                result = await session.execute(
                    select(Portfolio).filter(
                        Portfolio.asset == base_asset,
                        Portfolio.is_paper == is_paper
                    )
                )
                portfolio = result.scalars().first()
                if portfolio:
                    price_dec = Decimal(str(current_price))
                    portfolio.current_price = price_dec
                    if portfolio.quantity > 0:
                        portfolio.unrealized_pnl = (price_dec - portfolio.avg_price) * portfolio.quantity
                    else:
                        portfolio.unrealized_pnl = Decimal("0.0")
                    await session.commit()
            except Exception as e:
                await session.rollback()
                log.warning(f"[AsyncDB] Error updating asset price for {asset}: {e}")

    async def _update_virtual_wallet_async(self, session: AsyncSession, side: str, amount: float, price: float):
        telegram_id = str(self.settings.telegram_chat_id) or "default"
        result = await session.execute(
            select(DigitalWallet).filter(
                DigitalWallet.telegram_id == telegram_id,
                DigitalWallet.is_paper == True
            )
        )
        wallet = result.scalars().first()

        if not wallet:
            wallet = DigitalWallet(
                telegram_id=telegram_id,
                balance_usd=Decimal("50.0"),
                is_paper=True
            )
            session.add(wallet)

        amount_dec = Decimal(str(amount))
        price_dec = Decimal(str(price))
        cost = amount_dec * price_dec
        current_balance = Decimal(str(wallet.balance_usd))

        if side == "BUY":
            wallet.balance_usd = max(Decimal("0.0"), current_balance - cost)
        else:
            wallet.balance_usd = current_balance + cost

    async def record_decision_async(self, symbol: str, decision: str, reason: str = ""):
        """Registra una micro-decisión asíncronamente."""
        async with DatabaseSession.get_async_session() as session:
            try:
                log_entry = DecisionLog(
                    symbol=symbol,
                    decision=decision,
                    reason=reason,
                    timestamp=datetime.utcnow()
                )
                session.add(log_entry)
                await session.commit()
            except Exception as e:
                await session.rollback()
                log.warning(f"[AsyncDB] Error recording decision {decision} for {symbol}: {e}")

    async def record_decisions_bulk_async(self, decisions: list):
        """Registra decisiones masivas de forma asíncrona sin bloquear el event loop."""
        async with DatabaseSession.get_async_session() as session:
            try:
                timestamp = datetime.utcnow()
                logs = [
                    DecisionLog(
                        symbol=d['symbol'],
                        decision=d['decision'],
                        reason=d.get('reason', ''),
                        timestamp=timestamp
                    ) for d in decisions
                ]
                session.add_all(logs)
                await session.commit()
            except Exception as e:
                await session.rollback()
                log.warning(f"[AsyncDB] Error recording bulk decisions: {e}")

    async def get_cashflow_summary_async(self) -> dict:
        """Obtiene resumen de flujo de caja asíncronamente."""
        async with DatabaseSession.get_async_session() as session:
            telegram_id = str(self.settings.telegram_chat_id) or "default"
            cf_result = await session.execute(
                select(CashFlow).filter(
                    CashFlow.telegram_id == telegram_id,
                    CashFlow.is_paper == True
                )
            )
            cashflows = cf_result.scalars().all()

            total_deposits = sum(float(cf.amount_usd) for cf in cashflows if cf.type == "DEPOSIT")
            total_expenses = sum(float(cf.amount_usd) for cf in cashflows if cf.type == "EXPENSE")
            total_withdrawals = sum(float(cf.amount_usd) for cf in cashflows if cf.type == "WITHDRAWAL")

            tr_result = await session.execute(
                select(Trade).filter(
                    Trade.status == "CLOSED",
                    Trade.is_paper == True
                )
            )
            trades = tr_result.scalars().all()
            realized_pnl = sum(float(t.pnl) if t.pnl else 0.0 for t in trades)

            pf_result = await session.execute(
                select(Portfolio).filter(
                    Portfolio.is_paper == True,
                    Portfolio.quantity > 0
                )
            )
            portfolio_items = pf_result.scalars().all()

            unrealized_pnl = 0.0
            for p in portfolio_items:
                if p.unrealized_pnl is not None:
                    unrealized_pnl += float(p.unrealized_pnl)
                elif p.quantity and p.current_price and p.avg_price:
                    unrealized_pnl += float((p.current_price - p.avg_price) * p.quantity)

            total_pnl = realized_pnl + unrealized_pnl

            w_result = await session.execute(
                select(DigitalWallet).filter(
                    DigitalWallet.telegram_id == telegram_id,
                    DigitalWallet.is_paper == True
                )
            )
            wallet = w_result.scalars().first()

            current_balance = float(wallet.balance_usd) if wallet else 50.0
            base_capital = 50.0 + total_deposits - total_expenses
            roi_pct = (total_pnl / base_capital) * 100 if base_capital > 0 else 0.0

            return {
                "deposits": total_deposits,
                "expenses": total_expenses,
                "withdrawals": total_withdrawals,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "pnl": total_pnl,
                "balance": current_balance,
                "roi_pct": roi_pct
            }

    async def get_portfolio_summary_async(self) -> list:
        """Obtiene holdings del portafolio asíncronamente."""
        async with DatabaseSession.get_async_session() as session:
            pf_result = await session.execute(
                select(Portfolio).filter(
                    Portfolio.is_paper == True,
                    Portfolio.quantity > 0
                )
            )
            portfolio = pf_result.scalars().all()

            return [
                {
                    "asset": p.asset,
                    "quantity": float(p.quantity),
                    "avg_price": float(p.avg_price),
                    "current_price": float(p.current_price),
                    "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl is not None else float((p.current_price - p.avg_price) * p.quantity),
                    "agent_id": getattr(p, "agent_id", "legacy")
                }
                for p in portfolio
            ]

    async def reset_pnl_async(self, is_paper: bool = True) -> dict:
        """Versión asíncrona de reset_pnl."""
        async with DatabaseSession.get_async_session() as session:
            try:
                result = await session.execute(
                    select(Trade).filter(
                        Trade.status == "CLOSED",
                        Trade.is_paper == is_paper
                    )
                )
                trades = result.scalars().all()
                count = len(trades)
                archived_pnl = sum(float(t.pnl) if t.pnl else 0.0 for t in trades)

                for t in trades:
                    t.status = "ARCHIVED"

                await session.commit()
                log.info(f"[AsyncDB] PnL reset: {count} closed trades archived (Archived PnL: ${archived_pnl:,.2f} USD).")
                return {
                    "status": "success",
                    "archived_trades_count": count,
                    "archived_pnl": archived_pnl
                }
            except Exception as e:
                await session.rollback()
                log.error(f"[AsyncDB] Error resetting PnL: {e}")
                raise

    def get_liquid_cash(self) -> float:
        """Obtiene el efectivo disponible (USDT) no comprometido en operaciones."""
        session = DatabaseSession.get_session()
        try:
            telegram_id = str(self.settings.telegram_chat_id) or "default"
            wallet = session.query(DigitalWallet).filter(
                DigitalWallet.telegram_id == telegram_id,
                DigitalWallet.is_paper == True
            ).first()
            return float(wallet.balance_usd) if wallet else 50.0
        finally:
            session.close()

    def get_total_equity(self) -> float:
        """Calcula el patrimonio neto total (Efectivo disponible + Valor de mercado de activos en cartera)."""
        session = DatabaseSession.get_session()
        try:
            cash = self.get_liquid_cash()
            portfolio = session.query(Portfolio).filter(
                Portfolio.is_paper == True,
                Portfolio.quantity > 0
            ).all()
            positions_val = sum(
                float(p.quantity) * (float(p.current_price) if p.current_price and float(p.current_price) > 0 else float(p.avg_price))
                for p in portfolio
            )
            return max(0.0, cash + positions_val)
        finally:
            session.close()

    async def get_liquid_cash_async(self) -> float:
        """Versión asíncrona para obtener efectivo líquido disponible (USDT)."""
        telegram_id = str(self.settings.telegram_chat_id) or "default"
        async with DatabaseSession.get_async_session() as session:
            result = await session.execute(
                select(DigitalWallet).filter(
                    DigitalWallet.telegram_id == telegram_id,
                    DigitalWallet.is_paper == True
                )
            )
            wallet = result.scalars().first()
            return float(wallet.balance_usd) if wallet else 50.0

    async def get_total_equity_async(self) -> float:
        """Versión asíncrona para calcular patrimonio neto total (Cash + Posiciones Abiertas)."""
        if not self.settings.paper_trading:
            from tradingbot.market.ccxt_connector import CCXTConnector
            connector = CCXTConnector()
            try:
                balance = await connector.fetch_balance()
                base = "USDT"
                if base in balance and 'total' in balance[base]:
                    return float(balance[base]['total'])
                elif base in balance and 'free' in balance[base]:
                    return float(balance[base]['free'])
                return 1000.0
            except Exception as e:
                log.warning(f"Error fetching real balance equity: {e}")
                return 1000.0
            finally:
                await connector.close()

        cash = await self.get_liquid_cash_async()
        async with DatabaseSession.get_async_session() as session:
            pf_result = await session.execute(
                select(Portfolio).filter(
                    Portfolio.is_paper == True,
                    Portfolio.quantity > 0
                )
            )
            portfolio = pf_result.scalars().all()
            positions_val = sum(
                float(p.quantity) * (float(p.current_price) if p.current_price and float(p.current_price) > 0 else float(p.avg_price))
                for p in portfolio
            )
            return max(0.0, cash + positions_val)

