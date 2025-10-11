"""SQLite ORM models and utilities for prediction markets."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_WRITE_DB = "polymarket.db"

Base = declarative_base()


def _resolve_db_path(path: Optional[str]) -> str:
    candidate = path or os.getenv("PREDICTION_WRITE_DB_PATH") or DEFAULT_WRITE_DB
    return os.path.abspath(os.path.expanduser(candidate))


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String)
    section = Column(String)
    subsection = Column(String)
    section_tag_id = Column(Integer)
    subsection_tag_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    volume = Column(Integer, default=0)
    last_trade_date = Column(String, nullable=True)

    outcome_prices = Column(Text, nullable=True)
    last_trade_price = Column(Integer, nullable=True)
    best_bid = Column(Integer, nullable=True)
    best_ask = Column(Integer, nullable=True)
    liquidity = Column(Integer, nullable=True)
    liquidity_num = Column(Integer, nullable=True)
    liquidity_clob = Column(Integer, nullable=True)
    open_interest = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)


class Tag(Base):
    __tablename__ = "tags"

    tag_id = Column(Integer, primary_key=True)
    label = Column(String)
    slug = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Database:
    """Minimal helper around SQLAlchemy session usage."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = _resolve_db_path(db_path)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        Base.metadata.create_all(self.engine)
        session_cls = sessionmaker(bind=self.engine)
        self.session: Session = session_cls()

    def add_or_update_event(
        self,
        *,
        event_id: str,
        slug: str,
        title: str,
        domain: Optional[str],
        section: Optional[str],
        subsection: Optional[str],
        section_tag_id: Optional[int] = None,
        subsection_tag_id: Optional[int] = None,
        volume: Optional[float] = None,
        last_trade_date: Optional[str] = None,
        outcome_prices: Optional[str] = None,
        last_trade_price: Optional[float] = None,
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
        liquidity: Optional[float] = None,
        liquidity_num: Optional[float] = None,
        liquidity_clob: Optional[float] = None,
        open_interest: Optional[float] = None,
        description: Optional[str] = None,
        is_active: bool = True,
    ) -> Event:
        event = self.session.query(Event).filter_by(id=str(event_id)).first()

        def _to_int(value: Optional[float]) -> Optional[int]:
            if value is None:
                return None
            try:
                return int(value)
            except (ValueError, TypeError):
                return None

        if event:
            event.slug = slug
            event.title = title
            if description is not None:
                event.description = description
            event.domain = domain
            event.section = section
            event.subsection = subsection
            event.section_tag_id = section_tag_id
            event.subsection_tag_id = subsection_tag_id
            event.is_active = is_active
            if volume is not None:
                event.volume = _to_int(volume) or 0
            if last_trade_date is not None:
                event.last_trade_date = last_trade_date
            if outcome_prices is not None:
                event.outcome_prices = outcome_prices
            if last_trade_price is not None:
                event.last_trade_price = _to_int(last_trade_price)
            if best_bid is not None:
                event.best_bid = _to_int(best_bid)
            if best_ask is not None:
                event.best_ask = _to_int(best_ask)
            if liquidity is not None:
                event.liquidity = _to_int(liquidity)
            if liquidity_num is not None:
                event.liquidity_num = _to_int(liquidity_num)
            if liquidity_clob is not None:
                event.liquidity_clob = _to_int(liquidity_clob)
            if open_interest is not None:
                event.open_interest = _to_int(open_interest)
            event.updated_at = datetime.utcnow()
            event.last_synced = datetime.utcnow()
        else:
            event = Event(
                id=str(event_id),
                slug=slug,
                title=title,
                description=description,
                domain=domain,
                section=section,
                subsection=subsection,
                section_tag_id=section_tag_id,
                subsection_tag_id=subsection_tag_id,
                is_active=is_active,
                volume=_to_int(volume) or 0,
                last_trade_date=last_trade_date,
                outcome_prices=outcome_prices,
                last_trade_price=_to_int(last_trade_price),
                best_bid=_to_int(best_bid),
                best_ask=_to_int(best_ask),
                liquidity=_to_int(liquidity),
                liquidity_num=_to_int(liquidity_num),
                liquidity_clob=_to_int(liquidity_clob),
                open_interest=_to_int(open_interest),
                last_synced=datetime.utcnow(),
            )
            self.session.add(event)

        self.session.commit()
        return event

    def update_market_data(
        self, event_id: str, *, volume: Optional[float], last_trade_date: Optional[str]
    ) -> Optional[Event]:
        event = self.session.query(Event).filter_by(id=str(event_id)).first()
        if not event:
            return None
        try:
            event.volume = int(volume) if volume is not None else 0
        except (ValueError, TypeError):
            event.volume = 0
        if last_trade_date is not None:
            event.last_trade_date = last_trade_date
        event.updated_at = datetime.utcnow()
        self.session.commit()
        return event

    def mark_inactive_events(self, active_event_ids: Iterable[str]) -> int:
        active_set = {str(eid) for eid in active_event_ids}
        inactive = (
            self.session.query(Event)
            .filter(Event.id.notin_(active_set), Event.is_active.is_(True))
            .all()
        )
        for event in inactive:
            event.is_active = False
            event.updated_at = datetime.utcnow()
        self.session.commit()
        return len(inactive)

    def get_all_active_events(self) -> list[Event]:
        return self.session.query(Event).filter_by(is_active=True).all()

    def add_or_update_tag(self, tag_id: int, label: str, slug: str) -> Tag:
        tag = self.session.query(Tag).filter_by(tag_id=tag_id).first()
        if tag:
            tag.label = label
            tag.slug = slug
            tag.updated_at = datetime.utcnow()
        else:
            tag = Tag(tag_id=tag_id, label=label, slug=slug)
            self.session.add(tag)
        self.session.commit()
        return tag

    def get_all_tags(self) -> list[Tag]:
        return self.session.query(Tag).all()

    def close(self) -> None:
        self.session.close()
