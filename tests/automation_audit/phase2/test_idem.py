from automation_audit.idem import IDEMPOTENCY_TTL_SECONDS, IdempotencyStore


def test_ttl_24h_and_uniqueness(redis_client):
    store = IdempotencyStore(redis_client)
    assert store.put_if_absent("key", {"a": 1})
    ttl = redis_client.ttl(next(iter(redis_client.scan_iter(f"{store.namespace}:*"))))
    assert ttl == IDEMPOTENCY_TTL_SECONDS
    assert not store.put_if_absent("key", {"a": 2})
