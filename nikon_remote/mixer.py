"""Voice analysis → exact settings for a Mackie ProFX6v3 Mic/Line channel.

The ProFX6v3 channel 1/2 strip (per Mackie's owner's manual, 2024):
  GAIN knob (mic 0…+60 dB) + level-set LED · LOW CUT switch (100 Hz, 18 dB/oct)
  HI knob (±15 dB shelf above 12 kHz, flat at the centre detent)
  LOW knob (±15 dB shelf below 80 Hz, flat at the centre detent)
  FX switch · STEREO PAN switch (in = ch 1 feeds only the LEFT side)
  LEVEL knob (off … U … +10 dB)
It has no compressor and no mid EQ, and its USB feed is the main mix *before*
the MAIN MIX fader — so MAIN MIX doesn't change the recording.

Everything here works on a captured reading of a fixed script: speech is found
with WebRTC VAD, loudness is measured with pyloudnorm (ITU-R BS.1770), tone is
compared with the range real voices fall in, and the recording-software
compressor is *simulated* on your own audio with Spotify's pedalboard.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pyloudnorm
import webrtcvad
from pedalboard import Compressor, Gain, HighShelfFilter, LowShelfFilter, Pedalboard

RATE = 48000
REFERENCE = Path.home() / ".config" / "nikon-remote" / "voice_reference.json"

# 1/3-octave centres used for the voice's long-term spectrum.
THIRD_OCTAVES = [63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000,
                 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000]

PEAK_TARGET = (-12.0, -6.0)  # 90th-percentile speech peaks at the mixer's USB feed (dBFS)
RECORDING_LUFS = -16.0  # podcast delivery loudness after the software compressor


# ---------------------------------------------------------------------------
# knob language

def eq_clock(db: float) -> str:
    """ProFX EQ knobs: flat at 12 o'clock, ±15 dB at the ends (~150° each way),
    so one clock-hour (30°) ≈ 3 dB."""
    hours = db / 3.0
    if abs(hours) < 0.25:
        return "12 o'clock (centre detent)"
    base = 12 + hours
    h = int(np.floor(base)) % 12 or 12
    frac = base - np.floor(base)
    if frac < 0.25:
        pos = f"{h} o'clock"
    elif frac < 0.75:
        pos = f"half past {h}"
    else:
        pos = f"{(h % 12) + 1} o'clock"
    return pos


def _speech_mask(mono: np.ndarray, aggressiveness: int = 2) -> np.ndarray:
    """Per-sample boolean mask of speech, from 30 ms WebRTC VAD frames."""
    vad = webrtcvad.Vad(aggressiveness)
    frame = int(RATE * 0.03)
    pcm = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
    mask = np.zeros(len(mono), bool)
    for i in range(0, len(pcm) - frame + 1, frame):
        if vad.is_speech(pcm[i:i + frame].tobytes(), RATE):
            mask[i:i + frame] = True
    return mask


def third_octave_spectrum(mono: np.ndarray) -> np.ndarray:
    """Long-term average spectrum in dB per third-octave band."""
    n = 8192
    if len(mono) < n * 2:
        raise ValueError("not enough audio")
    win = np.hanning(n)
    spec = np.zeros(n // 2 + 1)
    count = 0
    for i in range(0, len(mono) - n, n // 2):
        spec += np.abs(np.fft.rfft(mono[i:i + n] * win)) ** 2
        count += 1
    spec /= count
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    out = []
    for fc in THIRD_OCTAVES:
        lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)
        sel = (freqs >= lo) & (freqs < hi)
        out.append(10 * np.log10(spec[sel].sum() + 1e-15))
    return np.array(out)


def save_reference_from_file(path: str, name: str) -> dict:
    """Decode any audio/video file with ffmpeg, keep the speech, store its spectrum as the target."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-t", "600", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
        capture_output=True, timeout=120,
    )
    if raw.returncode != 0 or not raw.stdout:
        raise ValueError("Couldn't read that file — try an MP3, WAV, M4A or a video file")
    mono = np.frombuffer(raw.stdout, np.float32)
    speech = mono[_speech_mask(mono)]
    if len(speech) < RATE * 10:
        raise ValueError("Found less than 10 s of speech in that file")
    metrics = measure_tone(third_octave_spectrum(speech))
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps({"name": name, "metrics": metrics, "speech_seconds": len(speech) / RATE}))
    return {"name": name, "speech_seconds": round(len(speech) / RATE, 1)}


