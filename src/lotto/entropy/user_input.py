"""Sources whose bytes come from the browser: mouse wiggle and phrase seed."""
from __future__ import annotations
import hashlib

from .base import EntropySource


class MouseSource(EntropySource):
    key = "mouse"
    label = "Mouse wiggle"
    icon = "ti-mouse"
    is_input = True
    description = "Scribble on the pad; positions and timings are hashed."

    def gather(self, progress=None, events: list | None = None, **_) -> bytes:
        if not events or len(events) < 20:
            raise RuntimeError("need at least 20 mouse samples; scribble longer")
        raw = bytearray()
        for e in events:
            x, y, t = int(e[0]), int(e[1]), int(e[2])
            raw += (x & 0xFFFF).to_bytes(2, "big")
            raw += (y & 0xFFFF).to_bytes(2, "big")
            raw += (t & 0xFFFFFFFF).to_bytes(4, "big")
        self._detail = f"{len(events)} mouse samples"
        self._extra = {"samples": len(events)}
        return bytes(raw)


class FileSource(EntropySource):
    key = "file"
    label = "Uploaded file"
    icon = "ti-photo-up"
    is_input = True
    description = "A photo or document you upload. Images contribute pixel noise; anything else is hashed whole. Same file gives the same digest, so mix it with live sources."

    def gather(self, progress=None, data: bytes | None = None, filename: str = "", **_) -> bytes:
        if not data:
            raise RuntimeError("no file uploaded")
        if len(data) > 40 * 1024 * 1024:
            raise RuntimeError("file larger than 40 MB")
        kind = "document"
        raw = data
        try:
            import cv2
            import numpy as np

            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                lsb = (img & 0x03).astype(np.uint8)          # two low bits per channel = sensor noise
                raw = lsb.tobytes() + hashlib.sha256(data).digest()
                kind = f"image {img.shape[1]}x{img.shape[0]}"
        except Exception:  # noqa: BLE001
            pass
        self._detail = f"{filename or 'file'}: {kind}, {len(data):,} bytes"
        self._extra = {"filename": filename, "kind": kind}
        return raw


class BrowserCameraSource(EntropySource):
    """Frames captured by the visitor's browser (getUserMedia) and sent as JPEGs. Used in hosted mode."""
    key = "webcam"
    label = "Your camera"
    icon = "ti-camera"
    is_input = True
    description = "Frames from your browser's camera. Sensor noise between frames is hashed."

    def gather(self, progress=None, frames: list[bytes] | None = None, **_) -> bytes:
        if not frames or len(frames) < 2:
            raise RuntimeError("need at least 2 camera frames from the browser")
        import cv2
        import numpy as np

        chunks: list[bytes] = []
        prev = None
        noise = []
        for i, jpg in enumerate(frames):
            img = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            if prev is not None and prev.shape == img.shape:
                diff = cv2.absdiff(img, prev)
                lsb = (diff & 0x0F).astype(np.uint8)
                chunks.append(hashlib.sha256(lsb.tobytes()).digest())
                chunks.append(lsb[::5, ::5].tobytes())
                noise.append(float(diff.mean()))
            prev = img
            if progress:
                progress(i + 1, len(frames))
        raw = b"".join(chunks)
        if not raw:
            raise RuntimeError("could not decode camera frames")
        mean_noise = sum(noise) / len(noise) if noise else 0.0
        self._detail = f"{len(frames)} browser frames, {len(raw)} bytes of frame-diff noise, mean diff {mean_noise:.2f}"
        self._extra = {"frames": len(frames), "mean_noise": round(mean_noise, 2)}
        return raw


class BrowserMicSource(EntropySource):
    """Audio samples captured by the visitor's browser. Used in hosted mode."""
    key = "audio"
    label = "Your microphone"
    icon = "ti-microphone"
    is_input = True
    description = "A second of audio from your browser's microphone, low bits only."

    def gather(self, progress=None, samples: list[int] | None = None, **_) -> bytes:
        if not samples or len(samples) < 1000:
            raise RuntimeError("need at least 1000 audio samples from the browser")
        raw = bytes((int(s) & 0xFF) for s in samples)
        rms = (sum(int(s) ** 2 for s in samples) / len(samples)) ** 0.5
        self._detail = f"{len(samples)} browser samples, rms {rms:.0f}"
        self._extra = {"rms": round(rms, 1)}
        return raw


class PhraseSource(EntropySource):
    key = "phrase"
    label = "Phrase seed"
    icon = "ti-abc"
    is_input = True
    description = "A word, name, or date you type. A repeatable base that entropy then pulls."

    def gather(self, progress=None, phrase: str = "", **_) -> bytes:
        phrase = (phrase or "").strip()
        if not phrase:
            raise RuntimeError("phrase is empty")
        self._detail = f"phrase of {len(phrase)} characters"
        return hashlib.sha512(phrase.encode("utf-8")).digest()
