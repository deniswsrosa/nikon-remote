"""Expose-for-face against a simulated camera whose picture brightness follows ISO."""
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytest

from nikon_remote import assist as assist_mod
from nikon_remote.ptp import PropDesc

ISOS = [100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000, 12800]


def face_canvas(gain: float) -> bytes:
    """A synthetic presenter: skin-toned ellipse with eyes, on a dark background."""
    img = np.full((360, 640, 3), 8, np.uint8)
    skin = np.clip(np.array([120, 150, 190]) * gain, 0, 255).astype(np.uint8)
    cv2.ellipse(img, (320, 150), (55, 72), 0, 0, 360, tuple(int(c) for c in skin), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


@dataclass
class Frame:
    seq: int
    jpeg: bytes


@dataclass
class FakeCamera:
    iso: int = 800
    scene: float = 0.55  # brightness at ISO 800
    lv_on: bool = True
    seq: int = 0
    descs: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)

    def __post_init__(self):
        self.descs = {0xD1AA: PropDesc(0xD1AA, 6, True, self.iso, "enum", values=ISOS)}

    def _is_movie(self):
        return True

    def _value(self, code):
        return {0xD1AA: self.iso, 0xD0AD: 0}.get(code)

    def _emit(self, kind, payload):
        pass

    def latest_frame(self):
        self.seq += 1
        # gamma-encoded output: linear light scales with ISO
        return Frame(self.seq, face_canvas((self.scene * (self.iso / 800)) ** (1 / 2.2) / 0.55 ** (1 / 2.2)))

    def submit(self, name, *args):
        fut = Future()
        if name == "set":
            code, value = args
            self.iso = value
            self.descs[code].current = value
        fut.set_result({"value": args[-1]})
        return fut


@pytest.fixture
def fake_face(monkeypatch):
    """YuNet needs a real face; stand in with a detector that finds our ellipse by brightness."""

    def analyze(self, jpeg):
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        y = 0.0722 * img[..., 0] + 0.7152 * img[..., 1] + 0.2126 * img[..., 2]
        skin = y[120:180, 300:340]
        return {"found": True, "face_luma": round(float(np.median(skin)) / 255 * 100, 1), "eye_mid": [0.5, 0.4],
                "sharpness": 1.0, "face_clip": 0.0,
                "eye_line": 0.33, "center_x": 0.5, "head_top": 0.1, "face_height": 0.3}

    monkeypatch.setattr(assist_mod.FaceAnalyzer, "analyze", analyze)
    monkeypatch.setattr(assist_mod, "_load", lambda: dict(assist_mod.DEFAULTS))


@pytest.mark.parametrize("scene", [0.08, 0.55, 3.0])
def test_expose_for_face_converges(fake_face, scene):
    cam = FakeCamera(scene=scene)
    a = assist_mod.Assist(cam)
    a.start()
    try:
        result = a.expose_for_face()
    finally:
        a.stop()
    target = a.cfg["face_target"]
    assert result["ok"], result
    assert abs(result["face"] - target) <= 4  # one ISO step ≈ 3-4 points
    assert len(result["steps"]) <= 5  # converges quickly, no hunting


def test_expose_reports_when_iso_limit_reached(fake_face):
    cam = FakeCamera(scene=0.004)  # far too dark even at the ISO cap
    a = assist_mod.Assist(cam)
    a.start()
    try:
        result = a.expose_for_face()
    finally:
        a.stop()
    assert not result["ok"]
    assert result["iso"] == 6400
    assert "Add light" in result["message"]