def clear_reference() -> None:
    REFERENCE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tone measurements, with the range real voices fall in.
#
# Ranges come from six public-domain LibriVox readers (different people, mics
# and rooms). Voices differ a lot in the bands the ProFX6v3's two shelves
# touch, so the knobs are only moved when a measurement is clearly outside
# the range real voices occupy — never to chase a single "ideal" curve.

METRICS = {
    # key: (band, reference band, label, knob it relates to, typical range dB)
    "boom": ((125, 200), (315, 500), "Low end / boominess", "distance", (-10.0, 1.5)),
    "air": ((10000, 16000), (2000, 4000), "Air / brightness", "HI", (-26.0, -4.0)),
    "sibilance": ((5000, 8000), (2000, 4000), "Sibilance (s, sh, t)", None, (-14.0, 3.0)),
    "boxy": ((250, 500), (800, 2000), "Boxiness", None, (4.0, 12.5)),
    "presence": ((2000, 4000), (500, 1000), "Clarity / presence", None, (-14.5, -2.0)),
}


def _band(levels: np.ndarray, lo: float, hi: float) -> float:
    return float(np.mean([levels[i] for i, f in enumerate(THIRD_OCTAVES) if lo <= f <= hi]))


def measure_tone(levels: np.ndarray) -> dict:
    return {k: round(_band(levels, *band) - _band(levels, *ref), 1) for k, (band, ref, *_rest) in METRICS.items()}


def _metric_shift(key: str, low_db: float = 0.0, hi_db: float = 0.0) -> float:
    """How much a LOW/HI knob change moves a measurement (modelled on the real shelf curves)."""
    band, ref = METRICS[key][0], METRICS[key][1]
    freqs = np.array(THIRD_OCTAVES, float)
    resp = _shelf_gain_db(freqs, 80, low_db, "low") + _shelf_gain_db(freqs, 12000, hi_db, "high")
    return _band(resp, *band) - _band(resp, *ref)


def load_ranges() -> tuple[dict, str]:
    """Typical ranges, or ±3 dB around a reference voice the user uploaded."""
    ranges = {k: v[4] for k, v in METRICS.items()}
    try:
        ref = json.loads(REFERENCE.read_text())
        for k, v in ref["metrics"].items():
            ranges[k] = (v - 3.0, v + 3.0)
        return ranges, ref.get("name", "your reference voice")
    except (OSError, ValueError, KeyError):
        return ranges, "typical range of real voices"


def _shelf_gain_db(freqs: np.ndarray, fc: float, gain: float, kind: str) -> np.ndarray:
    """Magnitude of an RBJ shelving biquad (Q=0.707)."""
    from scipy.signal import freqz

    if abs(gain) < 1e-6:
        return np.zeros_like(freqs)
    a_ = 10 ** (gain / 40)
    w0 = 2 * np.pi * fc / RATE
    alpha = np.sin(w0) / 2 / 0.7071
    cw = np.cos(w0)
    s = 2 * np.sqrt(a_) * alpha
    if kind == "low":
        b = [a_ * ((a_ + 1) - (a_ - 1) * cw + s), 2 * a_ * ((a_ - 1) - (a_ + 1) * cw), a_ * ((a_ + 1) - (a_ - 1) * cw - s)]
        a = [(a_ + 1) + (a_ - 1) * cw + s, -2 * ((a_ - 1) + (a_ + 1) * cw), (a_ + 1) + (a_ - 1) * cw - s]
    else:
        b = [a_ * ((a_ + 1) + (a_ - 1) * cw + s), -2 * a_ * ((a_ - 1) + (a_ + 1) * cw), a_ * ((a_ + 1) + (a_ - 1) * cw - s)]
        a = [(a_ + 1) - (a_ - 1) * cw + s, 2 * ((a_ - 1) - (a_ + 1) * cw), (a_ + 1) - (a_ - 1) * cw - s]
    _, h = freqz(b, a, worN=freqs, fs=RATE)
    return 20 * np.log10(np.abs(h) + 1e-12)


