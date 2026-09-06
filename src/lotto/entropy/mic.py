"""Microphone noise: records a short clip and hashes the least-significant bits."""
from __future__ import annotations

from .base import EntropySource


class MicSource(EntropySource):
    key = "mic"
    label = "Microphone"
    icon = "ti-microphone"
    description = "One second of microphone-array noise, low bits only."

    def gather(self, progress=None, seconds: float = 1.0, waveform=None, **_) -> bytes:
        import numpy as np
        import sounddevice as sd

        sr = 44100
        rec = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="int16", blocking=True)
        samples = rec.reshape(-1)
        if waveform is not None:
            step = max(1, len(samples) // 240)
            waveform([int(x) for x in samples[::step]])
        lsb = (samples & 0xFF).astype(np.uint8)
        rms = float(np.sqrt(np.mean(samples.astype(float) ** 2)))
        self._detail = f"{seconds:.1f}s at {sr} Hz, {len(lsb)} bytes, rms {rms:.0f}"
        self._extra = {"rms": round(rms, 1)}
        return lsb.tobytes()
