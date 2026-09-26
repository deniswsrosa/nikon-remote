"""Minimal PTP-over-USB client with the Nikon vendor operations this app needs.

libgphoto2 hides the Nikon live view header (AF box, level, recording time),
so the app talks PTP directly through pyusb instead.
"""

from __future__ import annotations

import struct
import threading
from dataclasses import dataclass, field

import usb.core
import usb.util

NIKON_VENDOR_ID = 0x04B0

# --- operation codes -------------------------------------------------------
OC_GetDeviceInfo = 0x1001
OC_OpenSession = 0x1002
OC_CloseSession = 0x1003
OC_GetObjectInfo = 0x1008
OC_GetDevicePropDesc = 0x1014
OC_GetDevicePropValue = 0x1015
OC_SetDevicePropValue = 0x1016
OC_NIKON_AfDrive = 0x90C1
OC_NIKON_ChangeCameraMode = 0x90C2
OC_NIKON_GetEvent = 0x90C7
OC_NIKON_DeviceReady = 0x90C8
OC_NIKON_GetVendorPropCodes = 0x90CA
OC_NIKON_StartLiveView = 0x9201
OC_NIKON_EndLiveView = 0x9202
OC_NIKON_GetLiveViewImg = 0x9203
OC_NIKON_MfDrive = 0x9204
OC_NIKON_ChangeAfArea = 0x9205
OC_NIKON_AfDriveCancel = 0x9206
OC_NIKON_StartMovieRecInCard = 0x920A
OC_NIKON_EndMovieRec = 0x920B

# --- response codes --------------------------------------------------------
RC_OK = 0x2001
RC_DeviceBusy = 0x2019
RC_SessionAlreadyOpen = 0x201E
RC_NAMES = {
    0x2002: "General error",
    0x2003: "Session not open",
    0x2005: "Operation not supported",
    0x2006: "Parameter not supported",
    0x200A: "Device property not supported",
    0x200F: "Access denied",
    0x2019: "Camera busy",
    0x201B: "Invalid device property format",
    0x201C: "Invalid device property value",
    0x201D: "Invalid parameter",
    0x201E: "Session already open",
    0xA001: "Hardware error",
    0xA002: "Could not focus",
    0xA003: "Camera mode change failed",
    0xA004: "Not allowed in the camera's current state",
    0xA005: "Setting not supported right now",
    0xA008: "Shutter speed is Bulb",
    0xA00A: "Aperture can't be adjusted in this mode",
    0xA00B: "Live view is not running",
    0xA00C: "Focus reached the end of its range",
    0xA00E: "Focus step too small",
    0xA021: "Card error",
    0xA022: "Card not formatted",
}

# --- event codes -----------------------------------------------------------
EC_ObjectAdded = 0x4002
EC_DevicePropChanged = 0x4006
EC_NIKON_MovieRecordInterrupted = 0xC105
EC_NIKON_MovieRecordComplete = 0xC108
EC_NIKON_MovieRecordStarted = 0xC10A
EC_NIKON_LiveViewStateChanged = 0xC10C

# --- data types ------------------------------------------------------------
DT_STR = 0xFFFF
_DT_FMT = {1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 7: "q", 8: "Q"}


class PTPError(Exception):
    def __init__(self, code: int, op: int | None = None):
        self.code = code
        self.op = op
        name = RC_NAMES.get(code, f"PTP error 0x{code:04x}")
        super().__init__(name)


class DisconnectedError(Exception):
    pass


@dataclass
class PropDesc:
    code: int
    dtype: int
    writable: bool
    current: object
    form: str = "none"  # none | range | enum
    minimum: object = None
    maximum: object = None
    step: object = None
    values: list = field(default_factory=list)


def _read_str(buf: bytes, off: int) -> tuple[str, int]:
    n = buf[off]
    off += 1
    if n == 0:
        return "", off
    raw = buf[off : off + 2 * n]
    return raw.decode("utf-16-le", errors="replace").rstrip("\x00"), off + 2 * n


