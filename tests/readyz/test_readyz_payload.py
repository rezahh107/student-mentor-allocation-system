import os, requests
def test_readyz_payload():
    url = os.getenv("READYZ_URL","http://127.0.0.1:25119/readyz")
    r = requests.get(url, timeout=5)
    assert r.status_code in (200,503)
    data = r.json()
    assert "redis" in data and "postgres" in data
