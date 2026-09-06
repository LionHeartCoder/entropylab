"""General-purpose generators driven by the entropy pool: numbers, dice, shuffles,
passwords, passphrases, keys, and password-based text encryption.

Nothing here is logged or saved. Secrets stay in the response only.
"""
from __future__ import annotations
import base64
import math
import os
import re
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .rng import ChaChaRNG

WORDLIST_PATH = Path(__file__).resolve().parents[2] / "data" / "eff_large_wordlist.txt"
_WORDS: list[str] | None = None

CHARSETS = {
    "lower": "abcdefghijklmnopqrstuvwxyz",
    "upper": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "digits": "0123456789",
    "symbols": "!@#$%^&*()-_=+[]{};:,.<>?/~",
}
AMBIGUOUS = set("0O1lI|`'\"")


def words() -> list[str]:
    global _WORDS
    if _WORDS is None:
        if WORDLIST_PATH.exists():
            _WORDS = [ln.split()[-1] for ln in WORDLIST_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
        else:
            _WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
                      "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango",
                      "uniform", "victor", "whiskey", "xray", "yankee", "zulu"]
    return _WORDS


# ---------------------------------------------------------------- numbers

def numbers(rng: ChaChaRNG, lo: int, hi: int, count: int, distinct: bool, sort: bool) -> dict:
    if hi < lo:
        lo, hi = hi, lo
    count = max(1, min(10_000, count))
    if distinct and count > hi - lo + 1:
        raise ValueError(f"cannot draw {count} distinct values from {lo}-{hi}")
    if distinct:
        out = rng.sample_distinct(lo, hi, count)
        if not sort:
            out = rng.shuffle(out)
    else:
        out = [rng.randint(lo, hi) for _ in range(count)]
        if sort:
            out.sort()
    return {"values": out, "bits": round(count * math.log2(hi - lo + 1), 1)}


def floats(rng: ChaChaRNG, count: int, decimals: int) -> dict:
    count = max(1, min(10_000, count))
    return {"values": [round(rng.unit(), max(0, min(15, decimals))) for _ in range(count)]}


def dice(rng: ChaChaRNG, sides: int, count: int) -> dict:
    sides = max(2, min(1000, sides))
    count = max(1, min(1000, count))
    rolls = [rng.randint(1, sides) for _ in range(count)]
    return {"values": rolls, "total": sum(rolls), "sides": sides}


def coins(rng: ChaChaRNG, count: int) -> dict:
    count = max(1, min(1000, count))
    flips = ["H" if rng.below(2) else "T" for _ in range(count)]
    return {"values": flips, "heads": flips.count("H"), "tails": flips.count("T")}


def shuffle(rng: ChaChaRNG, items: list[str]) -> dict:
    items = [i.strip() for i in items if i.strip()]
    return {"values": rng.shuffle(items)}


def pick_from(rng: ChaChaRNG, items: list[str], count: int) -> dict:
    items = [i.strip() for i in items if i.strip()]
    if not items:
        raise ValueError("list is empty")
    count = max(1, min(len(items), count))
    idx = rng.sample_distinct(0, len(items) - 1, count)
    return {"values": [items[i] for i in rng.shuffle(idx)]}


# ---------------------------------------------------------------- secrets

def password(rng: ChaChaRNG, length: int, classes: list[str], exclude_ambiguous: bool, custom: str = "",
             require_each: bool = True) -> dict:
    length = max(4, min(256, length))
    alphabet = "".join(CHARSETS[c] for c in classes if c in CHARSETS) + custom
    if exclude_ambiguous:
        alphabet = "".join(ch for ch in alphabet if ch not in AMBIGUOUS)
    alphabet = "".join(dict.fromkeys(alphabet))
    if len(alphabet) < 2:
        raise ValueError("choose at least one character class")
    groups = [set(CHARSETS[c]) & set(alphabet) for c in classes if c in CHARSETS]
    groups = [g for g in groups if g]
    for _ in range(1000):
        pw = "".join(alphabet[rng.below(len(alphabet))] for _ in range(length))
        if not require_each or len(groups) > length or all(any(ch in g for ch in pw) for g in groups):
            return {"value": pw, "bits": round(length * math.log2(len(alphabet)), 1), "alphabet_size": len(alphabet)}
    raise RuntimeError("could not satisfy the character-class requirement")


