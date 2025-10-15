import os, re, pytest
def test_signing_key_is_64_hex():
    key = os.getenv("SIGNING_KEY_HEX","")
    assert re.fullmatch(r"[0-9a-fA-F]{64}", key), "SIGNING_KEY_HEX باید ۶۴ هگزا باشد"
