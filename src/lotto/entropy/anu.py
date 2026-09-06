"""Australian National University quantum vacuum RNG (free legacy endpoint)."""
from __future__ import annotations
import time

import httpx

from .base import EntropySource

URL = "https://qrng.anu.edu.au/API/jsonI.php"


class AnuSource(EntropySource):
    key = "anu"
    label = "ANU quantum"
    icon = "ti-atom"
    online = True
    description = "Quantum vacuum fluctuations measured at ANU, Canberra."

    def gather(self, progress=None, n_bytes: int = 1024, **_) -> bytes:
        last = None
        for attempt in range(3):
            try:
                r = httpx.get(URL, params={"length": min(n_bytes, 1024), "type": "uint8"}, timeout=15)
                r.raise_for_status()
                j = r.json()
                if not j.get("success"):
                    raise RuntimeError(f"ANU API error: {j}")
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"ANU unreachable after 3 tries: {last}")
        data = bytes(j["data"])
        self._detail = f"{len(data)} quantum bytes"
        return data
