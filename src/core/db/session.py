"""
src/core/db/session.py
Configuration SQLAlchemy conforme à P5-09b.
"""

import os
from collections.abc import Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.core.config import cfg


def get_database_url() -> str:
    """Construit l'URL PostgreSQL selon P5-09b."""
    ci_url = os.getenv("CI_POSTGRES_URL") or cfg.CI_POSTGRES_URL
    if ci_url:
        return ci_url

    password = os.getenv("POSTGRES_PASSWORD", cfg.POSTGRES_PASSWORD)
    encoded_password = quote_plus(password)
    return (
        f"postgresql+psycopg://{cfg.database.user}:{encoded_password}"
        f"@{cfg.database.host}:{cfg.database.port}/{cfg.database.name}"
    )


DATABASE_URL = get_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
