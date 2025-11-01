# Kalshi Database Schema
import sqlite3
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class KalshiMarket(Base):
    __tablename__ = 'kalshi_markets'

    # Primary identifiers
    ticker = Column(String, primary_key=True)  # Unique market ticker
    event_ticker = Column(String, nullable=False, index=True)  # Parent event ticker

    # Basic info
    title = Column(Text, nullable=False)
    subtitle = Column(Text, nullable=True)
    market_type = Column(String)  # binary, scalar, etc.
    category = Column(String, nullable=True)  # Sports, Politics, Economics, etc.

    # Status and dates
    status = Column(String)  # unopened, open, closed, settled
    open_time = Column(DateTime, nullable=True)
    close_time = Column(DateTime, nullable=True)
    expiration_time = Column(DateTime, nullable=True)
    settlement_time = Column(DateTime, nullable=True)

    # Trading data
    volume = Column(Integer, default=0)
    liquidity = Column(Integer, default=0)
    open_interest = Column(Integer, default=0)

    # Pricing (stored in cents, 0-100)
    yes_bid = Column(Integer, nullable=True)
    yes_ask = Column(Integer, nullable=True)
    no_bid = Column(Integer, nullable=True)
    no_ask = Column(Integer, nullable=True)
    last_price = Column(Integer, nullable=True)

    # Result
    result = Column(String, nullable=True)  # yes, no, or final value

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)


class KalshiEvent(Base):
    __tablename__ = 'kalshi_events'

    # Primary identifiers
    event_ticker = Column(String, primary_key=True)

    # Basic info
    title = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    series_ticker = Column(String, nullable=True)

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KalshiDatabase:
    def __init__(self, db_path='kalshi.db'):
        self.engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def add_or_update_market(self, ticker, event_ticker, title, subtitle=None, market_type=None,
                             category=None, status=None, open_time=None, close_time=None,
                             expiration_time=None, settlement_time=None, volume=None, liquidity=None,
                             open_interest=None, yes_bid=None, yes_ask=None, no_bid=None,
                             no_ask=None, last_price=None, result=None):
        """Add new market or update existing market."""
        market = self.session.query(KalshiMarket).filter_by(ticker=ticker).first()

        if market:
            # Update existing
            market.event_ticker = event_ticker
            market.title = title
            if subtitle is not None:
                market.subtitle = subtitle
            if market_type is not None:
                market.market_type = market_type
            if category is not None:
                market.category = category
            if status is not None:
                market.status = status
                market.is_active = (status in ['open', 'active'])
            if open_time is not None:
                market.open_time = open_time
            if close_time is not None:
                market.close_time = close_time
            if expiration_time is not None:
                market.expiration_time = expiration_time
            if settlement_time is not None:
                market.settlement_time = settlement_time
            if volume is not None:
                market.volume = int(volume)
            if liquidity is not None:
                market.liquidity = int(liquidity)
            if open_interest is not None:
                market.open_interest = int(open_interest)
            if yes_bid is not None:
                market.yes_bid = yes_bid
            if yes_ask is not None:
                market.yes_ask = yes_ask
            if no_bid is not None:
                market.no_bid = no_bid
            if no_ask is not None:
                market.no_ask = no_ask
            if last_price is not None:
                market.last_price = last_price
            if result is not None:
                market.result = result
            market.updated_at = datetime.utcnow()
            market.last_synced = datetime.utcnow()
        else:
            # Create new
            market = KalshiMarket(
                ticker=ticker,
                event_ticker=event_ticker,
                title=title,
                subtitle=subtitle,
                market_type=market_type,
                category=category,
                status=status,
                is_active=(status in ['open', 'active']) if status else True,
                open_time=open_time,
                close_time=close_time,
                expiration_time=expiration_time,
                settlement_time=settlement_time,
                volume=int(volume) if volume is not None else 0,
                liquidity=int(liquidity) if liquidity is not None else 0,
                open_interest=int(open_interest) if open_interest is not None else 0,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                no_bid=no_bid,
                no_ask=no_ask,
                last_price=last_price,
                result=result,
                last_synced=datetime.utcnow()
            )
            self.session.add(market)

        self.session.commit()
        return market

    def add_or_update_event(self, event_ticker, title, category=None, series_ticker=None):
        """Add new event or update existing event."""
        event = self.session.query(KalshiEvent).filter_by(event_ticker=event_ticker).first()

        if event:
            event.title = title
            if category is not None:
                event.category = category
            if series_ticker is not None:
                event.series_ticker = series_ticker
            event.updated_at = datetime.utcnow()
        else:
            event = KalshiEvent(
                event_ticker=event_ticker,
                title=title,
                category=category,
                series_ticker=series_ticker
            )
            self.session.add(event)

        self.session.commit()
        return event

    def mark_inactive_markets(self, active_tickers):
        """Mark markets as inactive if they're not in the active list."""
        inactive_markets = self.session.query(KalshiMarket).filter(
            KalshiMarket.ticker.notin_(active_tickers),
            KalshiMarket.is_active == True
        ).all()

        for market in inactive_markets:
            market.is_active = False
            market.updated_at = datetime.utcnow()

        self.session.commit()
        return len(inactive_markets)

    def get_all_active_markets(self):
        """Get all active markets from database."""
        return self.session.query(KalshiMarket).filter_by(is_active=True).all()

    def get_market_by_ticker(self, ticker):
        """Get a specific market by ticker."""
        return self.session.query(KalshiMarket).filter_by(ticker=ticker).first()

    def get_markets_by_event(self, event_ticker):
        """Get all markets for a specific event."""
        return self.session.query(KalshiMarket).filter_by(event_ticker=event_ticker).all()

    def get_markets_by_category(self, category):
        """Get all active markets in a category."""
        return self.session.query(KalshiMarket).filter_by(
            category=category,
            is_active=True
        ).all()

    def get_top_markets_by_volume(self, limit=10):
        """Get top markets by volume."""
        return self.session.query(KalshiMarket).filter_by(
            is_active=True
        ).order_by(KalshiMarket.volume.desc()).limit(limit).all()

    def close(self):
        """Close database session."""
        self.session.close()
