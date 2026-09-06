"""Deterministic random bit generator seeded from the entropy pool.

ChaCha20 keystream, expanded from a 32-byte seed. All integer draws use
rejection sampling so no value in a range is favored (no modulo bias).
"""
from __future__ import annotations
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms


class ChaChaRNG:
    def __init__(self, seed: bytes):
        if len(seed) != 32:
            raise ValueError("seed must be 32 bytes")
        nonce = b"\x00" * 16
        self._enc = Cipher(algorithms.ChaCha20(seed, nonce), mode=None).encryptor()
        self._buf = b""
        self.bytes_used = 0

    def bytes(self, n: int) -> bytes:
        out = self._enc.update(b"\x00" * n)
        self.bytes_used += n
        return out

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) via rejection sampling."""
        if n <= 0:
            raise ValueError("n must be positive")
        if n == 1:
            return 0
        nbytes = (n.bit_length() + 7) // 8
        limit = (256 ** nbytes) - ((256 ** nbytes) % n)
        while True:
            r = int.from_bytes(self.bytes(nbytes), "big")
            if r < limit:
                return r % n

    def randint(self, lo: int, hi: int) -> int:
        return lo + self.below(hi - lo + 1)

    def unit(self) -> float:
        """Uniform float in [0,1) with 53 bits of precision."""
        return int.from_bytes(self.bytes(7), "big") / (1 << 56)

    def sample_distinct(self, lo: int, hi: int, k: int) -> list[int]:
        pool = list(range(lo, hi + 1))
        if k > len(pool):
            raise ValueError("k larger than range")
        for i in range(k):
            j = i + self.below(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return sorted(pool[:k])

    def weighted_choice(self, weights: list[float]) -> int:
        total = sum(weights)
        if total <= 0:
            raise ValueError("weights sum to zero")
        r = self.unit() * total
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if r < acc:
                return i
        return len(weights) - 1

    def weighted_sample_distinct(self, weights: list[float], k: int) -> list[int]:
        w = list(weights)
        out = []
        for _ in range(k):
            i = self.weighted_choice(w)
            out.append(i)
            w[i] = 0.0
        return out

    def shuffle(self, items: list) -> list:
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]
        return items