def _encode_str(s: str) -> bytes:
    if not s:
        return b"\x00"
    raw = (s + "\x00").encode("utf-16-le")
    return bytes([len(raw) // 2]) + raw


def _read_val(buf: bytes, off: int, dtype: int):
    if dtype == DT_STR:
        return _read_str(buf, off)
    if dtype & 0x4000:
        (count,) = struct.unpack_from("<I", buf, off)
        off += 4
        fmt = _DT_FMT[dtype & 0xFF]
        size = struct.calcsize(fmt)
        vals = list(struct.unpack_from(f"<{count}{fmt}", buf, off))
        return vals, off + count * size
    if dtype in (9, 10):  # 128-bit ints, never used for settings we care about
        return int.from_bytes(buf[off : off + 16], "little", signed=dtype == 9), off + 16
    fmt = _DT_FMT[dtype]
    (v,) = struct.unpack_from("<" + fmt, buf, off)
    return v, off + struct.calcsize(fmt)


def encode_val(value, dtype: int) -> bytes:
    if dtype == DT_STR:
        return _encode_str(str(value))
    return struct.pack("<" + _DT_FMT[dtype], int(value))


def _u16_array(buf: bytes, off: int) -> tuple[list[int], int]:
    (count,) = struct.unpack_from("<I", buf, off)
    off += 4
    return list(struct.unpack_from(f"<{count}H", buf, off)), off + 2 * count


@dataclass
class DeviceInfo:
    operations: list[int]
    events: list[int]
    properties: list[int]
    manufacturer: str
    model: str
    version: str
    serial: str


def parse_device_info(buf: bytes) -> DeviceInfo:
    off = 2 + 4 + 2  # standard version, vendor ext id, vendor ext version
    _, off = _read_str(buf, off)  # vendor extension description
    off += 2  # functional mode
    ops, off = _u16_array(buf, off)
    events, off = _u16_array(buf, off)
    props, off = _u16_array(buf, off)
    _, off = _u16_array(buf, off)  # capture formats
    _, off = _u16_array(buf, off)  # image formats
    manufacturer, off = _read_str(buf, off)
    model, off = _read_str(buf, off)
    version, off = _read_str(buf, off)
    serial, off = _read_str(buf, off)
    return DeviceInfo(ops, events, props, manufacturer, model, version, serial)


def parse_prop_desc(buf: bytes) -> PropDesc:
    code, dtype, getset = struct.unpack_from("<HHB", buf, 0)
    off = 5
    _, off = _read_val(buf, off, dtype)  # factory default
    current, off = _read_val(buf, off, dtype)
    desc = PropDesc(code=code, dtype=dtype, writable=getset == 1, current=current)
    if off >= len(buf):
        return desc
    form = buf[off]
    off += 1
    if form == 1:
        desc.form = "range"
        desc.minimum, off = _read_val(buf, off, dtype)
        desc.maximum, off = _read_val(buf, off, dtype)
        desc.step, off = _read_val(buf, off, dtype)
    elif form == 2:
        desc.form = "enum"
        (count,) = struct.unpack_from("<H", buf, off)
        off += 2
        for _ in range(count):
            v, off = _read_val(buf, off, dtype)
            desc.values.append(v)
    return desc


@dataclass
class LiveViewFrame:
    jpeg: bytes
    header: dict


def parse_liveview(data: bytes) -> LiveViewFrame:
    """Split a Nikon GetLiveViewImg payload into the JPEG and its header.

    The header is big-endian. Field offsets were confirmed against a D7500:
    full-sensor coordinate space, displayed area, and the AF box all use
    sensor pixels (5568x3712 on the D7500).
    """
    soi = data.find(b"\xff\xd8\xff")
    if soi < 0:
        raise PTPError(0x2002)
    h = data[:soi]

    def u16(o):
        return struct.unpack_from(">H", h, o)[0] if o + 2 <= len(h) else None

    def u32(o):
        return struct.unpack_from(">I", h, o)[0] if o + 4 <= len(h) else None

    header = {
        "jpeg_w": u16(8),
        "jpeg_h": u16(10),
        "whole_w": u16(12),
        "whole_h": u16(14),
        "disp_w": u16(16),
        "disp_h": u16(18),
        "disp_cx": u16(20),
        "disp_cy": u16(22),
        "af_w": u16(24),
        "af_h": u16(26),
        "af_cx": u16(28),
        "af_cy": u16(30),
        "raw": h[32:128].hex(),
    }
    # Angles are 16.16 fixed-point degrees (0-360); 0xFFFFFFFF = not available.
    for key, off in (("roll", 52), ("pitch", 56)):
        v = u32(off)
        if v is None or v == 0xFFFFFFFF:
            header[key] = None
        else:
            deg = v / 65536.0
            header[key] = round(deg - 360 if deg > 180 else deg, 2)
    header["lv_remaining_s"] = u16(46)  # candidate: live view auto-off countdown
    remain = u32(64)
    header["clip_remaining_ms"] = remain if remain not in (None, 0xFFFFFFFF) else None
    return LiveViewFrame(jpeg=bytes(data[soi:]), header=header)


def _is_still_image(dev) -> bool:
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceClass == 6:
                return True
    return False


class PTPCamera:
    """One PTP session over USB. All calls are serialised by a lock."""

    def __init__(self, vendor_id: int = NIKON_VENDOR_ID):
        self.vendor_id = vendor_id
        self.dev = None
        self._lock = threading.RLock()
        self._tid = 0
        self.info: DeviceInfo | None = None
        self.vendor_props: list[int] = []

    # -- connection ---------------------------------------------------------
    def open(self) -> None:
        dev = usb.core.find(idVendor=self.vendor_id, custom_match=_is_still_image)
        if dev is None:
            raise DisconnectedError("No Nikon camera found on USB")
        try:
            cfg = dev.get_active_configuration()
        except usb.core.USBError:
            dev.set_configuration()
            cfg = dev.get_active_configuration()
        intf = next(i for i in cfg if i.bInterfaceClass == 6)
        try:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                dev.detach_kernel_driver(intf.bInterfaceNumber)
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            usb.util.claim_interface(dev, intf.bInterfaceNumber)
        except usb.core.USBError as e:
            raise DisconnectedError(f"Camera is busy (another app is using it): {e}") from e

        def ep(direction, kind):
            return usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == direction
                and usb.util.endpoint_type(e.bmAttributes) == kind,
            )

        self.dev = dev
        self.intf = intf
        self.ep_out = ep(usb.util.ENDPOINT_OUT, usb.util.ENDPOINT_TYPE_BULK)
        self.ep_in = ep(usb.util.ENDPOINT_IN, usb.util.ENDPOINT_TYPE_BULK)
        self._drain()
        self._tid = 0
        try:
            self.transaction(OC_OpenSession, [1])
        except PTPError as e:
            if e.code != RC_SessionAlreadyOpen:
                raise
        data, _ = self.transaction(OC_GetDeviceInfo, want_data=True)
        self.info = parse_device_info(data)
        if OC_NIKON_GetVendorPropCodes in self.info.operations:
            data, _ = self.transaction(OC_NIKON_GetVendorPropCodes, want_data=True)
            self.vendor_props, _ = _u16_array(data, 0)

    def close(self) -> None:
        with self._lock:
            if self.dev is None:
                return
            try:
                self.transaction(OC_CloseSession, timeout=1000)
            except Exception:
                pass
            try:
                usb.util.release_interface(self.dev, self.intf.bInterfaceNumber)
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass
            self.dev = None

    def _drain(self) -> None:
        """Discard stale data left in the pipe by a previous session."""
        for _ in range(8):
            try:
                self.ep_in.read(512 * 1024, timeout=50)
            except usb.core.USBError:
                return

    # -- transport ----------------------------------------------------------
    def _read_container(self, timeout: int) -> bytes:
        while True:
            buf = bytes(self.ep_in.read(4 * 1024 * 1024, timeout=timeout))
            if len(buf) >= 12:
                break  # zero-length packets can trail a previous container
        (length,) = struct.unpack_from("<I", buf, 0)
        while len(buf) < length:
            buf += bytes(self.ep_in.read(4 * 1024 * 1024, timeout=timeout))
        return buf

    def transaction(self, op, params=(), data_out: bytes | None = None, want_data=False, timeout=5000):
        with self._lock:
            if self.dev is None:
                raise DisconnectedError("Camera not connected")
            self._tid += 1
            tid = self._tid
            try:
                cmd = struct.pack("<IHHI", 12 + 4 * len(params), 1, op, tid)
                cmd += b"".join(struct.pack("<I", p & 0xFFFFFFFF) for p in params)
                self.ep_out.write(cmd, timeout=timeout)
                if data_out is not None:
                    pkt = struct.pack("<IHHI", 12 + len(data_out), 2, op, tid) + data_out
                    self.ep_out.write(pkt, timeout=timeout)
                    if len(pkt) % self.ep_out.wMaxPacketSize == 0:
                        self.ep_out.write(b"", timeout=timeout)
                data = None
                while True:
                    buf = self._read_container(timeout)
                    length, ctype, code, _ = struct.unpack_from("<IHHI", buf, 0)
                    if ctype == 2:
                        data = buf[12:length]
                        continue
                    if ctype == 3:
                        nparams = (length - 12) // 4
                        rparams = struct.unpack_from(f"<{nparams}I", buf, 12) if nparams else ()
                        if code != RC_OK:
                            raise PTPError(code, op)
                        return data, rparams
            except usb.core.USBError as e:
                if e.errno in (19, 5, 32) or "No such device" in str(e):
                    self.dev = None
                    raise DisconnectedError(str(e)) from e
                raise

    # -- properties ---------------------------------------------------------
    def all_property_codes(self) -> list[int]:
        codes = list(self.info.properties if self.info else [])
        for c in self.vendor_props:
            if c not in codes:
                codes.append(c)
        return codes

    def get_prop_desc(self, code: int) -> PropDesc:
        data, _ = self.transaction(OC_GetDevicePropDesc, [code], want_data=True)
        return parse_prop_desc(data)

    def get_prop(self, code: int, dtype: int):
        data, _ = self.transaction(OC_GetDevicePropValue, [code], want_data=True)
        return _read_val(data, 0, dtype)[0]

    def set_prop(self, code: int, value, dtype: int, timeout: int = 5000) -> None:
        self.transaction(OC_SetDevicePropValue, [code], data_out=encode_val(value, dtype), timeout=timeout)

    # -- Nikon operations ---------------------------------------------------
    def device_ready(self) -> int:
        """Return the DeviceReady response code (RC_OK, RC_DeviceBusy, ...)."""
        try:
            self.transaction(OC_NIKON_DeviceReady)
            return RC_OK
        except PTPError as e:
            return e.code

    def wait_ready(self, timeout_s: float = 5.0, interval_s: float = 0.02) -> int:
        import time

        end = time.monotonic() + timeout_s
        while True:
            rc = self.device_ready()
            if rc != RC_DeviceBusy or time.monotonic() > end:
                return rc
            time.sleep(interval_s)

    def get_events(self) -> list[tuple[int, int]]:
        data, _ = self.transaction(OC_NIKON_GetEvent, want_data=True)
        if not data:
            return []
        (count,) = struct.unpack_from("<H", data, 0)
        return [struct.unpack_from("<HI", data, 2 + 6 * i) for i in range(count)]

    def start_liveview(self) -> None:
        try:
            self.transaction(OC_NIKON_StartLiveView)
        except PTPError as e:
            if e.code != RC_DeviceBusy:
                raise
        # The D7500 may autofocus as live view starts; in a dark room that takes a few seconds.
        rc = self.wait_ready(10.0, 0.1)
        if rc not in (RC_OK,):
            raise PTPError(rc, OC_NIKON_StartLiveView)

    def end_liveview(self) -> None:
        self.transaction(OC_NIKON_EndLiveView)
        self.wait_ready(3.0)

    def get_liveview(self) -> LiveViewFrame:
        data, _ = self.transaction(OC_NIKON_GetLiveViewImg, want_data=True)
        return parse_liveview(data)

    def cancel_af(self) -> None:
        """Abort a focus drive. The D7500 can get stuck mid-AF (every command answers
        "busy", even in a new session); this frees it immediately."""
        try:
            self.transaction(OC_NIKON_AfDriveCancel)
        except PTPError:
            pass

    def change_af_area(self, x: int, y: int) -> None:
        self.transaction(OC_NIKON_ChangeAfArea, [int(x), int(y)])

    def start_movie(self) -> None:
        self.transaction(OC_NIKON_StartMovieRecInCard)

    def stop_movie(self) -> None:
        self.transaction(OC_NIKON_EndMovieRec)

    def set_camera_mode(self, pc_control: bool) -> None:
        """PC-control mode unlocks dial-bound settings (exposure mode, Lv switch)."""
        self.transaction(OC_NIKON_ChangeCameraMode, [1 if pc_control else 0])

    # -- storage ------------------------------------------------------------
    def get_object_info(self, handle: int) -> dict:
        data, _ = self.transaction(OC_GetObjectInfo, [handle], want_data=True)
        storage, fmt, _prot, size = struct.unpack_from("<IHHI", data, 0)
        off = 52
        filename, off = _read_str(data, off)
        return {"handle": handle, "storage": storage, "format": fmt, "size": size, "filename": filename}

