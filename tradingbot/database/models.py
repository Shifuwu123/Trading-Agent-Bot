from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Numeric, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    trade_id = Column(String, unique=True, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BUY / SELL
    order_type = Column(String, default="MARKET")
    quantity = Column(Numeric(18, 8), nullable=False)
    price_entry = Column(Numeric(18, 8), nullable=False)
    price_exit = Column(Numeric(18, 8), nullable=True)
    stop_loss = Column(Numeric(18, 8), nullable=True)
    take_profit = Column(Numeric(18, 8), nullable=True)
    pnl = Column(Numeric(18, 8), nullable=True)
    pnl_pct = Column(Numeric(18, 8), nullable=True)
    status = Column(String, default="OPEN") # OPEN, CLOSED, CANCELED
    mode = Column(String)
    strategy = Column(String)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    exchange = Column(String)
    is_paper = Column(Boolean, default=True)
    agent_id = Column(String, default="legacy", nullable=True)

class Portfolio(Base):
    __tablename__ = 'portfolio'
    
    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('digital_wallet.id'), nullable=True)
    asset = Column(String, index=True)
    quantity = Column(Numeric(18, 8), default=0.0)
    avg_price = Column(Numeric(18, 8), default=0.0)
    current_price = Column(Numeric(18, 8), default=0.0)
    unrealized_pnl = Column(Numeric(18, 8), default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_paper = Column(Boolean, default=True)
    agent_id = Column(String, default="legacy", nullable=True)
    
    __table_args__ = (UniqueConstraint('asset', 'is_paper', name='_asset_paper_uc'),)
class DigitalWallet(Base):
    __tablename__ = 'digital_wallet'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, index=True)
    balance_usd = Column(Numeric(18, 8), default=50.0)
    is_paper = Column(Boolean, default=True)
    
    __table_args__ = (UniqueConstraint('telegram_id', 'is_paper', name='_telegram_paper_uc'),)

class Candle(Base):
    """
    Tabla de datos históricos para futuro entrenamiento de Machine Learning.
    Almacena el histórico silenciosamente en cada ciclo.
    """
    __tablename__ = 'candles'
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Numeric(18, 8), nullable=False)
    high = Column(Numeric(18, 8), nullable=False)
    low = Column(Numeric(18, 8), nullable=False)
    close = Column(Numeric(18, 8), nullable=False)
    volume = Column(Numeric(18, 8), nullable=False)

    __table_args__ = (UniqueConstraint('symbol', 'timeframe', 'timestamp', name='_symbol_tf_ts_uc'),)

class DecisionLog(Base):
    """
    Registra las micro-decisiones del bot para análisis estadístico.
    """
    __tablename__ = 'decision_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String, nullable=False, index=True)
    decision = Column(String, nullable=False) # HOLD, BUY, SELL, BLOCKED
    reason = Column(String, nullable=True)

class CashFlow(Base):
    __tablename__ = 'cash_flow'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    type = Column(String, nullable=False) # DEPOSIT, EXPENSE, WITHDRAWAL
    amount_usd = Column(Numeric(18, 8), nullable=False)
    description = Column(String, nullable=True)
    is_paper = Column(Boolean, default=True)
