import os

import pytest

from lotto.tools import CHARSETS, decrypt_text, encrypt_text, run_tool, words


def test_wordlist_loaded():
    assert len(words()) == 7776


def test_numbers_distinct_in_range():
    r = run_tool("numbers", os.urandom(32), {"lo": 1, "hi": 50, "count": 50, "distinct": True, "sort": True})
    assert r["values"] == list(range(1, 51))


def test_numbers_too_many_distinct_raises():
    with pytest.raises(ValueError):
        run_tool("numbers", os.urandom(32), {"lo": 1, "hi": 5, "count": 6, "distinct": True})


def test_password_respects_classes_and_ambiguity():
    r = run_tool("password", os.urandom(32), {"length": 40, "classes": ["lower", "digits"], "exclude_ambiguous": True})
    pw = r["value"]
    assert len(pw) == 40
    assert set(pw) <= set(CHARSETS["lower"] + CHARSETS["digits"]) - set("0l1")
    assert any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw)


def test_passphrase_shape():
    r = run_tool("passphrase", os.urandom(32), {"count": 5, "separator": " ", "capitalize": True, "add_number": False})
    parts = r["value"].split(" ")
    assert len(parts) == 5 and all(p[0].isupper() for p in parts)


def test_key_formats():
    s = os.urandom(32)
    assert len(run_tool("key", s, {"bits": 256, "format": "hex"})["value"]) == 64
    assert len(run_tool("key", s, {"bits": 128, "format": "binary"})["value"]) == 128


def test_shuffle_is_permutation():
    r = run_tool("shuffle", os.urandom(32), {"items": "a, b, c, d, e, f"})
    assert sorted(r["values"]) == ["a", "b", "c", "d", "e", "f"]


def test_encrypt_roundtrip_and_wrong_password():
    tok = encrypt_text("secret message ✓", "correct horse", os.urandom(32))
    assert tok.startswith("elab1.")
    assert decrypt_text(tok, "correct horse") == "secret message ✓"
    with pytest.raises(ValueError):
        decrypt_text(tok, "battery staple")
    with pytest.raises(ValueError):
        decrypt_text("garbage", "correct horse")


def test_same_seed_same_output_different_seed_different():
    a = run_tool("password", b"\x05" * 32, {"length": 30})["value"]
    b = run_tool("password", b"\x05" * 32, {"length": 30})["value"]
    c = run_tool("password", b"\x06" * 32, {"length": 30})["value"]
    assert a == b and a != c
