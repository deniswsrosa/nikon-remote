"""Voice analysis → exact settings for a Mackie ProFX6v3 Mic/Line channel.

The ProFX6v3 channel 1/2 strip (per Mackie's owner's manual, 2024):
  GAIN knob (mic 0…+60 dB) + level-set LED · LOW CUT switch (100 Hz, 18 dB/oct)
  HI knob (±15 dB shelf above 12 kHz, flat at the centre detent)
  LOW knob (±15 dB shelf below 80 Hz, flat at the centre detent)
  FX switch · STEREO PAN switch (in = ch 1 feeds only the LEFT side)
  LEVEL knob (off … U … +10 dB)
It has no compressor and no mid EQ, and its USB feed is the main mix *before*
the MAIN MIX fader — so MAIN MIX doesn't change the recording.

Everything here works on a captured stretch of your voice: speech is found
with WebRTC VAD, loudness is measured with pyloudnorm (ITU-R BS.1770), and the
recommended EQ and the recording-software compressor are *simulated* on your
own audio with Spotify's pedalboard before being suggested.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pyloudnorm
import webrtcvad
from pedalboard import Compressor, Gain, HighpassFilter, HighShelfFilter, LowShelfFilter, Pedalboard

RATE = 48000
REFERENCE = Path.home() / ".config" / "nikon-remote" / "voice_reference.json"

# 1/3-octave centres used for the voice's long-term spectrum.
THIRD_OCTAVES = [63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000,
                 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000]

# Built-in target: a close-miked "podcast" voice — warm low-mids, gentle ~3 dB/octave
# roll-off above 1 kHz. It's a starting point; upload a reference voice to match
# a sound you like instead. Relative dB, 0 at 1 kHz.
DEFAULT_TARGET = [-14, -9, -5, -2, 0, 1, 2, 2, 2, 2, 1.5, 0.5, 0, -1, -2, -3,
                  -3.5, -4, -5, -6, -7.5, -9.5, -12, -15, -20]

# How much each third-octave matters when fitting the two shelves: the mixer
# can only change the lows and highs, so the mids only anchor the level.
WEIGHTS = np.array([0.6, 1, 1, 1, 1, 0.8, 0.5, 0.3, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2,
                    0.2, 0.2, 0.3, 0.5, 0.8, 1, 1, 1, 0.6])

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


def _normalise(levels: np.ndarray) -> np.ndarray:
    """0 dB at the 500 Hz–2 kHz average, so comparisons ignore overall level."""
    mids = [i for i, f in enumerate(THIRD_OCTAVES) if 500 <= f <= 2000]
    return levels - levels[mids].mean()


def load_target() -> tuple[np.ndarray, str]:
    try:
        ref = json.loads(REFERENCE.read_text())
        return np.array(ref["levels"]), ref.get("name", "your reference voice")
    except (OSError, ValueError, KeyError):
        return np.array(DEFAULT_TARGET, float), "built-in podcast voice"


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
    levels = _normalise(third_octave_spectrum(speech))
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps({"name": name, "levels": levels.round(2).tolist(), "speech_seconds": len(speech) / RATE}))
    return {"name": name, "speech_seconds": round(len(speech) / RATE, 1)}


def clear_reference() -> None:
    REFERENCE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# fitting the two shelves (+ low cut) on the actual voice

def _chain_response(stereo_voice: np.ndarray, low_db: float, hi_db: float, low_cut: bool) -> np.ndarray:
    fx = []
    if low_cut:
        # 18 dB/octave at 100 Hz ≈ three cascaded 6 dB/oct high-passes
        fx += [HighpassFilter(cutoff_frequency_hz=100)] * 3
    if abs(low_db) > 0.01:
        fx.append(LowShelfFilter(cutoff_frequency_hz=80, gain_db=low_db, q=0.7071))
    if abs(hi_db) > 0.01:
        fx.append(HighShelfFilter(cutoff_frequency_hz=12000, gain_db=hi_db, q=0.7071))
    return Pedalboard(fx)(stereo_voice.T.astype(np.float32), RATE).T if fx else stereo_voice


def _shelf_gain_db(freqs: np.ndarray, fc: float, gain: float, kind: str) -> np.ndarray:
    """Magnitude of an RBJ shelving biquad (Q=0.707) — fast stand-in for the grid search."""
    from scipy.signal import freqz

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


def _hp_db(freqs: np.ndarray) -> np.ndarray:
    from scipy.signal import butter, freqz

    b, a = butter(3, 100, "highpass", fs=RATE)
    _, h = freqz(b, a, worN=freqs, fs=RATE)
    return 20 * np.log10(np.abs(h) + 1e-12)


def fit_eq(measured: np.ndarray, target: np.ndarray, current: dict) -> dict:
    """Best LOW / HI / LOW CUT settings, as absolute knob values, given what the
    channel is set to now (the measurement already includes those settings)."""
    freqs = np.array(THIRD_OCTAVES, float)
    cur_low, cur_hi, cur_cut = current.get("low", 0.0), current.get("hi", 0.0), bool(current.get("low_cut", True))
    # Undo the current settings to estimate the "flat channel" voice.
    flat = measured - _shelf_gain_db(freqs, 80, cur_low, "low") - _shelf_gain_db(freqs, 12000, cur_hi, "high")
    if cur_cut:
        flat = flat - np.maximum(_hp_db(freqs), -30)  # can't recover what's fully filtered out
    best = None
    for cut in (True, False):
        base = flat + (_hp_db(freqs) if cut else 0)
        for low in np.arange(-12, 6.1, 1.5):  # bigger LOW boosts mostly add rumble
            lo_resp = _shelf_gain_db(freqs, 80, low, "low")
            for hi in np.arange(-12, 6.1, 1.5):  # a shelf can't create highs the mic didn't capture
                cand = _normalise(base + lo_resp + _shelf_gain_db(freqs, 12000, hi, "high"))
                err = float(np.sum(WEIGHTS * (cand - target) ** 2) / WEIGHTS.sum())
                # prefer small moves and keeping the low cut in (voice + rumble protection)
                err += 0.02 * (low ** 2 + hi ** 2) / 9 + (0 if cut else 1.5)
                if best is None or err < best[0]:
                    best = (err, cut, float(low), float(hi), cand)
    err, cut, low, hi, cand = best
    return {"low_cut": cut, "low": low, "hi": hi, "residual_db": round(float(np.sqrt(np.mean((cand - target)[WEIGHTS >= 0.5] ** 2))), 1),
            "after": cand.round(1).tolist()}


# ---------------------------------------------------------------------------

def analyse(blocks: list, silence: list, floor: float | None, current: dict) -> dict:
    """blocks: [(stereo float32 100 ms, kweighted_ms, speaking, peak_db)] from the monitor."""
    if not blocks:
        raise ValueError("No audio captured")
    stereo = np.concatenate([b[0] for b in blocks]).astype(np.float32)
    mono = stereo.mean(axis=1)
    mask = _speech_mask(mono)
    speech_secs = mask.sum() / RATE
    result: dict = {"speech_seconds": round(float(speech_secs), 1), "current": current, "steps": [], "notes": []}
    peak_all = 20 * np.log10(np.abs(stereo).max() + 1e-9)
    if speech_secs < 4:
        if peak_all < -50:
            result["error"] = ("Almost no signal. Check: mic plugged into Mic/Line 1, the 48V switch on if it's a condenser "
                               "mic, channel LEVEL at U, and the right input selected.")
        else:
            result["error"] = "Not enough speech — talk continuously, at your recording volume, for the whole check."
        return result

    speech = stereo[mask]
    meter = pyloudnorm.Meter(RATE)
    loudness = float(meter.integrated_loudness(speech))
    # 100 ms peaks while talking
    blk = RATE // 10
    peaks = np.array([20 * np.log10(np.abs(speech[i:i + blk]).max() + 1e-9) for i in range(0, len(speech) - blk, blk)])
    p90, pmax = float(np.percentile(peaks, 90)), float(peaks.max())
    rms_lr = np.sqrt((speech ** 2).mean(axis=0))
    balance = float(20 * np.log10((rms_lr[0] + 1e-9) / (rms_lr[1] + 1e-9)))
    result.update(loudness=round(loudness, 1), peak_p90=round(p90, 1), peak_max=round(pmax, 1), balance=round(balance, 1),
                  floor=floor)

    # ---- GAIN -----------------------------------------------------------
    if pmax > -1:
        need = -9 - p90
        gain = {"action": "down", "db": round(need), "text": f"Clipping. Turn GAIN counter-clockwise ≈ {abs(need):.0f} dB "
                "(about a third of that in clock-hours) — the level-set LED should only flicker on your loudest words."}
    elif p90 < PEAK_TARGET[0]:
        need = -9 - p90
        gain = {"action": "up", "db": round(need), "text": f"Too quiet. Turn GAIN clockwise ≈ +{need:.0f} dB. Use the live GAIN "
                "hint at the bottom of the screen while you talk — stop when it says OK."}
    elif p90 > PEAK_TARGET[1]:
        need = -9 - p90
        gain = {"action": "down", "db": round(need), "text": f"A little hot. Turn GAIN counter-clockwise ≈ {abs(need):.0f} dB."}
    else:
        gain = {"action": "ok", "db": 0, "text": f"Good — speech peaks around {p90:.0f} dBFS."}

    # ---- STEREO PAN switch --------------------------------------------------
    if abs(balance) > 6:
        pan = {"state": False, "action": "release", "text": f"Your voice is {abs(balance):.0f} dB louder on the "
               f"{'left' if balance > 0 else 'right'}: the STEREO PAN switch on channel 1 is pressed in. Press it again so it's OUT."}
    else:
        pan = {"state": False, "action": "ok", "text": "OUT — voice is in both sides. Good."}

    # ---- EQ fit -------------------------------------------------------------
    target, target_name = load_target()
    measured = _normalise(third_octave_spectrum(speech.mean(axis=1)))
    fit = fit_eq(measured, target, current)
    before_err = float(np.sqrt(np.mean((measured - target)[WEIGHTS >= 0.5] ** 2)))

    def eq_step(key, label, freq):
        old, new = float(current.get(key, 0.0)), fit[key]
        if abs(new - old) < 1.5:
            return {"value": old, "action": "ok", "text": f"Leave at {eq_clock(old)}."}
        verb = "boost" if new > old else "cut"
        return {"value": new, "action": "set", "text": f"Turn {label} to {eq_clock(new)} ({new:+.1f} dB) — {verb} {freq}."}

    low = eq_step("low", "LOW", "below 80 Hz")
    hi = eq_step("hi", "HI", "above 12 kHz")
    if fit["low_cut"] != bool(current.get("low_cut", True)):
        cut = {"state": fit["low_cut"], "action": "press",
               "text": "Press LOW CUT so it's IN (removes rumble below 100 Hz)." if fit["low_cut"]
               else "Release LOW CUT (OUT) — your voice needs its low end."}
    else:
        cut = {"state": fit["low_cut"], "action": "ok", "text": "Keep IN." if fit["low_cut"] else "Keep OUT."}

    # Things the ProFX6v3 can't fix (no mid EQ): advice for mic technique / software EQ.
    mids = {f: measured[i] - target[i] for i, f in enumerate(THIRD_OCTAVES)}
    boxy = np.mean([mids[f] for f in (250, 315, 400, 500)])
    presence = np.mean([mids[f] for f in (2500, 3150, 4000)])
    if boxy > 3:
        result["notes"].append(f"Your voice is {boxy:.0f} dB 'boxy' around 250–500 Hz (the mixer has no mid EQ): move the mic "
                               "5–10 cm further away or slightly off-axis, or add a software EQ cut of about −3 dB at 350 Hz.")
    if presence < -3:
        result["notes"].append(f"Speech clarity (2.5–4 kHz) is {abs(presence):.0f} dB low: point the mic straight at your mouth, "
                               "or add a software EQ boost of about +3 dB at 3 kHz.")
    if presence > 4:
        result["notes"].append("Harsh around 3 kHz: angle the mic slightly off your mouth, or cut about −3 dB at 3 kHz in software.")
    air = np.mean([mids[f] for f in (8000, 10000, 12500)])
    if air < -12:
        result["notes"].append(f"Almost nothing above 8 kHz ({abs(air):.0f} dB below the target) — more than the HI knob can fix. "
                               "Check the mic points at your mouth, isn't behind a thick windscreen, and that the input isn't low-quality (e.g. a phone/USB headset).")
    if floor is not None and floor > -58:
        result["notes"].append(f"Background noise is high ({floor:.0f} dBFS between words): get closer to the mic and lower GAIN; "
                               "turn off fans/AC. A noise gate in your recording software can help (see below).")

    # ---- Recording-software chain (ProFX6v3 has no compressor) --------------
    eq_voice = _chain_response(speech, fit["low"] - current.get("low", 0.0), fit["hi"] - current.get("hi", 0.0),
                               fit["low_cut"] and not current.get("low_cut", True))
    gain_fix = (-9 - p90) if gain["action"] != "ok" else 0.0
    eq_voice = eq_voice * 10 ** (gain_fix / 20)
    rms_db = 20 * np.log10(np.sqrt(np.mean(eq_voice ** 2)) + 1e-9)
    threshold = float(np.clip(round(rms_db + 2), -40, -8))
    comp = Pedalboard([Compressor(threshold_db=threshold, ratio=3.5, attack_ms=6, release_ms=80)])
    compressed = comp(eq_voice.T.astype(np.float32), RATE).T
    makeup = float(np.clip(RECORDING_LUFS - meter.integrated_loudness(compressed), -6, 24))
    # Same order as OBS: compressor, its output gain, then the limiter.
    # pedalboard's Limiter adds its own makeup gain (OBS's doesn't), so model the
    # limiter as a fast 20:1 compressor at −1 dBFS with no makeup.
    final = Pedalboard([Compressor(threshold_db=threshold, ratio=3.5, attack_ms=6, release_ms=80), Gain(gain_db=makeup),
                        Compressor(threshold_db=-1.0, ratio=20, attack_ms=0.5, release_ms=60)])(eq_voice.T.astype(np.float32), RATE).T
    final_lufs = float(meter.integrated_loudness(final))
    final_peak = float(20 * np.log10(np.abs(final).max() + 1e-9))
    gate = None
    if floor is not None and floor > -62:
        gate = {"open_db": round(floor + 18), "close_db": round(floor + 12), "attack_ms": 25, "hold_ms": 200, "release_ms": 150}

    result["controls"] = {"gain": gain, "low_cut": cut, "hi": hi, "low": low,
                          "fx": {"state": False, "action": "ok", "text": "OUT — no reverb on a talking voice."},
                          "stereo_pan": pan,
                          "level": {"action": "ok", "text": "At the U mark (unity). It changes the recording; MAIN MIX doesn't."}}
    result["recommended"] = {"low_cut": fit["low_cut"], "low": fit["low"], "hi": fit["hi"]}
    result["tone"] = {"target": target_name, "freqs": THIRD_OCTAVES, "measured": measured.round(1).tolist(),
                      "target_curve": target.round(1).tolist(), "after": fit["after"],
                      "error_before": round(before_err, 1), "error_after": fit["residual_db"]}
    result["software"] = {
        "compressor": {"ratio": 3.5, "threshold_db": threshold, "attack_ms": 6, "release_ms": 80, "output_gain_db": round(makeup, 1)},
        "limiter": {"threshold_db": -1.0, "release_ms": 60},
        "noise_gate": gate,
        "predicted": {"loudness": round(final_lufs, 1), "peak": round(final_peak, 1)},
    }
    return result
