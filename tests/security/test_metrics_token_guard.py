import os, pytest, requests
def test_metrics_requires_token():
    url = os.getenv("APP_URL","http://127.0.0.1:25119/metrics")
    r = requests.get(url)
    assert r.status_code in (401,403), "بدون توکن نباید 200 بدهد"
