"""Recording assistants that sit on top of the camera service: face check
(exposure/focus/framing on the presenter) and session information."""

from __future__ import annotations

import json
import logging
import math
import shutil
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from .camera import CameraService, UserError
from .face import FaceAnalyzer, framing_advice

log = logging.getLogger("nikon_remote.assist")

CONFIG = Path.home() / ".config" / "nikon-remote" / "assist.json"
DEFAULTS = {
    "face_target": 58.0,  # face brightness (% luma) that looks right; user can "remember" their own
    "max_iso": 6400,
    "record_dir": str(Path.home() / "Videos"),
    "record_mbps": 40,  # typical OBS 1080p30 recording bitrate, for the disk-space estimate
}


def _load() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def _save(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2))


class Assist:
    def __init__(self, camera: CameraService):
        self.cam = camera
        self.cfg = _load()
        self.analyzer = FaceAnalyzer()
        self.face: dict = {"found": False}
        self._last_seq = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._focus_mark_at: float | None = None
        self._battery_hist: list[tuple[float, int]] = []
        self._next_session = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="assist", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _emit(self, kind: str, payload) -> None:
        self.cam._emit(kind, payload)

    # -- loop ---------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_face()
                if time.monotonic() >= self._next_session:
                    self._tick_session()
                    self._next_session = time.monotonic() + 5
            except Exception:
                log.exception("assist tick failed")
            time.sleep(0.3)

    def _tick_face(self) -> None:
        frame = self.cam.latest_frame()
        if frame is None or frame.seq == self._last_seq or not self.cam.lv_on:
            return
        self._last_seq = frame.seq
        a = self.analyzer.analyze(frame.jpeg)
        if a.get("found") and self._focus_mark_at and time.monotonic() >= self._focus_mark_at:
            # Remember how sharp the eyes are right after a successful AF.
            self.analyzer.focus_reference = a.get("sharpness")
            self._focus_mark_at = None
            a["focus_ratio"] = 1.0 if a.get("sharpness") else None
        a["framing"] = framing_advice(a)
        a["target"] = self.cfg["face_target"]
        self.face = a
        self._emit("face", a)

    def _tick_session(self) -> None:
        st = self.cam.status
        info: dict = {}
        bat = st.get("battery")
        now = time.monotonic()
        if bat is not None and not st.get("ac_power"):
            if self._battery_hist and bat > self._battery_hist[-1][1] + 2:
                self._battery_hist.clear()  # battery swapped or charged
            self._battery_hist.append((now, bat))
            self._battery_hist = [(t, b) for t, b in self._battery_hist if now - t < 1800]
            t0, b0 = self._battery_hist[0]
            if now - t0 > 300 and b0 > bat:
                rate = (b0 - bat) / ((now - t0) / 60)  # % per minute
                info["battery_minutes"] = int(bat / rate)
        try:
            path = Path(self.cfg["record_dir"]).expanduser()
            while not path.exists() and path != path.parent:
                path = path.parent
            free = shutil.disk_usage(path).free
            info["disk_free_gb"] = round(free / 1e9, 1)
            info["disk_minutes"] = int(free * 8 / (self.cfg["record_mbps"] * 1e6) / 60)
            info["record_dir"] = self.cfg["record_dir"]
        except OSError:
            pass
        self._emit("session", info)

    def mark_focus_soon(self) -> None:
        self._focus_mark_at = time.monotonic() + 0.8

    # -- commands (run on a worker thread by the server) ----------------------
    def _wait(self, fut: Future, timeout: float = 10):
        return fut.result(timeout=timeout)

    def _fresh_face(self, n: int = 3, timeout: float = 4.0) -> list[dict]:
        seen, out, end = self._last_seq, [], time.monotonic() + timeout
        while len(out) < n and time.monotonic() < end:
            time.sleep(0.1)
            if self._last_seq != seen:
                seen = self._last_seq
                if self.face.get("found"):
                    out.append(self.face)
        return out

    def focus_eyes(self) -> dict:
        faces = self._fresh_face(1)
        if not faces:
            raise UserError("No face found in the preview — sit in front of the camera first")
        fx, fy = faces[0]["eye_mid"]
        res = self._wait(self.cam.submit("focus_at", fx, fy, True), 12)
        if res.get("focused"):
            self.mark_focus_soon()
        return res

    def remember_brightness(self) -> dict:
        faces = self._fresh_face(3)
        if not faces:
            raise UserError("No face found in the preview")
        target = round(sum(f["face_luma"] for f in faces) / len(faces), 1)
        self.cfg["face_target"] = target
        _save(self.cfg)
        return {"target": target}

    def set_config(self, key: str, value) -> dict:
        if key not in DEFAULTS:
            raise UserError("Unknown setting")
        self.cfg[key] = type(DEFAULTS[key])(value)
        _save(self.cfg)
        self._next_session = 0
        return {key: self.cfg[key]}

    def expose_for_face(self) -> dict:
        if not self._busy.acquire(blocking=False):
            raise UserError("Already adjusting exposure")
        try:
            return self._expose()
        finally:
            self._busy.release()

    def _expose(self) -> dict:
        cam = self.cam
        movie = cam._is_movie()
        if not movie and cam._value(0xD1A5) != 1:
            raise UserError("Photo live view is auto-brightened — switch to Movie (or turn on exposure preview) first")
        iso_code = 0xD1AA if movie else 0x500F
        auto_code = 0xD0AD if movie else 0xD16A
        if cam._value(auto_code) == 1:
            self._wait(cam.submit("set", auto_code, 0))
        target = self.cfg["face_target"]
        steps = []
        for _ in range(7):
            faces = self._fresh_face(3)
            if not faces:
                raise UserError("Lost the face — stay in frame while it adjusts")
            luma = sum(f["face_luma"] for f in faces) / len(faces)
            err = target - luma
            steps.append(round(luma, 1))
            # One ISO step (1/3 stop) moves face brightness ~3-4 points, so ±4 is as close as ISO can get.
            if abs(err) <= 4:
                return {"ok": True, "iso": cam._value(iso_code), "face": round(luma, 1), "target": target, "steps": steps}
            desc = cam.descs[iso_code]
            iso = cam._value(iso_code)
            # Luma is gamma-encoded (~2.2); damp the correction so it converges without overshoot.
            stops = max(-3.0, min(3.0, 2.2 * math.log2(max(target, 1) / max(luma, 1)) * 0.8))
            want = iso * 2 ** stops
            allowed = [v for v in desc.values if 100 <= v <= self.cfg["max_iso"]]
            new = min(allowed, key=lambda v: abs(math.log2(v / want)))
            if new == iso:
                # Rounded back to the current ISO: take one step in the needed direction if there is one.
                ladder = sorted(allowed)
                i = ladder.index(iso) if iso in ladder else min(range(len(ladder)), key=lambda k: abs(ladder[k] - iso))
                j = i + (1 if err > 0 else -1)
                if 0 <= j < len(ladder):
                    new = ladder[j]
            if new == iso:
                if err > 0:
                    msg = (f"Face is still dark at ISO {iso} (the limit set for noise). Add light on your face, "
                           "open the aperture, or raise the ISO limit.")
                else:
                    msg = f"Face is still bright at ISO {iso}. Reduce the light on your face or close the aperture a little."
                return {"ok": False, "iso": iso, "face": round(luma, 1), "target": target, "steps": steps, "message": msg}
            self._wait(cam.submit("set", iso_code, new))
            time.sleep(0.6)
        return {"ok": False, "iso": cam._value(iso_code), "target": target, "steps": steps,
                "message": "Couldn't settle — is the light changing?"}
