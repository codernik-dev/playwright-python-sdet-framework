"""Database engine, session factory and the declarative base."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from claimdesk.config import get_app_settings


class Base(DeclarativeBase):
    """Declarative base for every ClaimDesk table."""


_settings = get_app_settings()

engine = create_engine(
    _settings.sqlalchemy_url,
    pool_pre_ping=True,
    future=True,
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
