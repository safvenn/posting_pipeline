"""SQLAlchemy engine, session factory, and Base for all models."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings

import re
from urllib.parse import quote_plus, unquote


def normalize_db_url(raw_url: str) -> str:
    """Normalize connection strings: dialect prefixes and auto-encode special characters in password."""
    if not raw_url:
        return raw_url
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    elif url.startswith("mysql://"):
        url = url.replace("mysql://", "mysql+pymysql://", 1)

    # Handle unencoded special characters in password (e.g. '@', '#', etc.)
    # Format: dialect://user:password@host[:port]/dbname
    match = re.match(r"^([a-zA-Z0-9_+]+)://([^:]+):(.*)@([^@]+)$", url)
    if match:
        proto, user, password, host_part = match.groups()
        encoded_pass = quote_plus(unquote(password))
        url = f"{proto}://{user}:{encoded_pass}@{host_part}"
    return url


db_url = normalize_db_url(settings.database_url)

is_sqlite = db_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
engine_kwargs = {"connect_args": connect_args}
if not is_sqlite:
    engine_kwargs.update({"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20})

engine = create_engine(
    db_url,
    **engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session, always closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
