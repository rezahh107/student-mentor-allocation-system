from pathlib import Path


def test_no_wall_clock_calls_in_middleware():
    source = Path("src/hardened_api/middleware.py").read_text(encoding="utf-8")
    forbidden = ["time.time(", "datetime.now(", "datetime.utcnow("]
    matches = [token for token in forbidden if token in source]
    assert matches == [], f"Forbidden wall-clock usage detected: {matches}"
