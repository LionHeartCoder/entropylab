"""Webcam sensor noise, Cloudflare-lavarand style.

Grabs N frames, keeps the per-pixel differences between consecutive frames
(mostly sensor noise) and hashes them. Optionally hands JPEG previews to a
callback so the UI can show the capture live.
"""
from __future__ import annotations
import hashlib

from .base import EntropySource


class CameraSource(EntropySource):
    icon = "ti-camera"
    description = "Hashes sensor noise between consecutive webcam frames."

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.key = "camera" if device_index == 0 else f"camera{device_index}"
        self.label = "Front camera" if device_index == 0 else f"Camera {device_index}"
        if device_index == 1:
            self.icon = "ti-camera-rotate"

    def gather(self, progress=None, frames: int = 24, preview=None, **_) -> bytes:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.device_index)
        if not cap.isOpened():
            raise RuntimeError(f"camera {self.device_index} not available")
        try:
            chunks: list[bytes] = []
            prev = None
            for _ in range(3):  # let exposure settle
                cap.read()
            noise_levels = []
            for i in range(frames):
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev is not None:
                    diff = cv2.absdiff(gray, prev)
                    lsb = (diff & 0x0F).astype(np.uint8)  # low nibble is noise
                    chunks.append(hashlib.sha256(lsb.tobytes()).digest())
                    chunks.append(lsb[::7, ::7].tobytes())  # sparse raw sample
                    noise_levels.append(float(diff.mean()))
                prev = gray
                if preview is not None:
                    ok2, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                    if ok2:
                        preview(jpg.tobytes(), i + 1, frames)
                if progress:
                    progress(i + 1, frames)
            raw = b"".join(chunks)
            mean_noise = sum(noise_levels) / len(noise_levels) if noise_levels else 0.0
            self._detail = f"{frames} frames, {len(raw)} bytes of frame-diff noise, mean diff {mean_noise:.2f}"
            self._extra = {"frames": frames, "mean_noise": round(mean_noise, 2)}
            return raw
        finally:
            cap.release()


def list_cameras(max_index: int = 4) -> list[int]:
    import cv2

    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found