def passphrase(rng: ChaChaRNG, count: int, separator: str, capitalize: bool, add_number: bool) -> dict:
    count = max(2, min(20, count))
    wl = words()
    chosen = [wl[rng.below(len(wl))] for _ in range(count)]
    if capitalize:
        chosen = [w.capitalize() for w in chosen]
    if add_number:
        i = rng.below(count)
        chosen[i] = chosen[i] + str(rng.below(100))
    bits = count * math.log2(len(wl)) + (math.log2(100 * count) if add_number else 0)
    return {"value": separator.join(chosen), "bits": round(bits, 1), "words": len(wl)}


def key(rng: ChaChaRNG, bits: int, fmt: str) -> dict:
    bits = max(8, min(4096, bits))
    nbytes = (bits + 7) // 8
    raw = rng.bytes(nbytes)
    if fmt == "base64":
        v = base64.b64encode(raw).decode()
    elif fmt == "base64url":
        v = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    elif fmt == "binary":
        v = "".join(f"{b:08b}" for b in raw)
    elif fmt == "decimal":
        v = str(int.from_bytes(raw, "big"))
    else:
        v = raw.hex()
    return {"value": v, "bits": nbytes * 8, "format": fmt}


def uuid4(rng: ChaChaRNG, count: int) -> dict:
    count = max(1, min(100, count))
    return {"values": [str(uuid.UUID(bytes=rng.bytes(16), version=4)) for _ in range(count)]}


def pin(rng: ChaChaRNG, length: int) -> dict:
    length = max(3, min(32, length))
    return {"value": "".join(str(rng.below(10)) for _ in range(length)), "bits": round(length * math.log2(10), 1)}


# ---------------------------------------------------------------- encryption

MAGIC = "elab1"


def _kdf(password_text: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password_text.encode("utf-8"))


def encrypt_text(plaintext: str, password_text: str, extra_seed: bytes | None = None) -> str:
    """AES-256-GCM with a scrypt-derived key. Output: elab1.<salt>.<nonce>.<ciphertext> in base64url."""
    if not password_text:
        raise ValueError("password is empty")
    mix = extra_seed or b""
    salt = bytes(a ^ b for a, b in zip(os.urandom(16), (mix[:16] or b"\x00" * 16).ljust(16, b"\x00")))
    nonce = bytes(a ^ b for a, b in zip(os.urandom(12), (mix[16:28] or b"\x00" * 12).ljust(12, b"\x00")))
    k = _kdf(password_text, salt)
    ct = AESGCM(k).encrypt(nonce, plaintext.encode("utf-8"), MAGIC.encode())
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return ".".join([MAGIC, b64(salt), b64(nonce), b64(ct)])


def decrypt_text(token: str, password_text: str) -> str:
    parts = token.strip().split(".")
    if len(parts) != 4 or parts[0] != MAGIC:
        raise ValueError("not an Entropy Lab token")
    unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    salt, nonce, ct = (unb64(p) for p in parts[1:])
    k = _kdf(password_text, salt)
    try:
        return AESGCM(k).decrypt(nonce, ct, MAGIC.encode()).decode("utf-8")
    except Exception as e:  # noqa: BLE001
        raise ValueError("wrong password or corrupted token") from e


# ---------------------------------------------------------------- dispatcher

def run_tool(kind: str, seed: bytes, opts: dict) -> dict:
    rng = ChaChaRNG(seed)
    g = lambda k, d: opts.get(k, d)  # noqa: E731
    if kind == "numbers":
        return numbers(rng, int(g("lo", 1)), int(g("hi", 100)), int(g("count", 1)), bool(g("distinct", False)), bool(g("sort", False)))
    if kind == "floats":
        return floats(rng, int(g("count", 1)), int(g("decimals", 6)))
    if kind == "dice":
        return dice(rng, int(g("sides", 6)), int(g("count", 1)))
    if kind == "coins":
        return coins(rng, int(g("count", 1)))
    if kind == "shuffle":
        return shuffle(rng, re.split(r"[\n,]", g("items", "")))
    if kind == "pick":
        return pick_from(rng, re.split(r"[\n,]", g("items", "")), int(g("count", 1)))
    if kind == "password":
        return password(rng, int(g("length", 20)), list(g("classes", ["lower", "upper", "digits", "symbols"])),
                        bool(g("exclude_ambiguous", True)), str(g("custom", "")), bool(g("require_each", True)))
    if kind == "passphrase":
        return passphrase(rng, int(g("count", 6)), str(g("separator", "-")), bool(g("capitalize", False)), bool(g("add_number", False)))
    if kind == "key":
        return key(rng, int(g("bits", 256)), str(g("format", "hex")))
    if kind == "uuid":
        return uuid4(rng, int(g("count", 1)))
    if kind == "pin":
        return pin(rng, int(g("length", 6)))
    raise ValueError(f"unknown tool {kind}")
