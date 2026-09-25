"""Camera service: one thread owns the USB session and everything else talks to it.

Commands are queued and run between live view frames. Autofocus and manual
focus are non-blocking so the preview keeps updating while the lens moves.
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import re
import subprocess
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable

import usb.core

from . import catalog
from .ptp import (
    DT_STR,
    EC_DevicePropChanged,
    EC_NIKON_LiveViewStateChanged,
    EC_NIKON_MovieRecordComplete,
    EC_NIKON_MovieRecordInterrupted,
    EC_NIKON_MovieRecordStarted,
    EC_ObjectAdded,
    OC_NIKON_AfDrive,
    OC_NIKON_MfDrive,
    RC_DeviceBusy,
    RC_OK,
    DisconnectedError,
    PropDesc,
    PTPCamera,
    PTPError,
)

log = logging.getLogger("nikon_remote.camera")

RC_NotLiveView = 0xA00B
REC_BIT = 1 << 10  # MovRecProhibitCondition: "already recording"
BODY_ONLY_BIT = 1 << 14  # "not in application mode": set ApplicationMode=1 (live view off) to clear it
RC_OutOfFocus = 0xA002
RC_MfDriveStepEnd = 0xA00C
# After an end stop the D7500 answers "step insufficiency" to further moves that way.
RC_MfDriveStepInsufficiency = 0xA00E
MF_LIMIT_CODES = (RC_MfDriveStepEnd, RC_MfDriveStepInsufficiency)

CATALOG_CODES = [s.code for s in catalog.SETTINGS]
PC_MODE_CODES = {s.code for s in catalog.SETTINGS if s.pc_mode}
# Changing any of these can change which other settings are available.
# ApplicationMode (0xD1F0) must be 1 for the D7500 to start a movie from USB
# (MovRecProhibitCondition bit 14 otherwise). The camera only accepts it with
# live view OFF and resets it when the USB session closes; written while live
# view runs it hangs the connection — so only the service sets it, never the UI.
APPLICATION_MODE = 0xD1F0
UNSAFE_CODES = {APPLICATION_MODE: "Set automatically by the app (the camera only accepts it with live view off)"}
CASCADE_CODES = {0x500E, 0xD1A6, 0xD0A0, 0xD0AD, 0xD16A, 0xD061, 0xD05D}
LV_ZOOM = 0xD1A3


class UserError(Exception):
    """An error meant to be shown to the user as-is."""


def release_gvfs() -> None:
    """GNOME auto-mounts cameras, which locks the USB device. Unmount it."""
    try:
        out = subprocess.run(["gio", "mount", "-l"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    for uri in set(re.findall(r"(gphoto2://\S+?/)", out)):
        subprocess.run(["gio", "mount", "-u", uri], capture_output=True, timeout=10)


def desc_json(d: PropDesc) -> dict:
    out = {"v": d.current, "w": d.writable, "dt": d.dtype, "form": d.form}
    if d.form == "enum":
        out["vals"] = d.values
    elif d.form == "range":
        out["min"], out["max"], out["step"] = d.minimum, d.maximum, d.step
    return out


@dataclass
class Frame:
    seq: int
    jpeg: bytes
    header: dict
    t: float


@dataclass
class _BusyOp:
    kind: str  # "af" | "mf"
    future: Future
    started: float
    timeout: float


class CameraService:
    def __init__(self):
        self.cam: PTPCamera | None = None
        self.descs: dict[int, PropDesc] = {}
        self._cmds: queue.Queue = queue.Queue()
        self._listeners: list[Callable[[str, object], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.viewers = 0
        self.want_lv = True
        self.lv_on = False
        self.pc_mode = False
        self.recording = False
        self.rec_started: float | None = None
        self.af_point: tuple[int, int] | None = None
        # The camera resets the Lv selector to the physical switch whenever live
        # view restarts, so remember what the user picked and re-apply it.
        self.desired_selector: int | None = None
        self._lv_started_at = 0.0
        self._next_frame_at = 0.0
        self._last_jpeg: bytes | None = None
        self._last_emit = 0.0
        self._busy_since: float | None = None
        self._recoveries = 0
        self.app_mode = False

        self._frame: Frame | None = None
        self._frame_lock = threading.Lock()
        self._seq = 0
        self._busy: _BusyOp | None = None
        self._rec_bit_seen = False
        self._dirty: set[int] = set()
        self._rr_catalog = 0
        self._rr_all = 0
        self._next_events = 0.0
        self._next_status = 0.0
        self._next_refresh = 0.0
        self._next_connect = 0.0
        self._next_lv_try = 0.0
        self._lv_idle_since: float | None = None
        self._usb_errors = 0
        self._fps_t0 = time.monotonic()
        self._fps_n = 0

        self.status: dict = {
            "connected": False,
            "message": "Looking for the camera…",
            "model": None,
            "serial": None,
            "firmware": None,
            "lv": False,
            "lv_error": None,
            "recording": False,
            "rec_elapsed": 0,
            "pc_mode": False,
            "fps": 0,
            "movie_prohibit": [],
            "last_clip": None,
        }

    # -- public API (any thread) -------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=8)

    def add_listener(self, fn: Callable[[str, object], None]) -> None:
        self._listeners.append(fn)

    def latest_frame(self) -> Frame | None:
        with self._frame_lock:
            return self._frame

    def submit(self, name: str, *args) -> Future:
        fut: Future = Future()
        self._cmds.put((name, args, fut))
        return fut

    def snapshot(self) -> dict:
        return {
            "props": {c: desc_json(d) for c, d in list(self.descs.items())},
            "status": dict(self.status),
        }

    # -- plumbing ----------------------------------------------------------
    def _emit(self, kind: str, payload: object) -> None:
        for fn in list(self._listeners):
            try:
                fn(kind, payload)
            except Exception:
                log.exception("listener failed")

    def _set_status(self, **kw) -> None:
        changed = {k: v for k, v in kw.items() if self.status.get(k) != v}
        if changed:
            self.status.update(changed)
            self._emit("status", changed)

    def _toast(self, text: str, level: str = "info") -> None:
        self._emit("toast", {"text": text, "level": level})

    # -- main loop ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            if self.cam is None:
                self._fail_pending_commands()
                if time.monotonic() >= self._next_connect:
                    self._connect()
                else:
                    time.sleep(0.2)
                continue
            try:
                self._process_commands()
                self._tick_busy()
                self._tick_liveview()
                now = time.monotonic()
                if now >= self._next_events:
                    self._tick_events()
                    self._next_events = now + 0.15
                if now >= self._next_status:
                    self._tick_status()
                    self._next_status = now + 1.0
                if now >= self._next_refresh:
                    self._tick_refresh()
                    self._next_refresh = now + 0.25
                if not self.lv_on:
                    time.sleep(0.03)
                self._usb_errors = 0
            except DisconnectedError as e:
                self._on_disconnect(str(e))
            except usb.core.USBError as e:
                # Any USB error can leave a half-read PTP container in the pipe;
                # a fresh session is the only reliable way back in sync.
                log.warning("USB error: %s — reconnecting", e)
                self._on_disconnect(f"USB communication hiccup ({e}) — reconnecting…")
                self._next_connect = time.monotonic() + 0.3
            except PTPError as e:
                log.warning("PTP error in loop: %s", e)
                time.sleep(0.05)
            except Exception:
                log.exception("unexpected error in camera loop")
                time.sleep(0.2)
        self._shutdown()

    def _connect(self) -> None:
        self._next_connect = time.monotonic() + 2.0
        release_gvfs()
        cam = PTPCamera()
        try:
            cam.open()
        except DisconnectedError as e:
            self._set_status(connected=False, message=str(e))
            return
        except Exception as e:
            log.warning("connect failed: %s", e)
            self._set_status(connected=False, message=f"Could not open the camera: {e}")
            return
        self.cam = cam
        self.lv_on = False
        self.recording = False
        if cam.device_ready() == RC_DeviceBusy:
            cam.cancel_af()  # a focus drive left stuck from before would block everything
        # Never disturb a take in progress (e.g. reconnecting after a USB hiccup):
        # keep live view running and pick the recording back up.
        try:
            lv_running = bool(cam.get_prop(0xD1A2, 2))
            recording = lv_running and bool(cam.get_prop(0xD0A4, 6) & REC_BIT)
        except Exception:
            lv_running = recording = False
        if lv_running:
            self.lv_on = True
            self._lv_started_at = time.monotonic()
        if recording:
            self._recording_started()
            self._rec_bit_seen = True
        elif not lv_running:
            try:
                cam.set_camera_mode(False)
            except Exception:
                pass
        self.pc_mode = False
        self.app_mode = False
        if not lv_running:
            self._ensure_app_mode()
        self._load_all_descs()
        info = cam.info
        self._set_status(
            connected=True,
            message=None,
            model=info.model,
            serial=info.serial.lstrip("0"),
            firmware=info.version,
            pc_mode=False,
            recording=self.recording,
            lv=self.lv_on,
        )
        self._emit("props", {c: desc_json(d) for c, d in self.descs.items()})
        self._tick_status()
        log.info("connected to %s", info.model)

    def _on_disconnect(self, reason: str) -> None:
        log.warning("camera disconnected: %s", reason)
        if self.cam:
            try:
                self.cam.close()
            except Exception:
                pass
        self.cam = None
        self.lv_on = False
        self.recording = False
        if self._busy:
            self._busy.future.set_exception(UserError("Camera disconnected"))
            self._busy = None
        self._next_connect = time.monotonic() + 1.0
        self._set_status(
            connected=False,
            lv=False,
            recording=False,
            message="Camera disconnected — check the cable and that the camera is on.",
        )

    def _shutdown(self) -> None:
        cam = self.cam
        if not cam:
            return
        try:
            if self.recording:
                cam.stop_movie()
            if self.lv_on:
                cam.end_liveview()
            if self.pc_mode:
                cam.set_camera_mode(False)
        except Exception:
            pass
        cam.close()
        self.cam = None

    def _fail_pending_commands(self) -> None:
        while True:
            try:
                _, _, fut = self._cmds.get_nowait()
            except queue.Empty:
                return
            fut.set_exception(UserError("Camera is not connected"))

    # -- properties --------------------------------------------------------
    def _load_all_descs(self) -> None:
        cam = self.cam
        for code in cam.all_property_codes():
            try:
                self.descs[code] = cam.get_prop_desc(code)
            except PTPError:
                pass

    def _reload(self, codes) -> None:
        changed = {}
        for code in codes:
            try:
                d = self.cam.get_prop_desc(code)
            except PTPError:
                continue
            old = self.descs.get(code)
            self.descs[code] = d
            if old is None or desc_json(old) != desc_json(d):
                changed[code] = desc_json(d)
        if changed:
            self._emit("props", changed)
            if 0xD1A6 in changed or 0x500E in changed:
                self._reload_catalog_soon()

    def _reload_catalog_soon(self) -> None:
        self._dirty.update(CATALOG_CODES)

    def _value(self, code: int, default=None):
        d = self.descs.get(code)
        return d.current if d else default

    def _is_movie(self) -> bool:
        return self._value(0xD1A6) == 1

    # -- periodic work -----------------------------------------------------
    def _tick_events(self) -> None:
        cam = self.cam
        for code, param in cam.get_events():
            if code == EC_DevicePropChanged:
                self._dirty.add(param)
                if param == 0xD1A6 and self.lv_on and time.monotonic() - self._lv_started_at > 2:
                    self._follow_selector = True
            elif code == EC_NIKON_MovieRecordStarted:
                self._recording_started()
            elif code == EC_NIKON_MovieRecordComplete:
                self._recording_stopped(None)
            elif code == EC_NIKON_MovieRecordInterrupted:
                self._recording_stopped(f"Recording stopped by the camera (code 0x{param:x})")
            elif code == EC_ObjectAdded:
                try:
                    info = cam.get_object_info(param)
                    self._set_status(last_clip={"name": info["filename"], "size": info["size"]})
                except PTPError:
                    pass
            elif code == EC_NIKON_LiveViewStateChanged:
                self._dirty.add(0xD1A2)
        if self._dirty:
            dirty, self._dirty = self._dirty, set()
            self._reload(sorted(dirty))
        if getattr(self, "_follow_selector", False):
            # The user flipped the physical Lv switch: that becomes the new choice.
            self._follow_selector = False
            self.desired_selector = self._value(0xD1A6)

    def _tick_refresh(self) -> None:
        """Safety net for changes the camera doesn't announce: re-read a few
        catalog properties and one other property per tick."""
        codes = []
        for _ in range(3):
            codes.append(CATALOG_CODES[self._rr_catalog % len(CATALOG_CODES)])
            self._rr_catalog += 1
        others = [c for c in self.descs if c not in CATALOG_CODES]
        if others:
            codes.append(others[self._rr_all % len(others)])
            self._rr_all += 1
        self._reload(codes)

    def _tick_status(self) -> None:
        cam = self.cam
        vals = {}
        for key, code in catalog.STATUS_CODES.items():
            d = self.descs.get(code)
            if d is None:
                continue
            try:
                vals[key] = cam.get_prop(code, d.dtype)
            except PTPError:
                continue
        prohibit = vals.get("movie_prohibit", 0) or 0
        lv_prohibit = vals.get("lv_prohibit", 0) or 0
        # The D7500 doesn't send movie start/stop events, so also follow the
        # "already recording" bit: catches takes started/stopped on the body.
        if self.lv_on and "movie_prohibit" in vals:
            rec_bit = bool(prohibit & REC_BIT)
            if rec_bit and not self.recording:
                self._recording_started()
            if rec_bit:
                self._rec_bit_seen = True
            elif self.recording and self._rec_bit_seen:
                self._recording_stopped(None)
        self._set_status(
            battery=vals.get("battery"),
            remaining_shots=vals.get("remaining_shots"),
            meter=vals.get("meter"),
            focal_length=vals.get("focal_length"),
            focal_min=vals.get("focal_min"),
            focal_max=vals.get("focal_max"),
            ac_power=bool(vals.get("ac_power")),
            af_lock=bool(vals.get("af_lock")),
            movie_prohibit=catalog.decode_bits(prohibit, catalog.MOVIE_PROHIBIT_BITS)
            if not self.recording
            else [],
            lv_prohibit=catalog.decode_bits(lv_prohibit, catalog.LV_PROHIBIT_BITS),
            rec_elapsed=int(time.monotonic() - self.rec_started) if self.recording and self.rec_started else 0,
        )
        if self.lv_on:
            now = time.monotonic()
            elapsed = now - self._fps_t0
            if elapsed >= 1.0:
                self._set_status(fps=round(self._fps_n / elapsed, 1))
                self._fps_t0, self._fps_n = now, 0

    # -- live view ---------------------------------------------------------
    def _tick_liveview(self) -> None:
        cam = self.cam
        want = self.want_lv and (self.viewers > 0 or self.recording)
        now = time.monotonic()
        if not want:
            if self.lv_on and not self.recording:
                if self._lv_idle_since is None:
                    self._lv_idle_since = now
                elif now - self._lv_idle_since > 5:
                    self._end_lv()
            return
        self._lv_idle_since = None
        if not self.lv_on:
            if now >= self._next_lv_try:
                self._start_lv()
            return
        if now < self._next_frame_at:
            time.sleep(min(0.01, self._next_frame_at - now))
            return
        self._next_frame_at = now + 1 / 30
        try:
            f = cam.get_liveview()
        except PTPError as e:
            if e.code == RC_DeviceBusy:
                # Normal for a frame or two; if it never clears the camera's live view is stuck
                # (seen on the D7500) — restart it instead of waiting forever.
                if self._busy_since is None:
                    self._busy_since = now
                elif now - self._busy_since > 2.0 and self._busy is None:
                    self._busy_since = None
                    self._recoveries += 1
                    if self._recoveries % 2 == 1:
                        log.warning("live view stuck busy for 2 s — cancelling a stuck focus drive")
                        cam.cancel_af()
                    else:
                        log.warning("still stuck — restarting live view")
                        if not self._unstick():
                            self._end_lv()
                            self._next_lv_try = now + 10.0
                time.sleep(0.005)
                return
            if e.code == RC_NotLiveView:
                self.lv_on = False
                self._set_status(lv=False)
                self._next_lv_try = now + 0.5
                return
            raise
        self._busy_since = None
        self._recoveries = 0
        if f.jpeg == self._last_jpeg and now - self._last_emit < 0.5:
            return  # same picture as last time (camera hasn't refreshed, or a static dark scene)
        self._last_jpeg = f.jpeg
        self._last_emit = now
        self._seq += 1
        self._fps_n += 1
        with self._frame_lock:
            self._frame = Frame(self._seq, f.jpeg, f.header, time.time())
        self._emit("frame", self._seq)

    def _ensure_app_mode(self) -> bool:
        """Put the D7500 in application mode (needed to record from USB). Live view must be off."""
        cam = self.cam
        try:
            if cam.get_prop(APPLICATION_MODE, 2) == 1:
                self.app_mode = True
                return True
            cam.set_prop(APPLICATION_MODE, 1, 2, timeout=8000)
            self.app_mode = cam.get_prop(APPLICATION_MODE, 2) == 1
        except (PTPError, usb.core.USBTimeoutError) as e:
            log.warning("couldn't set application mode: %s", e)
            self.app_mode = False
        return self.app_mode

    def _start_lv(self) -> None:
        cam = self.cam
        self._next_lv_try = time.monotonic() + 2.0
        try:
            cond = cam.get_prop(0xD1A4, 6)
        except PTPError:
            cond = 0
        if APPLICATION_MODE in self.descs and not self.app_mode:
            self._ensure_app_mode()
        # bit 24 (lens retracting) is transient and harmless
        if cond & ~(1 << 24):
            reasons = catalog.decode_bits(cond, catalog.LV_PROHIBIT_BITS)
            self._set_status(lv=False, lv_error="Live view blocked: " + "; ".join(reasons))
            return
        try:
            cam.start_liveview()
        except PTPError as e:
            if e.code != RC_DeviceBusy:
                self._set_status(lv=False, lv_error=f"Live view could not start: {e}")
                return
            log.warning("camera busy when starting live view — cancelling a stuck focus drive and retrying")
            if not self._unstick():
                self._next_lv_try = time.monotonic() + 10  # back off; don't hammer a busy camera
                self._set_status(lv=False, lv_error="The camera is busy — close any menu or playback on the camera. "
                                 "If it stays like this, switch the camera off and on.")
                return
        self.lv_on = True
        self._lv_started_at = time.monotonic()
        want = self.desired_selector
        if want is not None and self._value(0xD1A6) != want:
            try:
                self._retry_busy(cam.set_prop, 0xD1A6, want, 2)
                self._dirty.update(CATALOG_CODES)
            except PTPError as e:
                log.warning("could not restore Lv selector: %s", e)
        self._fps_t0, self._fps_n = time.monotonic(), 0
        self._set_status(lv=True, lv_error=None)
        self._dirty.update([0xD1A2, LV_ZOOM])

    def _unstick(self) -> bool:
        """Recover a D7500 stuck 'busy' (a focus drive that never finished): cancel AF,
        end live view, pause, start it again. Verified on the camera."""
        cam = self.cam
        cam.cancel_af()
        if cam.wait_ready(5.0, 0.2) != RC_OK:
            return False  # still busy: leave it alone (menus open on the body also do this)
        try:
            cam.end_liveview()
        except PTPError:
            pass
        time.sleep(2.0)
        try:
            cam.start_liveview()
            return True
        except PTPError as e:
            log.warning("unstick attempt failed: %s", e)
            return False

    def _end_lv(self) -> None:
        if self._busy is not None:
            self._busy.future.set_exception(UserError("Live view restarted"))
            self._busy = None
        try:
            self.cam.end_liveview()
        except PTPError:
            pass
        self.lv_on = False
        self._set_status(lv=False, fps=0)

    # -- busy operations (AF / MF) -----------------------------------------
    def _tick_busy(self) -> None:
        op = self._busy
        if op is None:
            return
        rc = self.cam.device_ready()
        if rc == RC_DeviceBusy and time.monotonic() - op.started < op.timeout:
            return
        self._busy = None
        if op.kind == "af":
            if rc == RC_OK:
                op.future.set_result({"focused": True})
            elif rc == RC_OutOfFocus:
                op.future.set_result({"focused": False})
            elif rc == RC_DeviceBusy:
                op.future.set_exception(UserError("Autofocus timed out"))
            else:
                op.future.set_exception(PTPError(rc, OC_NIKON_AfDrive))
            self._dirty.add(0xD104)
        else:
            if rc in (RC_OK,):
                op.future.set_result({"ok": True})
            elif rc in MF_LIMIT_CODES:
                op.future.set_result({"ok": True, "limit": True})
            else:
                op.future.set_exception(PTPError(rc, OC_NIKON_MfDrive))

    # -- recording state ---------------------------------------------------
    def _recording_started(self) -> None:
        if not self.recording:
            self._rec_bit_seen = False
            self.recording = True
            self.rec_started = time.monotonic()
            self._set_status(recording=True, rec_elapsed=0, movie_prohibit=[])

    def _recording_stopped(self, error: str | None) -> None:
        if self.recording:
            self.recording = False
            self.rec_started = None
            self._set_status(recording=False, rec_elapsed=0)
            if error:
                self._toast(error, "error")

    # -- commands ----------------------------------------------------------
    def _process_commands(self) -> None:
        while True:
            try:
                name, args, fut = self._cmds.get_nowait()
            except queue.Empty:
                return
            if fut.set_running_or_notify_cancel() is False:
                continue
            handler = getattr(self, "_cmd_" + name, None)
            try:
                if handler is None:
                    raise UserError(f"Unknown command {name}")
                result = handler(fut, *args)
                if result is not _PENDING:
                    fut.set_result(result)
            except (DisconnectedError, usb.core.USBError):
                fut.set_exception(UserError("Camera disconnected"))
                raise
            except Exception as e:
                fut.set_exception(e)

    def _retry_busy(self, fn, *args, attempts: int = 40):
        for i in range(attempts):
            try:
                return fn(*args)
            except PTPError as e:
                if e.code != RC_DeviceBusy or i == attempts - 1:
                    raise
                time.sleep(0.05)

    def _cmd_set(self, fut, code: int, value):
        cam = self.cam
        code = int(code)
        if code in UNSAFE_CODES:
            raise UserError(UNSAFE_CODES[code])
        d = self.descs.get(code) or cam.get_prop_desc(code)
        if not d.writable:
            raise UserError(self._readonly_reason(code))
        if d.dtype == DT_STR:
            value = str(value)
        else:
            value = int(value)
            if d.form == "enum" and d.values and value not in d.values:
                raise UserError("That value isn't available right now")
            if d.form == "range":
                value = max(d.minimum, min(d.maximum, value))
        try:
            self._retry_busy(cam.set_prop, code, value, d.dtype)
        except PTPError as e:
            raise UserError(self._set_error(code, e)) from e
        if code == 0xD1A6:
            self.desired_selector = value
        self._reload([code])
        if code in CASCADE_CODES:
            self._reload(CATALOG_CODES)
        return {"value": self._value(code)}

    def _readonly_reason(self, code: int) -> str:
        movie_codes = {s.code for s in catalog.SETTINGS if s.scope == catalog.MOVIE}
        photo_codes = {s.code for s in catalog.SETTINGS if s.scope == catalog.PHOTO}
        mode = self._value(0x500E)
        if code in (0xD1A8, 0xD1A9, 0xD100, 0x5007) and mode not in (1, 3, 4):
            return "Set the exposure mode to M (or A/S) to change this"
        if code in (0xD1A8, 0xD1A9, 0xD1AA, 0xD1AB) and not self._is_movie():
            return "Movie settings can only be changed with live view in movie mode"
        if code in PC_MODE_CODES and not self.lv_on:
            return "Can only be changed while live view is running"
        if code in (0xD23B, 0xD314) and self._value(0xD0A0) in (0, 1, 2):
            return "Not available in 4K — pick a 1080p or 720p frame size"
        if code in movie_codes and not self._is_movie():
            return "Switch live view to movie mode to change this"
        if code in photo_codes and self._is_movie():
            return "Switch live view to photo mode to change this"
        if self.recording:
            return "Can't be changed while recording"
        return "The camera doesn't allow changing this right now"

    def _set_error(self, code: int, e: PTPError) -> str:
        if e.code == 0x200F:
            return "The camera refused the change (" + self._readonly_reason(code) + ")"
        return f"The camera refused the change: {e}"

    def _enable_pc_mode(self) -> None:
        if self.pc_mode:
            return
        was_lv = self.lv_on
        if was_lv:
            self._end_lv()
        try:
            self._retry_busy(self.cam.set_camera_mode, True)
        except PTPError as e:
            raise UserError(f"Couldn't switch the camera to PC control: {e}") from e
        self.pc_mode = True
        self._set_status(pc_mode=True)
        self._reload(CATALOG_CODES)
        self._toast("PC control on — the mode dial and Lv switch are now set from here.")

    def _disable_pc_mode(self) -> None:
        if not self.pc_mode:
            return
        if self.lv_on:
            self._end_lv()
        try:
            self._retry_busy(self.cam.set_camera_mode, False)
        except PTPError as e:
            raise UserError(f"Couldn't leave PC control: {e}") from e
        self.pc_mode = False
        self._set_status(pc_mode=False)
        self._reload(CATALOG_CODES)

    def _cmd_pc_mode(self, fut, on: bool):
        if self.recording:
            raise UserError("Stop recording first")
        if on:
            self._enable_pc_mode()
        else:
            self._disable_pc_mode()
        return {"pc_mode": self.pc_mode}

    def _cmd_liveview(self, fut, on: bool):
        self.want_lv = bool(on)
        if not on and self.lv_on and not self.recording:
            self._end_lv()
        if on:
            self._next_lv_try = 0
        return {"lv": self.want_lv}

    def _frame_to_sensor(self, fx: float, fy: float) -> tuple[int, int]:
        frame = self.latest_frame()
        if frame is None or not frame.header.get("disp_w"):
            raise UserError("No live view frame yet")
        h = frame.header
        x = h["disp_cx"] - h["disp_w"] / 2 + fx * h["disp_w"]
        y = h["disp_cy"] - h["disp_h"] / 2 + fy * h["disp_h"]
        x = int(max(0, min(h["whole_w"] - 1, x)))
        y = int(max(0, min(h["whole_h"] - 1, y)))
        return x, y

    def _cmd_focus_at(self, fut, fx: float, fy: float, run_af: bool = True):
        if not self.lv_on:
            raise UserError("Live view isn't running")
        x, y = self._frame_to_sensor(float(fx), float(fy))
        try:
            self._retry_busy(self.cam.change_af_area, x, y)
        except PTPError as e:
            raise UserError(f"Couldn't move the focus point: {e}") from e
        self.af_point = (x, y)
        if not run_af or self._value(0xD061) in (3, 4):
            return {"moved": True, "x": x, "y": y}
        return self._cmd_autofocus(fut)

    def _cmd_autofocus(self, fut):
        if not self.lv_on:
            raise UserError("Live view isn't running")
        if self._value(0xD061) in (3, 4):
            raise UserError("Focus mode is MF — switch to AF-S or AF-F to autofocus")
        if self._busy:
            raise UserError("Still focusing…")
        try:
            self._retry_busy(self.cam.transaction, OC_NIKON_AfDrive)
        except PTPError as e:
            raise UserError(f"Autofocus failed: {e}") from e
        self._busy = _BusyOp("af", fut, time.monotonic(), 6.0)
        return _PENDING

    def _cmd_manual_focus(self, fut, steps: int):
        if not self.lv_on:
            raise UserError("Live view isn't running")
        if self._busy:
            raise UserError("Lens is still moving…")
        steps = int(steps)
        direction = 2 if steps >= 0 else 1
        try:
            self._retry_busy(self.cam.transaction, OC_NIKON_MfDrive, [direction, max(1, abs(steps))])
        except PTPError as e:
            if e.code in MF_LIMIT_CODES:
                return {"ok": True, "limit": True}
            raise UserError(f"Manual focus failed: {e}") from e
        self._busy = _BusyOp("mf", fut, time.monotonic(), 5.0)
        return _PENDING

    def _cmd_record(self, fut, on: bool):
        cam = self.cam
        if on:
            if self.recording:
                return {"recording": True}
            if not self._is_movie():
                raise UserError("Live view is in photo mode — switch it to movie to record")
            if not self.lv_on:
                self._start_lv()
                if not self.lv_on:
                    raise UserError(self.status.get("lv_error") or "Live view isn't running")
            prohibit = cam.get_prop(0xD0A4, 6)
            if prohibit & BODY_ONLY_BIT and not self.recording:
                # Not in application mode: it can only be set with live view off.
                log.info("recording blocked by application mode — restarting live view in application mode")
                self._end_lv()
                time.sleep(1.0)
                self.app_mode = False
                self._ensure_app_mode()
                self._next_lv_try = 0
                self._start_lv()
                if not self.lv_on:
                    raise UserError(self.status.get("lv_error") or "Live view didn't restart")
                time.sleep(0.5)
            # Let the camera decide; the prohibit bits only explain a refusal.
            try:
                self._retry_busy(cam.start_movie)
            except PTPError as e:
                prohibit = cam.get_prop(0xD0A4, 6)
                if prohibit & ~BODY_ONLY_BIT == 0:
                    raise UserError(
                        "The camera refused to start recording even in application mode. Press the camera's "
                        "● button as a fallback — the app follows the take."
                    ) from e
                reasons = catalog.decode_bits(prohibit, catalog.MOVIE_PROHIBIT_BITS)
                raise UserError("Can't record: " + ("; ".join(reasons) if reasons else str(e))) from e
            self._recording_started()
            return {"recording": True}
        if not self.recording:
            return {"recording": False}
        try:
            self._retry_busy(cam.stop_movie)
        except PTPError as e:
            raise UserError(f"Recording didn't stop: {e}") from e
        self._recording_stopped(None)
        return {"recording": False}

    def _cmd_restart_lv(self, fut):
        """Restart live view to reset the camera's live view auto-off timer (brief blackout)."""
        if self.recording:
            raise UserError("Not while the camera is recording")
        self.cam.cancel_af()
        time.sleep(0.2)
        if self.lv_on:
            self._end_lv()
            time.sleep(2.0)  # restarting too quickly can leave the D7500 stuck busy
        self._next_lv_try = 0
        self._start_lv()
        if not self.lv_on:
            raise UserError(self.status.get("lv_error") or "Live view didn't restart")
        return {"ok": True}

    def _cmd_sync_clock(self, fut):
        now = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        return self._cmd_set(fut, 0x5011, now)

    # -- presets ------------------------------------------------------------
    def _preset_path(self):
        from pathlib import Path

        base = Path.home() / ".config" / "nikon-remote"
        base.mkdir(parents=True, exist_ok=True)
        return base / "presets.json"

    def _load_presets(self) -> dict:
        import json

        try:
            return json.loads(self._preset_path().read_text())
        except (OSError, ValueError):
            return {}

    def _save_presets(self, presets: dict) -> None:
        import json

        path = self._preset_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(presets, indent=2))
        tmp.replace(path)

    def _cmd_presets(self, fut):
        return {**catalog.builtin_presets_json(), **self._load_presets()}

    def _cmd_save_preset(self, fut, name: str):
        name = str(name).strip()[:60]
        if not name:
            raise UserError("Give the preset a name")
        if name in catalog.builtin_presets_json():
            raise UserError("That name belongs to a built-in preset — pick another")
        movie = self._is_movie()
        values = {}
        for s in catalog.SETTINGS:
            d = self.descs.get(s.code)
            if d is None or not d.writable or s.fmt == "text" or s.section == "setup":
                continue
            if s.scope != catalog.BOTH and (s.scope == catalog.MOVIE) != movie:
                continue
            if s.code in (LV_ZOOM, 0xD1A5):
                continue
            values[str(s.code)] = d.current
        presets = self._load_presets()
        presets[name] = {"movie": movie, "values": values, "saved": dt.datetime.now().isoformat(timespec="seconds")}
        self._save_presets(presets)
        return {"name": name, "count": len(values)}

    def _cmd_delete_preset(self, fut, name: str):
        if str(name) in catalog.builtin_presets_json():
            raise UserError("Built-in presets can't be deleted")
        presets = self._load_presets()
        presets.pop(str(name), None)
        self._save_presets(presets)
        return {"ok": True}

    def _cmd_apply_preset(self, fut, name: str):
        preset = {**catalog.builtin_presets_json(), **self._load_presets()}.get(str(name))
        if not preset:
            raise UserError("Preset not found")
        values = {int(k): v for k, v in preset["values"].items()}
        # Order matters: live view mode and exposure mode decide what else is writable.
        first = [c for c in (0xD1A6, 0x500E, 0xD0A0, 0xD0AD, 0xD16A, 0xD23A) if c in values]
        failed = []
        for code in first + [c for c in values if c not in first]:
            d = self.descs.get(code)
            if d is None or d.current == values[code]:
                continue
            value = values[code]
            if d.form == "enum" and d.values and value not in d.values and all(isinstance(v, int) for v in d.values):
                # e.g. f/3.5 isn't available when zoomed in: use the closest the lens offers
                value = min(d.values, key=lambda v: abs(v - value))
            try:
                self._cmd_set(fut, code, value)
            except (UserError, PTPError) as e:
                label = next((s.label for s in catalog.SETTINGS if s.code == code), hex(code))
                failed.append(f"{label}: {e}")
        return {"failed": failed}

    def _cmd_refresh(self, fut):
        self._load_all_descs()
        self._emit("props", {c: desc_json(d) for c, d in self.descs.items()})
        return {"ok": True}


_PENDING = object()
