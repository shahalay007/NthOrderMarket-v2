# pip install sqlalchemy
import sqlite3
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class Event(Base):
    __tablename__ = 'events'

    id = Column(String, primary_key=True)  # event_id from Polymarket
    slug = Column(String, unique=True, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)  # Event description from Polymarket
    domain = Column(String)  # Domain (e.g., "Politics", "Sports")
    section = Column(String)  # Section (e.g., "US Politics", "Motorsports")
    subsection = Column(String)  # Subsection (e.g., "Elections", "Formula 1")
    section_tag_id = Column(Integer)  # Legacy field
    subsection_tag_id = Column(Integer, nullable=True)  # Legacy field
    is_active = Column(Boolean, default=True)
    volume = Column(Integer, default=0)  # Trading volume
    last_trade_date = Column(String, nullable=True)  # Last trade timestamp
    
    # Enrichment fields
    outcome_prices = Column(Text, nullable=True)  # JSON array of outcome prices
    last_trade_price = Column(Integer, nullable=True)  # Last trade price
    best_bid = Column(Integer, nullable=True)  # Best bid price
    best_ask = Column(Integer, nullable=True)  # Best ask price
    liquidity = Column(Integer, nullable=True)  # Total liquidity
    liquidity_num = Column(Integer, nullable=True)  # Numeric liquidity
    liquidity_clob = Column(Integer, nullable=True)  # CLOB liquidity
    open_interest = Column(Integer, nullable=True)  # Open interest
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)

class Tag(Base):
    __tablename__ = 'tags'

    tag_id = Column(Integer, primary_key=True)
    label = Column(String)
    slug = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Database:
    def __init__(self, db_path='polymarket.db'):
        self.engine = create_engine(f'sqlite:///{db_path}')
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def add_or_update_event(self, event_id, slug, title, domain, section, subsection, section_tag_id=None, subsection_tag_id=None, volume=None, last_trade_date=None, outcome_prices=None, last_trade_price=None, best_bid=None, best_ask=None, liquidity=None, liquidity_num=None, liquidity_clob=None, open_interest=None, description=None):
        """Add new event or update existing event with domain, section, subsection, description, and enrichment fields."""
        event = self.session.query(Event).filter_by(id=str(event_id)).first()

        if event:
            # Update existing
            event.slug = slug
            event.title = title
            if description is not None:
                event.description = description
            event.domain = domain
            event.section = section
            event.subsection = subsection
            event.section_tag_id = section_tag_id
            event.subsection_tag_id = subsection_tag_id if subsection_tag_id else None
            event.is_active = True
            if volume is not None:
                event.volume = int(volume)
            if last_trade_date is not None:
                event.last_trade_date = last_trade_date
            # Update enrichment fields
            if outcome_prices is not None:
                event.outcome_prices = outcome_prices
            if last_trade_price is not None:
                event.last_trade_price = last_trade_price
            if best_bid is not None:
                event.best_bid = best_bid
            if best_ask is not None:
                event.best_ask = best_ask
            if liquidity is not None:
                event.liquidity = liquidity
            if liquidity_num is not None:
                event.liquidity_num = liquidity_num
            if liquidity_clob is not None:
                event.liquidity_clob = liquidity_clob
            if open_interest is not None:
                event.open_interest = open_interest
            event.updated_at = datetime.utcnow()
            event.last_synced = datetime.utcnow()
        else:
            # Create new
            event = Event(
                id=str(event_id),
                slug=slug,
                title=title,
                description=description,
                domain=domain,
                section=section,
                subsection=subsection,
                section_tag_id=section_tag_id,
                subsection_tag_id=subsection_tag_id if subsection_tag_id else None,
                is_active=True,
                volume=int(volume) if volume is not None else 0,
                last_trade_date=last_trade_date,
                outcome_prices=outcome_prices,
                last_trade_price=last_trade_price,
                best_bid=best_bid,
                best_ask=best_ask,
                liquidity=liquidity,
                liquidity_num=liquidity_num,
                liquidity_clob=liquidity_clob,
                open_interest=open_interest,
                last_synced=datetime.utcnow()
            )
            self.session.add(event)

        self.session.commit()
        return event

    def update_market_data(self, event_id, volume, last_trade_date):
        """Update market data for an event."""
        event = self.session.query(Event).filter_by(id=str(event_id)).first()
        if event:
            event.volume = int(volume) if volume is not None else 0
            event.last_trade_date = last_trade_date
            event.updated_at = datetime.utcnow()
            self.session.commit()
            return event
        return None

    def mark_inactive_events(self, active_event_ids):
        """Mark events as inactive if they're not in the active list."""
        active_ids_str = [str(eid) for eid in active_event_ids]
        inactive_events = self.session.query(Event).filter(
            Event.id.notin_(active_ids_str),
            Event.is_active == True
        ).all()

        for event in inactive_events:
            event.is_active = False
            event.updated_at = datetime.utcnow()

        self.session.commit()
        return len(inactive_events)

    def get_all_active_events(self):
        """Get all active events from database."""
        return self.session.query(Event).filter_by(is_active=True).all()

    def add_or_update_tag(self, tag_id, label, slug):
        """Add new tag or update existing tag."""
        tag = self.session.query(Tag).filter_by(tag_id=tag_id).first()

        if tag:
            tag.label = label
            tag.slug = slug
            tag.updated_at = datetime.utcnow()
        else:
            tag = Tag(
                tag_id=tag_id,
                label=label,
                slug=slug
            )
            self.session.add(tag)

        self.session.commit()
        return tag

    def get_all_tags(self):
        """Get all tags from database."""
        return self.session.query(Tag).all()

    def close(self):
        """Close database session."""
        self.session.close()