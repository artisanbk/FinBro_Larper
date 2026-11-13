from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from datetime import datetime, timezone
from database import Base

class Portfolio(Base):
    __tablename__ = "portfolio"
    id = Column(Integer, primary_key=True, index=True)
    cash_balance = Column(Float, default=10000.0)
    total_fees_paid = Column(Float, default=0.0)

class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    qty = Column(Integer, default=0)  # in units of the asset's qty_step (1 share, 0.0001 BTC, ...)
    average_cost = Column(Float, default=0.0)  # per whole share / coin

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    order_type = Column(String) 
    side = Column(String) 
    qty = Column(Integer)  # in units of the asset's qty_step
    limit_price = Column(Float, nullable=True)
    status = Column(String, default="PENDING")  # PENDING (resting in the book), FILLED, CANCELLED
    filled_qty = Column(Integer, default=0)  # in units of the asset's qty_step
    avg_fill_price = Column(Float, nullable=True)
    fees = Column(Float, default=0.0)  # the per-order fee, charged on the first fill
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))  # naive UTC

class Execution(Base):
    """What one order filled during one settlement (one tick), so the chart can mark it."""
    __tablename__ = "executions"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, index=True)
    ticker = Column(String, index=True)
    side = Column(String)
    units = Column(Integer)  # in units of the asset's qty_step
    avg_price = Column(Float)  # average fill price of these units
    tick = Column(Integer)  # game tick of the fill

class Candle(Base):
    __tablename__ = "candles"
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Float, default=0)  # in shares / coins
