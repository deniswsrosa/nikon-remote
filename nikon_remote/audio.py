"""Audio monitor for a mic going into the PC through a mixer's USB feed.

Streams the source through PipeWire (`pw-record`), meters it (peak, RMS,
ITU BS.1770 loudness), gives a live GAIN hint while you talk, and captures
speech for the mixer analysis in `mixer.py`.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import Future

import json
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

from . import mixer

log = logging.getLogger("nikon_remote.audio")

RATE = 48000
BLOCK = RATE // 10  # 100 ms

# BS.1770 K-weighting at 48 kHz (pre-filter shelf + RLB high-pass).
K1_B, K1_A = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
K2_B, K2_A = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]

MIXER_STATE = Path.home() / ".config" / "nikon-remote" / "mixer.json"
# What the channel is set to at the start: the "starting position" in the Audio tab.
BASELINE = {"low_cut": True, "low": 0.0, "hi": 0.0}


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
        self._speech_peaks: deque = deque(maxlen=40)  # last 4 s of speech, 100 ms peaks
        self._last_speech = 0.0
        self.mixer_state = self._load_state()

    # -- mixer state (what the user says the channel is set to) -------------
    def _load_state(self) -> dict:
        try:
            return {**BASELINE, **json.loads(MIXER_STATE.read_text())}
        except (OSError, ValueError):
            return dict(BASELINE)

    def set_mixer_state(self, state: dict | None) -> dict:
        self.mixer_state = {**BASELINE, **(state or {})}
        MIXER_STATE.parent.mkdir(parents=True, exist_ok=True)
        MIXER_STATE.write_text(json.dumps(self.mixer_state))
        return self.mixer_state

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

        # Live GAIN hint from the last few seconds of speech (target: 90th-percentile peaks −12…−6 dBFS).
        now_s = time.monotonic()
        if speaking:
            self._speech_peaks.append(peak)
            self._last_speech = now_s
        elif now_s - self._last_speech > 3:
            self._speech_peaks.clear()
        hint = {"action": "talk", "db": 0}
        if len(self._speech_peaks) >= 12:
            p90 = float(np.percentile(self._speech_peaks, 90))
            lo, hi_ = mixer.PEAK_TARGET
            if peak > -1 or p90 > hi_:
                hint = {"action": "down", "db": round(-9 - p90)}
            elif p90 < lo:
                hint = {"action": "up", "db": round(-9 - p90)}
            else:
                hint = {"action": "ok", "db": 0}
            hint["p90"] = round(p90, 1)

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
            gain_hint=hint,
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
        floor = self.last.get("floor")
        state = dict(self.mixer_state)

        def work():
            try:
                fut.set_result(mixer.analyse(blocks, list(self._silence), floor, state))
            except Exception as e:  # surfaced to the UI
                log.exception("voice analysis failed")
                fut.set_exception(e)

        # The analysis takes ~0.1–0.3 s; keep the audio thread streaming meanwhile.
        threading.Thread(target=work, daemon=True).start()
