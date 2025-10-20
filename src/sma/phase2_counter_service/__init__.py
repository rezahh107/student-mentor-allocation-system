# -*- coding: utf-8 -*-
"""Public entry-points for the Phase 2 counter service."""
from __future__ import annotations

from functools import lru_cache
from typing import Tuple

from .types import GenderLiteral

from sma.infrastructure.persistence.session import make_engine, make_session_factory

from .config import ServiceConfig, load_from_env
from .logging_utils import build_logger, make_hash_fn
from .metrics import DEFAULT_METERS
from .repository import SqlAlchemyCounterRepository
from .service import CounterAssignmentService


@lru_cache(maxsize=1)
def _bootstrap() -> Tuple[CounterAssignmentService, ServiceConfig]:
    config = load_from_env()
    engine = make_engine(config.db_url)
    session_factory = make_session_factory(engine)
    repository = SqlAlchemyCounterRepository(session_factory)
    logger = build_logger()
    hash_fn = make_hash_fn(config.pii_hash_salt)
    service = CounterAssignmentService(repository, DEFAULT_METERS, logger, hash_fn)
    return service, config


def get_service() -> CounterAssignmentService:
    return _bootstrap()[0]


def get_config() -> ServiceConfig:
    return _bootstrap()[1]


def assign_counter(national_id: str, gender: GenderLiteral, year_code: str) -> str:
    service = get_service()
    return service.assign_counter(national_id, gender, year_code)
