from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from tooling.middleware_app import get_app

def test_only_one_succeeds(redis_client, redis_namespace):
    app = get_app(redis_client, redis_namespace, token="metrics-token")
    client = TestClient(app)
    idem_key = uuid4().hex

    def do_request() -> int:
        response = client.post(
            "/submit",
            json={
                "reg_center": 0,
                "reg_status": 1,
                "gender": 1,
                "mobile": "٠٩١٢٣٤٥٦٧٨٩",
                "text_fields_desc": "\u200fتست",
                "national_id": "0061234567",
                "year": 2024,
                "counter": "123573678",
            },
            headers={
                "Authorization": "Bearer metrics-token",
                "X-Request-ID": "req-shared",
                "X-Idempotency-Key": idem_key,
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: do_request(), range(2)))

    assert codes.count(200) == 2
    keys = list(redis_client.scan_iter(match=f"{redis_namespace}:idem:*"))
    assert len(keys) == 1
    client.close()


def test_unique_idempotency_keys_per_request(redis_client, redis_namespace):
    app = get_app(redis_client, redis_namespace, token="metrics-token")
    client = TestClient(app)
    keys: list[str] = []

    for _ in range(3):
        idem_key = uuid4().hex
        keys.append(idem_key)
        response = client.post(
            "/submit",
            json={
                "reg_center": 2,
                "reg_status": 0,
                "gender": 0,
                "mobile": "09123456789",
                "text_fields_desc": "نمونه",
                "national_id": "0061234567",
                "year": 2024,
                "counter": "013733456",
            },
            headers={
                "Authorization": "Bearer metrics-token",
                "X-Request-ID": f"req-{idem_key}",
                "X-Idempotency-Key": idem_key,
            },
        )
        assert response.status_code == 200, response.text

    stored_suffixes = set()
    for raw_key in redis_client.scan_iter(match=f"{redis_namespace}:idem:*"):
        key_str = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        _, suffix = key_str.split(":idem:", 1)
        stored_suffixes.add(suffix)

    assert stored_suffixes == set(keys)
    client.close()
