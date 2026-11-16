from mcp_browserdata import crypto

SVC = "Test Safe Storage"


def test_v10_roundtrip():
    blob = crypto.encrypt_v10(b"hello world", SVC)
    assert blob[:3] == b"v10"
    assert crypto.decrypt_v10(blob, SVC) == b"hello world"


def test_cookie_value_roundtrip():
    host = ".example.com"
    blob = crypto.encrypt_cookie_value("secret-token", host, SVC)
    assert crypto.decrypt_cookie_value(blob, "", host, SVC) == "secret-token"


def test_cookie_plaintext_column_wins():
    assert crypto.decrypt_cookie_value(b"", "plain", "host", SVC) == "plain"


def test_decrypt_plaintext_passthrough():
    assert crypto.decrypt_v10(b"not-encrypted", SVC) == b"not-encrypted"
