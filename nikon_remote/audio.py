"""Audio monitor and mixer coach for a mic going into the PC (tuned for a Mackie ProFX6v3).

Streams the mixer's USB feed through PipeWire (`pw-record`), meters it
(peak, RMS, EBU/ITU BS.1770 loudness) and, on request, analyses a stretch of
speech to say which knob to turn, and which way, for a podcast-style voice.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import Future

import numpy as np
from scipy.signal import lfilter

log = logging.getLogger("nikon_remote.audio")

RATE = 48000
BLOCK = RATE // 10  # 100 ms

# BS.1770 K-weighting at 48 kHz (pre-filter shelf + RLB high-pass).
K1_B, K1_A = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
K2_B, K2_A = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]

# Targets for a podcast-style voice in the raw recording (normalise to −14 LUFS for YouTube in the edit).
PEAK_TARGET = (-12.0, -6.0)  # 95th-percentile speech peaks, dBFS
LOUDNESS_TARGET = (-22.0, -16.0)  # speech loudness, LUFS
# Long-term speech spectrum, each band's power relative to the 250 Hz–2 kHz "body" (dB), with tolerance.
BANDS = {
    "sub": (20, 90),
    "boom": (100, 250),
    "body": (250, 2000),
    "presence": (2000, 5000),
    "air": (8000, 16000),
}
TONE_TARGETS = {"boom": (-6.0, 4.5), "presence": (-13.0, 4.5), "air": (-30.0, 6.0)}


def db(x: float) -> float:
    return 20 * np.log10(max(x, 1e-9))


def list_sources() -> list[dict]:
    """PipeWire audio inputs as [{name, description}]."""
    try:
        out = subprocess.run(["pw-cli", "ls", "Node"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    sources = []
    for block in re.split(r"\n\s*id \d+,", out):
        props = dict(re.findall(r'(\S+) = "([^"]*)"', block))
        if props.get("media.class") == "Audio/Source" and "node.name" in props:
            sources.append({"name": props["node.name"], "description": props.get("node.description", props["node.name"])})
    return sources


def default_source(sources: list[dict]) -> str | None:
    for s in sources:
        if "profx" in (s["name"] + s["description"]).lower():
            return s["name"]
    return sources[0]["name"] if sources else None


class AudioMonitor:
    def __init__(self, emit):
        self._emit = emit  # emit(kind, payload)
        self.source: str | None = None
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._zi = None
        self._kblocks: deque = deque(maxlen=30)  # K-weighted mean-square per block, per channel (3 s)
        self._rms_hist: deque = deque(maxlen=300)  # block RMS dBFS, 30 s
        self._silence: deque = deque(maxlen=50)  # raw mono blocks judged as silence (5 s)
        self._capture: list | None = None  # voice check buffer
        self._capture_blocks = 0  # how many 100 ms blocks the running voice check wants
        self._capture_future: Future | None = None
        self._clip_until = 0.0
        self.enabled = True
        self.last: dict = {}

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill()

    def select(self, name: str | None) -> None:
        self.source = name
        self._restart.set()
        self._kill()

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # -- streaming ----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            self._restart.clear()
            if self.source is None:
                self.source = default_source(list_sources())
            if not self.source:
                self._status(error="No audio input found. Is the mixer's USB cable connected?")
                time.sleep(3)
                continue
            cmd = ["pw-record", "--raw", "--format", "s16", "--rate", str(RATE), "--channels", "2",
                   "--latency", "50ms", "--target", self.source, "-"]
            try:
                self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError as e:
                self._status(error=f"Can't start audio capture: {e}")
                time.sleep(5)
                continue
            self._zi = None
            self._status(error=None)
            nbytes = BLOCK * 4
            while not self._stop.is_set() and not self._restart.is_set():
                buf = self._proc.stdout.read(nbytes)
                if not buf or len(buf) < nbytes:
                    break
                x = np.frombuffer(buf, np.int16).reshape(-1, 2).astype(np.float32) / 32768.0
                try:
                    self._process(x)
                except Exception:
                    log.exception("audio block failed")
            self._kill()
            if not self._stop.is_set() and not self._restart.is_set():
                self._status(error="Audio input stopped — reconnecting…")
                time.sleep(2)

    def _status(self, **kw) -> None:
        self.last.update(kw)
        self._emit("audio", dict(self.last, source=self.source))

    def _process(self, x: np.ndarray) -> None:
        # K-weighting with filter state carried across blocks.
        if self._zi is None:
            self._zi = [np.zeros((2, 2)), np.zeros((2, 2))]
        k = np.empty_like(x)
        for ch in range(2):
            y, self._zi[0][ch] = lfilter(K1_B, K1_A, x[:, ch], zi=self._zi[0][ch])
            k[:, ch], self._zi[1][ch] = lfilter(K2_B, K2_A, y, zi=self._zi[1][ch])
        self._kblocks.append((k ** 2).mean(axis=0))
        kb = np.array(self._kblocks)
        lufs_m = -0.691 + 10 * np.log10(max(kb[-4:].mean(axis=0).sum(), 1e-12))
        lufs_s = -0.691 + 10 * np.log10(max(kb.mean(axis=0).sum(), 1e-12))

        peak = db(float(np.abs(x).max()))
        rms_ch = np.sqrt((x ** 2).mean(axis=0))
        rms = db(float(rms_ch.max()))
        self._rms_hist.append(rms)
        floor = float(np.percentile(self._rms_hist, 15)) if len(self._rms_hist) >= 30 else None
        speaking = rms > max((floor if floor is not None else -70) + 12, -55)
        if not speaking:
            self._silence.append(x.mean(axis=1))
        if peak > -1.0:
            self._clip_until = time.monotonic() + 3
        balance = db(float(rms_ch[0])) - db(float(rms_ch[1]))

        now = time.monotonic()
        if self._capture is not None:
            self._capture.append((x.copy(), float(kb[-1].sum()), speaking, peak))
            if len(self._capture) >= self._capture_blocks:
                self._finish_check()

        self.last.update(
            peak=round(peak, 1),
            rms=round(rms, 1),
            lufs_m=round(float(lufs_m), 1),
            lufs_s=round(float(lufs_s), 1),
            floor=round(floor, 1) if floor is not None else None,
            speaking=bool(speaking),
            clipping=now < self._clip_until,
            balance=round(balance, 1),
            checking=self._capture is not None,
            check_left=round((self._capture_blocks - len(self._capture)) / 10, 1) if self._capture is not None else 0,
            error=None,
        )
        self._emit("audio", dict(self.last, source=self.source))

    # -- voice check --------------------------------------------------------
    def voice_check(self, seconds: float = 15.0) -> Future:
        fut: Future = Future()
        if self._capture is not None:
            fut.set_exception(RuntimeError("A voice check is already running"))
            return fut
        self._capture = []
        self._capture_blocks = max(10, int(seconds * 10))
        self._capture_future = fut
        return fut

    def _finish_check(self) -> None:
        blocks, fut = self._capture, self._capture_future
        self._capture, self._capture_future = None, None
        try:
            fut.set_result(analyse_voice(blocks, list(self._silence), self.last.get("floor")))
        except Exception as e:  # pragma: no cover - surfaced to the UI
            fut.set_exception(e)


# ---------------------------------------------------------------------------
# Analysis → ProFX6v3 advice

def _band_powers(mono: np.ndarray) -> dict[str, float]:
    n = 8192
    if len(mono) < n:
        return {}
    win = np.hanning(n)
    hop = n // 2
    spec = np.zeros(n // 2 + 1)
    count = 0
    for i in range(0, len(mono) - n, hop):
        spec += np.abs(np.fft.rfft(mono[i:i + n] * win)) ** 2
        count += 1
    spec /= max(count, 1)
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    return {name: 10 * np.log10(spec[(freqs >= lo) & (freqs < hi)].sum() + 1e-12) for name, (lo, hi) in BANDS.items()}


def _hum(silence: list[np.ndarray]) -> str | None:
    if len(silence) < 20:
        return None
    x = np.concatenate(silence)[: RATE * 4]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    for base in (60, 50):
        hits = 0
        for h in (1, 2, 3):
            f = base * h
            i = int(np.argmin(np.abs(freqs - f)))
            peak = spec[max(0, i - 2): i + 3].max()
            around = np.median(spec[max(0, i - 40): i + 40])
            if peak > around * 8:  # ~18 dB above its neighbourhood
                hits += 1
        if hits >= 2:
            return f"{base} Hz"
    return None


def analyse_voice(blocks: list, silence: list, floor: float | None) -> dict:
    speech = [b for b in blocks if b[2]]
    speech_secs = len(speech) / 10
    recs: list[dict] = []

    def rec(level, control, action, text, amount=None):
        recs.append({"level": level, "control": control, "action": action, "text": text, "amount": amount})

    if speech_secs < 4:
        peak_all = max((b[3] for b in blocks), default=-120)
        if peak_all < -50:
            rec("bad", "INPUT", "check",
                "Almost no signal. Check the mic is in channel 1 (or 2), +48V is on if it's a condenser mic, "
                "channel LEVEL and MAIN MIX are up, and the right audio input is selected below.")
        else:
            rec("bad", "INPUT", "check", "Not enough speech heard — talk continuously at your recording volume for the whole check.")
        return {"speech_seconds": speech_secs, "recommendations": recs}

    x = np.concatenate([b[0] for b in speech])
    peaks = np.array([b[3] for b in speech])
    peak_max = float(peaks.max())
    peak_p95 = float(np.percentile(peaks, 95))
    ms = np.array([b[1] for b in speech])
    loudness = -0.691 + 10 * np.log10(ms.mean() + 1e-12)
    # Short-term loudness spread (3 s windows) ≈ loudness range: how uneven the voice is.
    st = [-0.691 + 10 * np.log10(ms[i:i + 30].mean() + 1e-12) for i in range(0, max(1, len(ms) - 29), 5)]
    lra = float(np.percentile(st, 95) - np.percentile(st, 10)) if len(st) >= 3 else None
    rms_l, rms_r = np.sqrt((x ** 2).mean(axis=0))
    balance = db(float(rms_l)) - db(float(rms_r))
    bands = _band_powers(x.mean(axis=1))
    rel = {k: bands[k] - bands["body"] for k in bands if k != "body"} if bands else {}
    hum = _hum(silence)

    # 1. clipping / gain
    if peak_max > -1:
        rec("bad", "GAIN", "down", "Clipping: turn GAIN down until the loudest words peak around −6 dBFS. "
            "The channel's Level Set LED should only flicker on your loudest words.", f"≈ −{peak_max + 6:.0f} dB")
    elif peak_p95 < PEAK_TARGET[0]:
        need = -9 - peak_p95
        rec("warn", "GAIN", "up", "Too quiet: turn GAIN up on your mic channel. (Channel LEVEL and MAIN MIX should sit at U — unity.)",
            f"≈ +{need:.0f} dB")
    elif peak_p95 > PEAK_TARGET[1] or peak_max > -3:
        rec("warn", "GAIN", "down", "A bit hot: turn GAIN down slightly to leave headroom for laughs and emphasis.",
            f"≈ −{max(peak_p95 + 9, peak_max + 6):.0f} dB")
    else:
        rec("ok", "GAIN", "ok", f"Speech peaks at {peak_p95:.0f} dBFS — good headroom.")

    # 2. pan / balance
    if abs(balance) > 3:
        side = "left" if balance > 0 else "right"
        rec("warn", "PAN", "center", f"Your voice is {abs(balance):.0f} dB louder on the {side}: set PAN to 12 o'clock (centre).")
    else:
        rec("ok", "PAN", "ok", "Voice centred.")

    # 3. noise and hum
    if floor is not None and floor > -58:
        rec("warn", "GAIN", "check",
            f"Background noise is high ({floor:.0f} dBFS between words): get closer to the mic and lower GAIN, "
            "and turn off fans/AC. The compressor also lifts noise.")
    elif floor is not None:
        rec("ok", "NOISE", "ok", f"Quiet between words ({floor:.0f} dBFS).")
    if hum:
        rec("warn", "CABLES", "check", f"{hum} hum detected: check mic/USB cables, keep audio cables away from power bricks, try another outlet.")

    # 4. rumble → low cut
    if rel.get("sub") is not None and rel["sub"] > -18:
        rec("warn", "LOW CUT", "press", "Low rumble under your voice: press LOW CUT (100 Hz) on your mic channel.")
    elif rel:
        rec("ok", "LOW CUT", "ok", "No rumble.")

    # 5. dynamics → compressor
    if lra is not None:
        if lra > 8:
            rec("warn", "COMP", "up", f"Your level varies a lot ({lra:.0f} LU): turn COMP clockwise, to about 12–1 o'clock, for an even podcast voice.")
        elif lra < 3 and peak_max - loudness < 9:
            rec("warn", "COMP", "down", "Very squashed — turn COMP back a little (counter-clockwise) so it doesn't pump.")
        else:
            rec("ok", "COMP", "ok", f"Even level ({lra:.0f} LU range).")

    # 6. tone → 3-band EQ (LOW 80 Hz shelf, MID 2.5 kHz, HI 12 kHz)
    def tone(band, control, freq, low_text, high_text):
        if band not in rel:
            return
        target, tol = TONE_TARGETS[band]
        d = rel[band] - target
        if d > tol:
            rec("warn", control, "down", high_text, f"≈ −3 dB ({freq})")
        elif d < -tol:
            rec("warn", control, "up", low_text, f"≈ +3 dB ({freq})")
        else:
            rec("ok", control, "ok", f"{control} ({freq}) sounds balanced.")

    tone("boom", "LOW", "80 Hz", "Voice sounds thin: turn LOW up a little (about 1 o'clock) for warmth.",
         "Boomy low end: turn LOW down a little (about 11 o'clock), or sit a few centimetres further from the mic.")
    tone("presence", "MID", "2.5 kHz", "Voice sounds muffled: turn MID up a little (about 1 o'clock) for clarity.",
         "Harsh/shouty: turn MID down a little (about 11 o'clock).")
    tone("air", "HI", "12 kHz", "Dull: turn HI up a little (about 1 o'clock) for air.",
         "Hissy or sibilant: turn HI down a little (about 11 o'clock).")

    order = {"bad": 0, "warn": 1, "ok": 2}
    recs.sort(key=lambda r: order[r["level"]])
    return {
        "speech_seconds": speech_secs,
        "peak_max": round(peak_max, 1),
        "peak_p95": round(peak_p95, 1),
        "loudness": round(float(loudness), 1),
        "lra": round(lra, 1) if lra is not None else None,
        "balance": round(balance, 1),
        "floor": floor,
        "hum": hum,
        "tone": {k: round(v, 1) for k, v in rel.items()},
        "recommendations": recs,
    }
