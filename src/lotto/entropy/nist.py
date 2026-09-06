"""NIST Randomness Beacon 2.0. Public and logged, so it is a mix-in only, never a sole source."""
from __future__ import annotations
import httpx

from .base import EntropySource

URL = "https://beacon.nist.gov/beacon/2.0/pulse/last"


class NistSource(EntropySource):
    key = "nist"
    label = "NIST beacon"
    icon = "ti-building-bank"
    online = True
    description = "512 signed public bits every 60 s from NIST. Mix-in only."

    def gather(self, progress=None, **_) -> bytes:
        r = httpx.get(URL, timeout=15)
        r.raise_for_status()
        p = r.json()["pulse"]
        data = bytes.fromhex(p["outputValue"]) + bytes.fromhex(p["localRandomValue"])
        self._detail = f"pulse {p['pulseIndex']} at {p['timeStamp']}"
        self._extra = {"pulse_index": p["pulseIndex"], "pulse_time": p["timeStamp"]}
        return data
