import uuid

import pytest

from sma.hardened_api.api import APISettings, create_app
from sma.hardened_api.auth_repository import APIKeyRecord, InMemoryAPIKeyRepository
from sma.hardened_api.middleware import AuthConfig
from sma.hardened_api.observability import hash_national_id, metrics_registry_guard
from tests.hardened_api.conftest import FakeAllocator, FakeRedis, verify_middleware_order


def _build_app():
    redis_client = FakeRedis()
    allocator = FakeAllocator()
    salt = "testsalt"
    raw_key = "STATICKEY1234567890"
    repo = InMemoryAPIKeyRepository([APIKeyRecord(name="fixture", key_hash=hash_national_id(raw_key, salt=salt))])
    auth_config = AuthConfig(
        bearer_secret="secret-key",
        api_key_salt=salt,
        accepted_audience={"alloc"},
        accepted_issuers={"issuer"},
        allow_plain_tokens={"TESTTOKEN1234567890"},
        api_key_repository=repo,
    )
    settings = APISettings(redis_namespace=f"test-{uuid.uuid4()}")
    return create_app(allocator=allocator, settings=settings, auth_config=auth_config, redis_client=redis_client)


@pytest.fixture()
def counter_app():
    with metrics_registry_guard():
        app = _build_app()
        yield app


def test_middleware_order_counter_post(counter_app):
    verify_middleware_order(counter_app)
