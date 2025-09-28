from automation_audit.normalize import fold_digits, normalize_text


def test_nfkc_digit_fold():
    value = "٠۱۲٣\u200cك"
    result = normalize_text(value)
    assert result == "0123ک"
