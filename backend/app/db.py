from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def _init() -> None:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        options: dict = {"pool_pre_ping": True}
        # SQLite (used in tests) does not support these pool options
        if not settings.database_url.startswith("sqlite"):
            options.update(
                pool_size=settings.epicwing_db_pool_size,
                max_overflow=settings.epicwing_db_max_overflow,
                pool_recycle=settings.epicwing_db_pool_recycle,
            )
        _engine = create_engine(settings.database_url, **options)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    _init()
    return _engine


def get_db() -> Iterator[Session]:
    _init()
    with _session_factory() as session:
        yield session
