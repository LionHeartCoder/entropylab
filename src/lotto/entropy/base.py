from __future__ import annotations
import hashlib
import math
import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class SourceResult:
    key: str
    ok: bool
    raw_len: int = 0
    digest: bytes = b""
    entropy_bits_per_byte: float = 0.0
    elapsed_ms: int = 0
    detail: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "ok": self.ok,
            "raw_len": self.raw_len,
            "digest": self.digest.hex(),
            "entropy_bits_per_byte": round(self.entropy_bits_per_byte, 3),
            "elapsed_ms": self.elapsed_ms,
            "detail": self.detail,
            "error": self.error,
            **self.extra,
        }


def shannon_bits_per_byte(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in Counter(data).values())


class EntropySource:
    key: str = "base"
    label: str = "Base"
    icon: str = "ti-question-mark"
    description: str = ""
    online: bool = False
    is_input: bool = False  # bytes arrive from the browser (mouse wiggle, phrase)

    def gather(self, progress=None, **opts) -> bytes:
        raise NotImplementedError

    def run(self, progress=None, **opts) -> SourceResult:
        t0 = time.perf_counter()
        self._detail = ""
        self._extra = {}
        try:
            raw = self.gather(progress=progress, **opts)
            if not raw:
                raise RuntimeError("source returned no data")
            res = SourceResult(
                key=self.key,
                ok=True,
                raw_len=len(raw),
                digest=hashlib.sha256(self.key.encode() + b"\x00" + raw).digest(),
                entropy_bits_per_byte=shannon_bits_per_byte(raw),
                detail=self._detail,
                extra=self._extra,
            )
        except Exception as e:  # noqa: BLE001
            res = SourceResult(key=self.key, ok=False, error=f"{type(e).__name__}: {e}")
        res.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return res

    def info(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "icon": self.icon,
            "description": self.description,
            "online": self.online,
            "is_input": self.is_input,
        }
