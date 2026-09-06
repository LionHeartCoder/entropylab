"""Combine independent sources into one 32-byte seed.

Each source is hashed on its own, the digests are concatenated in a fixed
order with a domain tag and a timestamp, and the result is hashed again.
Any one good source makes the seed unpredictable.
"""
from __future__ import annotations
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .anu import AnuSource
from .base import EntropySource, SourceResult
from .camera import CameraSource
from .cpu import CpuSource
from .mic import MicSource
from .nist import NistSource
import os

from .user_input import BrowserCameraSource, BrowserMicSource, FileSource, MouseSource, PhraseSource

HOSTED = os.environ.get("LOTTO_HOSTED", "").lower() in ("1", "true", "yes")

_local_devices = [CameraSource(0), CameraSource(1), MicSource()]
_browser_devices = [BrowserCameraSource(), BrowserMicSource()]
REGISTRY: dict[str, EntropySource] = {
    s.key: s
    for s in [
        CpuSource(),
        *(_browser_devices if HOSTED else _local_devices),
        AnuSource(),
        NistSource(),
        MouseSource(),
        FileSource(),
        PhraseSource(),
    ]
}
DEFAULT_SOURCES = ["cpu", "webcam", "audio", "anu", "nist"] if HOSTED else ["cpu", "camera", "mic", "anu", "nist"]


@dataclass
class EntropyPool:
    results: list[SourceResult]
    seed: bytes
    created: float = field(default_factory=time.time)

    @property
    def ok_sources(self) -> list[str]:
        return [r.key for r in self.results if r.ok]

    @property
    def failed_sources(self) -> list[str]:
        return [r.key for r in self.results if not r.ok]

    @property
    def bits_in(self) -> int:
        return sum(int(r.raw_len * r.entropy_bits_per_byte) for r in self.results if r.ok)

    def as_dict(self) -> dict:
        return {
            "seed": self.seed.hex(),
            "created": self.created,
            "bits_in": self.bits_in,
            "ok_sources": self.ok_sources,
            "failed_sources": self.failed_sources,
            "sources": [r.as_dict() for r in self.results],
        }


def combine(results: list[SourceResult], extra_tag: bytes = b"") -> bytes:
    h = hashlib.sha256()
    h.update(b"lotto-entropy-lab-v1\x00")
    h.update(str(time.time_ns()).encode())
    h.update(b"\x00" + extra_tag + b"\x00")
    for r in sorted((r for r in results if r.ok), key=lambda r: r.key):
        h.update(r.key.encode() + b"\x00" + r.digest)
    return h.digest()


def collect(
    keys: list[str],
    opts: dict | None = None,
    on_result=None,
    progress=None,
    parallel: bool = True,
) -> EntropyPool:
    """Gather from the requested sources (online ones in parallel) and combine."""
    opts = opts or {}
    keys = list(dict.fromkeys(keys))
    if not keys:
        raise ValueError("no entropy sources selected")
    sources = [REGISTRY[k] for k in keys if k in REGISTRY]
    unknown = [k for k in keys if k not in REGISTRY]
    if unknown:
        raise ValueError(f"unknown entropy source(s): {', '.join(unknown)}")
    results: list[SourceResult] = []

    def run(src: EntropySource) -> SourceResult:
        cb = (lambda i, n: progress(src.key, i, n)) if progress else None
        res = src.run(progress=cb, **opts.get(src.key, {}))
        if on_result:
            on_result(res)
        return res

    online = [s for s in sources if s.online]
    local = [s for s in sources if not s.online]
    if parallel and online:
        with ThreadPoolExecutor(max_workers=len(online)) as ex:
            futs = [ex.submit(run, s) for s in online]
            for s in local:
                results.append(run(s))
            for f in futs:
                results.append(f.result())
    else:
        for s in sources:
            results.append(run(s))

    if not any(r.ok for r in results):
        raise RuntimeError(
            "every entropy source failed: " + "; ".join(f"{r.key}: {r.error}" for r in results)
        )
    return EntropyPool(results=results, seed=combine(results))
