"""Quick randomness tests for a byte stream, scored 0-100 for the source health lab.

Not a substitute for the NIST SP 800-22 suite, but enough to show which
sources are clean and which are noisy-but-biased (camera, mic).
"""
from __future__ import annotations
import math
import zlib
from collections import Counter


def monobit(data: bytes) -> float:
    """Fraction of one bits; ideal 0.5."""
    ones = sum(bin(b).count("1") for b in data)
    return ones / (8 * len(data)) if data else 0.0


def chi_square_bytes(data: bytes) -> float:
    """Chi-square of byte values vs uniform; expected around 255 for random data."""
    n = len(data)
    if n == 0:
        return 0.0
    exp = n / 256
    c = Counter(data)
    return sum((c.get(v, 0) - exp) ** 2 / exp for v in range(256))


def runs_score(data: bytes) -> float:
    """Wald-Wolfowitz style runs on the bit stream; returns |z| (ideal < 2)."""
    bits = "".join(f"{b:08b}" for b in data)
    n = len(bits)
    if n < 100:
        return 0.0
    n1 = bits.count("1")
    n0 = n - n1
    if n0 == 0 or n1 == 0:
        return 99.0
    runs = 1 + sum(1 for a, b in zip(bits, bits[1:]) if a != b)
    mu = 1 + 2 * n0 * n1 / n
    var = 2 * n0 * n1 * (2 * n0 * n1 - n) / (n * n * (n - 1))
    return abs(runs - mu) / math.sqrt(var) if var > 0 else 99.0


def serial_correlation(data: bytes) -> float:
    n = len(data)
    if n < 3:
        return 0.0
    xs = list(data)
    mean = sum(xs) / n
    num = sum((xs[i] - mean) * (xs[i + 1] - mean) for i in range(n - 1))
    den = sum((x - mean) ** 2 for x in xs)
    return num / den if den else 0.0


def compression_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return len(zlib.compress(data, 9)) / len(data)


def shannon(data: bytes) -> float:
    n = len(data)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in Counter(data).values())


def health_report(data: bytes) -> dict:
    ent = shannon(data)
    mono = monobit(data)
    chi = chi_square_bytes(data)
    runs = runs_score(data)
    sc = serial_correlation(data)
    cr = compression_ratio(data)
    # scoring: each test contributes up to 20 points
    s_ent = 20 * min(1.0, ent / 8.0) ** 4
    s_mono = 20 * max(0.0, 1 - abs(mono - 0.5) * 20)
    s_chi = 20 * max(0.0, 1 - max(0.0, chi - 320) / 2000)
    s_runs = 20 * max(0.0, 1 - max(0.0, runs - 2.5) / 20)
    s_comp = 20 * max(0.0, min(1.0, (cr - 0.7) / 0.32)) if cr > 0 else 0
    score = int(round(s_ent + s_mono + s_chi + s_runs + s_comp))
    verdict = "excellent" if score >= 90 else "good" if score >= 70 else "raw but usable" if score >= 40 else "biased"
    return {
        "bytes": len(data),
        "shannon_bits_per_byte": round(ent, 3),
        "monobit_ones": round(mono, 4),
        "chi_square": round(chi, 1),
        "runs_z": round(runs, 2),
        "serial_correlation": round(sc, 4),
        "compression_ratio": round(cr, 3),
        "score": score,
        "verdict": verdict,
        "note": "Raw sources are hashed before use, so a low raw score still yields a clean seed.",
    }
