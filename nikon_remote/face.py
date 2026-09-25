"""Face check: finds the presenter in the live view and judges exposure, focus,
framing and background separation from the actual pixels.

With a dark background the camera's exposure meter is misleading (the dark
wall drags it down), so exposure is judged on the face itself.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"

# Where a talking head usually looks right: eyes on the upper third line,
# face roughly centred.
EYE_LINE_TARGET = 1 / 3
EYE_LINE_TOLERANCE = 0.07
CENTER_TOLERANCE = 0.12


def _luma(img_bgr: np.ndarray) -> np.ndarray:
    b, g, r = img_bgr[..., 0], img_bgr[..., 1], img_bgr[..., 2]
    return 0.0722 * b + 0.7152 * g + 0.2126 * r


def _linear(y_percent: float) -> float:
    """Approximate scene-linear light from a gamma-encoded luma percentage."""
    return max(1e-4, (y_percent / 100.0) ** 2.2)


class FaceAnalyzer:
    def __init__(self):
        self._size = (0, 0)
        self._det = None
        self.focus_reference: float | None = None  # eye sharpness right after a successful AF

    def _detector(self, w: int, h: int):
        if self._det is None or self._size != (w, h):
            self._det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.7, 0.3, 50)
            self._size = (w, h)
        return self._det

    def analyze(self, jpeg: bytes) -> dict:
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return {"found": False}
        h, w = img.shape[:2]
        _, faces = self._detector(w, h).detect(img)
        if faces is None or len(faces) == 0:
            return {"found": False}
        # The biggest face is the presenter.
        f = max(faces, key=lambda r: r[2] * r[3])
        x, y, fw, fh = (float(v) for v in f[:4])
        eyes = [(float(f[4]), float(f[5])), (float(f[6]), float(f[7]))]
        y_img = _luma(img.astype(np.float32))

        # Skin: the middle of the face box (cheeks/nose/forehead), avoiding hair and background.
        sx0, sx1 = int(x + 0.22 * fw), int(x + 0.78 * fw)
        sy0, sy1 = int(y + 0.18 * fh), int(y + 0.80 * fh)
        skin = y_img[max(0, sy0):max(1, sy1), max(0, sx0):max(1, sx1)]
        if skin.size < 50:
            return {"found": False}
        face_luma = float(np.median(skin)) / 255 * 100
        face_clip = float((skin >= 250).mean())

        # Background: everything outside a generous person silhouette (face box widened
        # and extended down to the bottom of the frame for the shoulders/body).
        mask = np.ones((h, w), bool)
        px0, px1 = int(x - 0.9 * fw), int(x + 1.9 * fw)
        py0 = int(y - 0.45 * fh)
        mask[max(0, py0):h, max(0, px0):min(w, px1)] = False
        bg = y_img[mask]
        bg_luma = float(np.median(bg)) / 255 * 100 if bg.size > 500 else None
        separation = None
        if bg_luma is not None:
            separation = round(math.log2(_linear(face_luma) / _linear(max(bg_luma, 0.5))), 2)

        # Focus: Laplacian energy around the eyes, normalised by local contrast so
        # it doesn't simply track brightness.
        ex = int(min(eyes[0][0], eyes[1][0]) - 0.15 * fw)
        ex1 = int(max(eyes[0][0], eyes[1][0]) + 0.15 * fw)
        ey = int(min(eyes[0][1], eyes[1][1]) - 0.12 * fh)
        ey1 = int(max(eyes[0][1], eyes[1][1]) + 0.12 * fh)
        eye_region = y_img[max(0, ey):max(1, ey1), max(0, ex):max(1, ex1)]
        sharpness = None
        if eye_region.size > 100:
            lap = cv2.Laplacian(eye_region, cv2.CV_32F)
            contrast = float(eye_region.std()) + 1.0
            sharpness = round(float(lap.var()) / (contrast * contrast), 4)

        eye_mid = ((eyes[0][0] + eyes[1][0]) / 2 / w, (eyes[0][1] + eyes[1][1]) / 2 / h)
        center_x = (x + fw / 2) / w
        return {
            "found": True,
            "score": round(float(f[14]), 2),
            "box": [round(x / w, 4), round(y / h, 4), round(fw / w, 4), round(fh / h, 4)],
            "eyes": [[round(ex_ / w, 4), round(ey_ / h, 4)] for ex_, ey_ in eyes],
            "eye_mid": [round(eye_mid[0], 4), round(eye_mid[1], 4)],
            "face_luma": round(face_luma, 1),
            "face_clip": round(face_clip, 3),
            "bg_luma": round(bg_luma, 1) if bg_luma is not None else None,
            "separation_stops": separation,
            "sharpness": sharpness,
            "focus_ratio": round(sharpness / self.focus_reference, 2)
            if sharpness and self.focus_reference
            else None,
            "eye_line": round(eye_mid[1], 3),
            "center_x": round(center_x, 3),
            "head_top": round(max(0.0, (y - 0.3 * fh) / h), 3),
            "face_height": round(fh / h, 3),
        }


def framing_advice(a: dict) -> list[str]:
    """Plain-language framing hints for a centred talking head."""
    tips = []
    if not a.get("found"):
        return tips
    d = a["eye_line"] - EYE_LINE_TARGET
    if d > EYE_LINE_TOLERANCE:
        tips.append("Eyes are low in the frame — tilt the camera down slightly (or lower it) so your eyes sit on the upper third line")
    elif d < -EYE_LINE_TOLERANCE:
        tips.append("Eyes are high in the frame — tilt the camera up slightly (or raise it) so your eyes sit on the upper third line")
    if abs(a["center_x"] - 0.5) > CENTER_TOLERANCE:
        side = "left" if a["center_x"] < 0.5 else "right"
        tips.append(f"You're off to the {side} — pan the camera or move to the centre")
    if a["head_top"] < 0.01:
        tips.append("The top of your head is cut off — tilt up or zoom out a little")
    if a["face_height"] < 0.14:
        tips.append("You look small in the frame — zoom in or move closer (face about 1/5 of the frame height works well)")
    elif a["face_height"] > 0.42:
        tips.append("Very tight framing — zoom out a little so your shoulders are in the shot")
    return tips
