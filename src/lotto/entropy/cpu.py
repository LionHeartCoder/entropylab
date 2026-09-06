"""CPU / OS hardware RNG via Windows CNG (BCryptGenRandom), fed by RDSEED/RDRAND."""
from __future__ import annotations
import os

from .base import EntropySource


class CpuSource(EntropySource):
    key = "cpu"
    label = "CPU hardware RNG"
    icon = "ti-cpu"
    description = "Intel RDSEED/RDRAND through the Windows kernel generator."

    def gather(self, progress=None, n_bytes: int = 4096, **_) -> bytes:
        self._detail = f"{n_bytes} bytes from the kernel generator"
        return os.urandom(n_bytes)
