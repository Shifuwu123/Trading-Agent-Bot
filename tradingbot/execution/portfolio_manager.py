from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Dict, Any, Optional
from decimal import Decimal

from tradingbot.database.models import Trade, Portfolio, DigitalWallet, Candle, DecisionLog, CashFlow, Base
from tradingbot.core.config import get_settings
from tradingbot.utils.logger import log

class DatabaseSession:
    _engine = None
    _SessionLocal = None

    @classmethod
    def initialize(cls):
        if cls._engine is None:
            settings = get_settings()
            # If using sqlite, check_same_thread=False is often required for multi-threading
            connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
            cls._engine = create_engine(settings.database_url, connect_args=connect_args)
            
            # Ensure tables are created
            Base.metadata.create_all(bind=cls._engine)
            cls._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls._engine)

    @classmethod
    def get_session(cls) -> Session:
        if cls._SessionLocal is None:
            cls.initialize()
        return cls._SessionLocal()

class PortfolioManager:
    """
    Manages portfolio state and trade records in the database.
    """
    def __init__(self):
        DatabaseSession.initialize()
        self.settings = get_settings()

    def record_open_trade(self, execution_data: Dict[str, Any], strategy: str = "default") -> Trade:
        """
        Records a new open trade in the database.
        """
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
                opened_at=datetime.utcnow()
            )
            session.add(trade)
            
            # Update portfolio balance
            self._update_portfolio_entry(
                session, 
                execution_data["symbol"], 
                execution_data["side"], 
                execution_data["amount"], 
                execution_data["price"], 
                execution_data["is_paper"]
            )
            
            # Update virtual wallet balance if paper trading
            if execution_data["is_paper"]:
                self._update_virtual_wallet(session, execution_data["side"], execution_data["amount"], execution_data["price"])
            
            session.commit()
            session.refresh(trade)
            log.info(f"Recorded open trade {trade.trade_id} for {trade.symbol}")
            
            return trade
        except Exception as e:
            session.rollback()
            log.error(f"Failed to record open trade: {e}")
            raise
        finally:
            session.close()

    def record_close_trade(self, trade_id: str, execution_data: Dict[str, Any]) -> Optional[Trade]:
        """
        Records the closing of an open trade, calculates PnL, and updates the database.
        """
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
            
            # Calculate PnL
            if trade.side == "BUY":
                # Bought to open, sold to close
                trade.pnl = (price_exit_dec - trade.price_entry) * trade.quantity
                trade.pnl_pct = (price_exit_dec - trade.price_entry) / trade.price_entry if trade.price_entry > 0 else 0
            else:
                # Sold to open, bought to close (Short)
                trade.pnl = (trade.price_entry - price_exit_dec) * trade.quantity
                trade.pnl_pct = (trade.price_entry - price_exit_dec) / trade.price_entry if trade.price_entry > 0 else 0
            
            # Update portfolio balance
            # For closing, the 'side' in execution_data is opposite to entry side.
            self._update_portfolio_entry(
                session, 
                execution_data["symbol"], 
                execution_data["side"], 
                execution_data["amount"], 
                execution_data["price"], 
                execution_data["is_paper"]
            )
            
            # Update virtual wallet balance if paper trading
            if execution_data["is_paper"]:
                # When closing a trade, if we bought to open and sell to close, we get money back
                # Since side is "SELL" (closing a BUY), we add to wallet. 
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

    def _update_portfolio_entry(self, session: Session, symbol: str, side: str, amount: float, price: float, is_paper: bool):
        """
        Updates the portfolio balance based on an execution.
        Must be called within an active session transaction.
        """
        amount_dec = Decimal(str(amount))
        price_dec = Decimal(str(price))
        
        # For simplicity, we track the base asset (e.g., BTC from BTC/USDT)
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
                is_paper=is_paper
            )
            session.add(portfolio)
        
        if side == "BUY":
            # Adding to position
            total_value = (portfolio.quantity * portfolio.avg_price) + (amount_dec * price_dec)
            portfolio.quantity += amount_dec
            if portfolio.quantity > 0:
                portfolio.avg_price = total_value / portfolio.quantity
        else: 
            # SELL - Reducing position
            portfolio.quantity -= amount_dec
            # If quantity hits 0 or below, we reset avg_price
            if portfolio.quantity <= 0:
                 portfolio.quantity = Decimal("0.0")
                 portfolio.avg_price = Decimal("0.0")
                 
        portfolio.current_price = price_dec

    def _update_virtual_wallet(self, session: Session, side: str, amount: float, price: float):
        """
        Updates the DigitalWallet balance for paper trading.
        """
        telegram_id = str(self.settings.telegram_chat_id)
        if not telegram_id:
            telegram_id = "default"
            
        wallet = session.query(DigitalWallet).filter(
            DigitalWallet.telegram_id == telegram_id,
            DigitalWallet.is_paper == True
        ).first()
        
        if not wallet:
            wallet = DigitalWallet(
                telegram_id=telegram_id,
                balance_usd=Decimal("10000.0"),
                is_paper=True
            )
            session.add(wallet)
            
        amount_dec = Decimal(str(amount))
        price_dec = Decimal(str(price))
        
        cost = amount_dec * price_dec
        
        # Ensure balance_usd is Decimal before arithmetic
        current_balance = Decimal(str(wallet.balance_usd))
        
        # BUY: We spend USDT to get BTC (subtract from balance)
        # SELL: We get USDT back (add to balance)
        if side == "BUY":
            wallet.balance_usd = current_balance - cost
        else:
            wallet.balance_usd = current_balance + cost

    def record_decision(self, symbol: str, decision: str, reason: str = ""):
        """
        Registra una decisión (HOLD, BLOCKED, BUY, SELL) en la base de datos para estadísticas.
        """
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
        """
        Registra múltiples decisiones en una sola transacción masiva.
        'decisions' debe ser una lista de dicts: [{'symbol': '...', 'decision': '...', 'reason': '...'}]
        """
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
        """
        Records a cash flow event (DEPOSIT, EXPENSE, WITHDRAWAL) and updates the DigitalWallet.
        """
        session = DatabaseSession.get_session()
        try:
            telegram_id = str(self.settings.telegram_chat_id)
            if not telegram_id:
                telegram_id = "default"
                
            amount_dec = Decimal(str(amount_usd))
            
            cashflow = CashFlow(
                telegram_id=telegram_id,
                type=record_type,
                amount_usd=amount_dec,
                description=description,
                is_paper=True
            )
            session.add(cashflow)
            
            # Update virtual wallet balance
            wallet = session.query(DigitalWallet).filter(
                DigitalWallet.telegram_id == telegram_id,
                DigitalWallet.is_paper == True
            ).first()
            
            if not wallet:
                wallet = DigitalWallet(telegram_id=telegram_id, balance_usd=Decimal("10000.0"), is_paper=True)
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
        """
        Calculates total investments, expenses, trading PnL, and ROI.
        """
        session = DatabaseSession.get_session()
        try:
            telegram_id = str(self.settings.telegram_chat_id)
            if not telegram_id:
                telegram_id = "default"
                
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
            
            total_pnl = sum(float(t.pnl) if t.pnl else 0.0 for t in trades)
            
            wallet = session.query(DigitalWallet).filter(
                DigitalWallet.telegram_id == telegram_id,
                DigitalWallet.is_paper == True
            ).first()
            
            current_balance = float(wallet.balance_usd) if wallet else 10000.0
            
            # ROI is calculated based on net deposits minus expenses (actual capital invested)
            # Or simply: Total PnL / (Initial 10000 + Deposits - Expenses)
            # We assume a base 10000 if no deposits were made, or we just count it.
            # Let's count 10000 as implicit initial deposit.
            base_capital = 10000.0 + total_deposits - total_expenses
            roi_pct = (total_pnl / base_capital) * 100 if base_capital > 0 else 0.0
            
            return {
                "deposits": total_deposits,
                "expenses": total_expenses,
                "withdrawals": total_withdrawals,
                "pnl": total_pnl,
                "balance": current_balance,
                "roi_pct": roi_pct
            }
        finally:
            session.close()

    def get_portfolio_summary(self) -> list:
        """
        Returns a list of all currently held assets (quantity > 0) in the paper portfolio.
        """
        session = DatabaseSession.get_session()
        try:
            portfolio = session.query(Portfolio).filter(
                Portfolio.is_paper == True,
                Portfolio.quantity > 0
            ).all()
            
            return [{"asset": p.asset, "quantity": float(p.quantity), "avg_price": float(p.avg_price), "current_price": float(p.current_price)} for p in portfolio]
        finally:
            session.close()