def _hi_move(value: float, rng: tuple, current: float) -> dict | None:
    """HI (12 kHz shelf): only when clearly outside the range. ±3 dB on the knob moves this
    measurement by ~1.7 dB, so the steps stay small and are verified afterwards."""
    lo, hi = rng
    if value < lo - 6:
        delta, why = 6.0, f"very little air ({lo - value:.0f} dB below the range) — dull"
    elif value < lo:
        delta, why = 3.0, f"a little dull ({lo - value:.0f} dB below the range)"
    elif value > hi:
        delta, why = -3.0, f"hissy / too bright ({value - hi:.0f} dB above the range)"
    else:
        return None
    target = float(np.clip(current + delta, -6, 6))
    if abs(target - current) < 1.5:
        return None
    d = target - current
    return {"type": "knob", "control": "HI", "key": "hi", "from": current, "to": target,
            "from_clock": eq_clock(current), "to_clock": eq_clock(target),
            "direction": "clockwise (right)" if d > 0 else "counter-clockwise (left)",
            "why": why, "metric": "air", "expected_shift": round(_metric_shift("air", hi_db=d), 1)}


def _distance_move(value: float, rng: tuple) -> dict | None:
    """Low end is set by mic distance (proximity effect), not by the LOW knob: the 80 Hz shelf
    moves this measurement by only ~0.2 dB per 3 dB on a ProFX6v3 with LOW CUT in."""
    lo, hi = rng
    if value > hi:
        return {"type": "position", "control": "MIC DISTANCE", "key": "distance", "metric": "boom", "expect": "down",
                "why": f"your low end is {value - hi:.0f} dB above the range — boomy (you're close to the mic)",
                "text": "Move about 3–5 cm further from the mic (or tilt it slightly off your mouth). Keep that distance while recording."}
    if value < lo - 2:
        return {"type": "position", "control": "MIC DISTANCE", "key": "distance", "metric": "boom", "expect": "up",
                "why": f"your low end is {lo - value:.0f} dB below the range — thin",
                "text": "Move about 2–3 cm closer to the mic — being closer adds warmth (proximity effect)."}
    return None


