import numpy as np

from nikon_remote.audio import BLOCK, RATE, AudioMonitor
from tests.voice import voice


def run_blocks(signal: np.ndarray):
    """Feed a stereo float signal through the monitor; return the emitted states."""
    states = []
    mon = AudioMonitor(lambda kind, payload: states.append(payload))
    for i in range(0, len(signal) - BLOCK + 1, BLOCK):
        mon._process(signal[i:i + BLOCK].astype(np.float32))
    return mon, states


def tone(freq, dbfs, secs):
    t = np.arange(int(RATE * secs)) / RATE
    x = 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t)
    return np.stack([x, x], axis=1)


def test_k_weighted_loudness_matches_bs1770_reference():
    # A 1 kHz sine peaking at −20 dBFS in both channels reads −20 LUFS (±0.5).
    _, states = run_blocks(tone(997, -20, 4))
    assert abs(states[-1]["lufs_s"] - (-20.0)) < 0.5
    assert abs(states[-1]["peak"] - (-20.0)) < 0.2


def live_hint(level_db):
    v = voice(14, seed=1) * 10 ** (level_db / 20)
    quiet = np.zeros((RATE * 2, 2)) + 1e-5  # lets the monitor learn the noise floor first
    _, states = run_blocks(np.concatenate([quiet, np.stack([v, v], axis=1)]))
    return states[-1]["gain_hint"]["action"]


def test_live_gain_hint():
    assert live_hint(-30) == "up"
    assert live_hint(-8) == "ok"
    assert live_hint(-0.5) == "down"
