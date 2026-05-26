"""
db_utils.py
───────────
Minimal DB layer for the annotation app.
Handles connection, models, and all read/write operations.
DATABASE_URL is read from Streamlit secrets → env var (in that order).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import streamlit as st
from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    UniqueConstraint, JSON, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session


# ── Connection URL ────────────────────────────────────────────────────────

def _get_database_url() -> str:
    """Read DATABASE_URL from Streamlit secrets, then env."""
    try:
        url = st.secrets.get("DATABASE_URL")
        if url:
            return url
    except Exception:
        pass
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Add it to .streamlit/secrets.toml or set the env var."
        )
    return url


def _build_engine(url: str):
    """
    Strip psycopg2-incompatible query params (sslmode, channel_binding)
    from the URL and pass them as connect_args instead.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    connect_args: dict = {}
    for key in ("sslmode", "channel_binding", "connect_timeout"):
        if key in params:
            connect_args[key] = params.pop(key)[0]
    clean_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=clean_query))
    if clean_url.startswith("postgresql://"):
        clean_url = "postgresql+psycopg2://" + clean_url[len("postgresql://"):]
    return create_engine(clean_url, pool_pre_ping=True, connect_args=connect_args)


# Lazy singleton engine — created on first DB call
_engine = None
_SessionLocal = None


def _get_session() -> Session:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine(_get_database_url())
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal()


# ── ORM Models ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    __tablename__ = "instruments"
    id             = Column(Integer, primary_key=True)
    name           = Column(String(512), nullable=False, unique=True)
    name_lower     = Column(String(512), nullable=False, unique=True)
    instrument_type = Column(String(128))
    year           = Column(Integer)
    description    = Column(Text)
    source_urls    = Column(JSON, default=list)
    created_at     = Column(DateTime(timezone=True), default=_now)
    updated_at     = Column(DateTime(timezone=True), default=_now)


class InstrumentAnnotation(Base):
    __tablename__ = "instrument_annotations"
    __table_args__ = (UniqueConstraint("instrument_name", "annotator_id", name="uq_annotation"),)
    id              = Column(Integer, primary_key=True)
    instrument_name = Column(String(512), nullable=False)
    annotator_id    = Column(String(64), nullable=False)
    label           = Column(String(32))   # Keep | Drop | Review | NULL
    notes           = Column(Text)
    annotated_at    = Column(DateTime(timezone=True), default=_now)
    updated_at      = Column(DateTime(timezone=True), default=_now)


# ── Data access functions ─────────────────────────────────────────────────

@st.cache_data(show_spinner="Loading instruments…")
def load_instruments() -> list[dict]:
    """Fetch all instruments from DB, sorted alphabetically."""
    session = _get_session()
    try:
        rows = session.query(Instrument).order_by(Instrument.name).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "instrument_type": r.instrument_type or "unknown",
                "year": r.year,
                "description": r.description or "",
                "source_urls": r.source_urls or [],
            }
            for r in rows
        ]
    finally:
        session.close()


def load_my_annotations(annotator_id: str) -> dict[str, dict]:
    """Load all labelled annotations for this annotator from DB."""
    session = _get_session()
    try:
        rows = (
            session.query(InstrumentAnnotation)
            .filter(
                InstrumentAnnotation.annotator_id == annotator_id,
                InstrumentAnnotation.label.isnot(None),
            )
            .all()
        )
        return {
            r.instrument_name: {
                "label": r.label,
                "notes": r.notes or "",
                "annotated_at": r.annotated_at.isoformat() if r.annotated_at else "",
            }
            for r in rows
        }
    finally:
        session.close()


def save_annotation(instrument_name: str, annotator_id: str, label: str | None, notes: str) -> None:
    """Upsert one annotation row."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    now = datetime.now(timezone.utc)
    session = _get_session()
    try:
        stmt = pg_insert(InstrumentAnnotation).values(
            instrument_name=instrument_name,
            annotator_id=annotator_id,
            label=label,
            notes=notes,
            annotated_at=now,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["instrument_name", "annotator_id"],
            set_=dict(label=label, notes=notes, updated_at=now),
        )
        session.execute(stmt)
        session.commit()
    except Exception as e:
        session.rollback()
        st.error(f"Save failed: {e}")
    finally:
        session.close()


def get_others_decisions(instrument_name: str, annotator_id: str) -> list[tuple[str, str]]:
    """Return [(annotator_id, label)] for other annotators on this instrument."""
    session = _get_session()
    try:
        rows = (
            session.query(InstrumentAnnotation.annotator_id, InstrumentAnnotation.label)
            .filter(
                InstrumentAnnotation.instrument_name == instrument_name,
                InstrumentAnnotation.annotator_id != annotator_id,
                InstrumentAnnotation.label.isnot(None),
            )
            .all()
        )
        return [(r.annotator_id, r.label) for r in rows]
    finally:
        session.close()


def get_irr_stats() -> dict:
    """Compute aggregate stats across all annotators."""
    session = _get_session()
    try:
        rows = (
            session.query(
                InstrumentAnnotation.instrument_name,
                InstrumentAnnotation.annotator_id,
                InstrumentAnnotation.label,
            )
            .filter(InstrumentAnnotation.label.isnot(None))
            .all()
        )
    finally:
        session.close()

    by_item: dict[str, dict[str, str]] = {}
    all_annotators: set[str] = set()
    for name, ann_id, label in rows:
        by_item.setdefault(name, {})[ann_id] = label
        all_annotators.add(ann_id)

    coverage_1 = len(by_item)
    coverage_2 = sum(1 for v in by_item.values() if len(v) >= 2)
    agree = 0
    conflicts: list[tuple[str, list, list]] = []
    for name, ann_map in by_item.items():
        if len(ann_map) < 2:
            continue
        labels = list(ann_map.values())
        anns   = list(ann_map.keys())
        if len(set(labels)) == 1:
            agree += 1
        else:
            conflicts.append((name, labels, anns))

    per_ann: dict[str, dict] = {}
    for name, ann_id, label in rows:
        d = per_ann.setdefault(ann_id, {"Keep": 0, "Drop": 0, "Review": 0, "total": 0})
        if label in d:
            d[label] += 1
        d["total"] += 1

    return {
        "annotators":      sorted(all_annotators),
        "coverage_1plus":  coverage_1,
        "coverage_2plus":  coverage_2,
        "agreement_count": agree,
        "conflict_items":  sorted(conflicts, key=lambda x: x[0]),
        "per_annotator":   per_ann,
    }