def analyse(blocks: list, silence: list, floor: float | None, current: dict) -> dict:
    """blocks: [(stereo float32 100 ms, kweighted_ms, speaking, peak_db)] from the monitor."""
    if not blocks:
        raise ValueError("No audio captured")
    stereo = np.concatenate([b[0] for b in blocks]).astype(np.float32)
    mono = stereo.mean(axis=1)
    mask = _speech_mask(mono)
    speech_secs = mask.sum() / RATE
    current = {"low_cut": True, "low": 0.0, "hi": 0.0, **(current or {})}
    result: dict = {"speech_seconds": round(float(speech_secs), 1), "current": current, "notes": []}
    peak_all = 20 * np.log10(np.abs(stereo).max() + 1e-9)
    if speech_secs < 8:
        if peak_all < -50:
            result["error"] = ("Almost no signal. Check: mic plugged into Mic/Line 1, the 48V switch on if it's a condenser "
                               "mic, channel LEVEL at U, and the right input selected.")
        else:
            result["error"] = f"Only heard {speech_secs:.0f} s of speech — read the whole passage, at your recording volume."
        return result

    speech = stereo[mask]
    meter = pyloudnorm.Meter(RATE)
    loudness = float(meter.integrated_loudness(speech))
    blk = RATE // 10
    peaks = np.array([20 * np.log10(np.abs(speech[i:i + blk]).max() + 1e-9) for i in range(0, len(speech) - blk, blk)])
    p90, pmax = float(np.percentile(peaks, 90)), float(peaks.max())
    rms_avg = float(20 * np.log10(np.sqrt(np.mean(speech ** 2)) + 1e-9))
    rms_lr = np.sqrt((speech ** 2).mean(axis=0))
    balance = float(20 * np.log10((rms_lr[0] + 1e-9) / (rms_lr[1] + 1e-9)))
    result["level"] = {"peak_p90": round(p90, 1), "peak_max": round(pmax, 1), "rms": round(rms_avg, 1),
                       "loudness": round(loudness, 1), "target_peaks": PEAK_TARGET, "target_rms": -18.0}
    result["balance"] = round(balance, 1)
    result["floor"] = floor

    steps = []
    # 1. GAIN (level) — dead band: only when clearly outside −12…−6 dBFS peaks
    if pmax > -1:
        steps.append({"type": "gain", "control": "GAIN", "key": "gain", "delta": round(-9 - p90), "direction": "counter-clockwise (left)",
                      "why": f"your loudest words clip ({pmax:.1f} dBFS)"})
    elif p90 < PEAK_TARGET[0] - 2:
        steps.append({"type": "gain", "control": "GAIN", "key": "gain", "delta": round(-9 - p90), "direction": "clockwise (right)",
                      "why": f"speech peaks at {p90:.0f} dBFS, target −12…−6"})
    elif p90 > PEAK_TARGET[1] + 2:
        steps.append({"type": "gain", "control": "GAIN", "key": "gain", "delta": round(-9 - p90), "direction": "counter-clockwise (left)",
                      "why": f"speech peaks at {p90:.0f} dBFS, target −12…−6"})
    # 2. STEREO PAN switch
    if abs(balance) > 6:
        steps.append({"type": "switch", "control": "STEREO PAN", "key": "stereo_pan", "to": False,
                      "why": f"your voice is {abs(balance):.0f} dB louder on the {'left' if balance > 0 else 'right'} — the switch is IN"})
    # 3. LOW CUT: always in for a voice (best practice: high-pass 80–100 Hz)
    if not current.get("low_cut", True):
        steps.append({"type": "switch", "control": "LOW CUT", "key": "low_cut", "to": True, "why": "a voice always wants the 100 Hz low cut — it removes rumble"})

    # 4. tone
    levels = third_octave_spectrum(speech.mean(axis=1))
    tone = measure_tone(levels)
    ranges, range_name = load_ranges()
    gauges = {}
    for key, (_b, _r, label, knob, _typ) in METRICS.items():
        lo, hi = ranges[key]
        v = tone[key]
        gauges[key] = {"label": label, "value": v, "range": [lo, hi], "knob": knob,
                       "verdict": "low" if v < lo else "high" if v > hi else "ok"}
    move = _distance_move(tone["boom"], ranges["boom"])
    if move:
        steps.append(move)
    move = _hi_move(tone["air"], ranges["air"], float(current.get("hi", 0.0)))
    if move:
        steps.append(move)
    if abs(float(current.get("low", 0.0))) >= 1.5:
        steps.append({"type": "knob", "control": "LOW", "key": "low", "from": float(current["low"]), "to": 0.0,
                      "from_clock": eq_clock(float(current["low"])), "to_clock": eq_clock(0.0),
                      "direction": "back to the centre click",
                      "why": "with LOW CUT in, the 80 Hz LOW knob barely affects a voice — keep it flat"})
    result["tone"] = tone
    result["gauges"] = gauges
    result["range_name"] = range_name
    result["steps"] = steps
    result["recommended"] = {
        "low_cut": True,
        "low": 0.0,
        "hi": next((s["to"] for s in steps if s.get("key") == "hi"), current.get("hi", 0.0)),
    }

    # Things the ProFX6v3 can't change (no mid EQ, no compressor)
    if gauges["boxy"]["verdict"] == "high":
        result["notes"].append("Boxy (250–500 Hz): move the mic a little further away or slightly off-axis, add soft furnishings, or cut about −3 dB at 350 Hz in your recording software.")
    if gauges["presence"]["verdict"] == "low":
        result["notes"].append("Muffled: point the mic straight at your mouth, or add about +3 dB at 3 kHz in software.")
    if gauges["presence"]["verdict"] == "high":
        result["notes"].append("Harsh: angle the mic slightly off your mouth, or cut about −3 dB at 3 kHz in software.")
    if gauges["sibilance"]["verdict"] == "high":
        result["notes"].append("Strong 's' sounds: angle the mic slightly off-axis; in OBS a de-esser (or EQ −3 dB at 6–7 kHz) helps.")
    if floor is not None and floor > -58:
        result["notes"].append(f"Background noise is high ({floor:.0f} dBFS between words): get closer to the mic and lower GAIN; turn off fans/AC.")

    # 5. recording-software chain (simulated on the voice, with the recommended changes)
    d_low = result["recommended"]["low"] - current.get("low", 0.0)
    d_hi = result["recommended"]["hi"] - current.get("hi", 0.0)
    fx = []
    if abs(d_low) > 0.01:
        fx.append(LowShelfFilter(cutoff_frequency_hz=80, gain_db=d_low, q=0.7071))
    if abs(d_hi) > 0.01:
        fx.append(HighShelfFilter(cutoff_frequency_hz=12000, gain_db=d_hi, q=0.7071))
    voice = Pedalboard(fx)(speech.T.astype(np.float32), RATE).T if fx else speech
    gain_step = next((s for s in steps if s["key"] == "gain"), None)
    if gain_step:
        voice = voice * 10 ** (gain_step["delta"] / 20)
    rms_db = 20 * np.log10(np.sqrt(np.mean(voice ** 2)) + 1e-9)
    threshold = float(np.clip(round(rms_db + 2), -40, -8))
    comp = Pedalboard([Compressor(threshold_db=threshold, ratio=3.5, attack_ms=6, release_ms=80)])
    makeup = float(np.clip(RECORDING_LUFS - meter.integrated_loudness(comp(voice.T.astype(np.float32), RATE).T), -6, 24))
    # pedalboard's Limiter adds its own makeup gain (OBS's doesn't): model it as a fast 20:1 compressor at −1 dBFS.
    final = Pedalboard([Compressor(threshold_db=threshold, ratio=3.5, attack_ms=6, release_ms=80), Gain(gain_db=makeup),
                        Compressor(threshold_db=-1.0, ratio=20, attack_ms=0.5, release_ms=60)])(voice.T.astype(np.float32), RATE).T
    gate = None
    if floor is not None and floor > -62:
        gate = {"open_db": round(floor + 18), "close_db": round(floor + 12), "attack_ms": 25, "hold_ms": 200, "release_ms": 150}
    result["software"] = {
        "compressor": {"ratio": 3.5, "threshold_db": threshold, "attack_ms": 6, "release_ms": 80, "output_gain_db": round(makeup, 1)},
        "limiter": {"threshold_db": -1.0, "release_ms": 60},
        "noise_gate": gate,
        "predicted": {"loudness": round(float(meter.integrated_loudness(final)), 1),
                      "peak": round(float(20 * np.log10(np.abs(final).max() + 1e-9)), 1)},
    }
    _log(result)
    return result


LOG = Path.home() / ".config" / "nikon-remote" / "voice-checks.jsonl"


def _log(result: dict) -> None:
    """Keep a history of checks (helps explain advice later)."""
    import time as _t

    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({"t": _t.strftime("%Y-%m-%dT%H:%M:%S"), **{k: result.get(k) for k in
                                ("current", "level", "tone", "steps", "balance", "floor", "speech_seconds")}}) + "\n")
    except OSError:
        pass


# Rainbow Passage (Fairbanks, 1960) — public domain, the standard phonetically
# balanced passage used in speech science. Reading the same text every time
# makes checks comparable.
SCRIPT = (
    "When the sunlight strikes raindrops in the air, they act as a prism and form a rainbow. "
    "The rainbow is a division of white light into many beautiful colors. "
    "These take the shape of a long round arch, with its path high above, and its two ends apparently beyond the horizon. "
    "There is, according to legend, a boiling pot of gold at one end. "
    "People look, but no one ever finds it. "
    "When a man looks for something beyond his reach, his friends say he is looking for the pot of gold at the end of the rainbow. "
    "Throughout the centuries people have explained the rainbow in various ways. "
    "Some have accepted it as a miracle without physical explanation."
)
