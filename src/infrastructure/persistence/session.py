# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

try:
    from src.infrastructure.monitoring.metrics import db_query_duration_seconds  # type: ignore
except Exception:  # pragma: no cover - optional import in design phase
    db_query_duration_seconds = None  # type: ignore


def make_engine(dsn: str):
    engine = create_engine(
        dsn,
        pool_size=20,
        max_overflow=40,
        pool_timeout=5,
        pool_recycle=1800,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover - driver specific
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("SET statement_timeout TO 2000")
            cursor.close()
        except Exception:
            pass

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # pragma: no cover - timing
        context._query_start_time = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # pragma: no cover - timing
        if db_query_duration_seconds is not None:
            db_query_duration_seconds.observe(perf_counter() - getattr(context, "_query_start_time", perf_counter()))

    return engine


def make_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
