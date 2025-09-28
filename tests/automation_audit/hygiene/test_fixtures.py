from automation_audit.idem import IdempotencyStore


def test_namespace_isolation(redis_client):
    store = IdempotencyStore(redis_client, namespace="ns1")
    store.put_if_absent("key", {"a": 1})
    other = IdempotencyStore(redis_client, namespace="ns2")
    assert other.get("key") is None
