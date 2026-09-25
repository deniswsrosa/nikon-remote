"""A synthetic talking voice: glottal pulses through vowel formants, in syllables.
WebRTC VAD classifies ~90% of it as speech, so tests don't need recordings."""

import numpy as np
from scipy.signal import butter, lfilter

RATE = 48000
VOWELS = [(730, 1090, 2440), (270, 2290, 3010), (530, 1840, 2480), (570, 840, 2410), (300, 870, 2240)]


def voice(secs: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(RATE * secs)
    out = np.zeros(n)
    pos = 0
    while pos < n:
        syl = int(RATE * rng.uniform(0.15, 0.3))
        gap = int(RATE * rng.uniform(0.03, 0.12))
        f0 = rng.uniform(105, 140)
        t = np.arange(syl)
        phase = np.cumsum(np.full(syl, f0) * (1 + 0.03 * np.sin(2 * np.pi * 3 * t / RATE)) / RATE)
        src = (np.diff(np.floor(phase), prepend=0) > 0).astype(float) + 0.02 * rng.standard_normal(syl)
        y = src
        for f, bw in zip(VOWELS[rng.integers(len(VOWELS))], (90, 110, 160)):
            r = np.exp(-np.pi * bw / RATE)
            y = lfilter([1 - r], [1, -2 * r * np.cos(2 * np.pi * f / RATE), r * r], y)
        # breathiness plus an occasional "s"/"f" (fricatives carry speech's highs)
        b, a = butter(2, [2500, 7000], "bandpass", fs=RATE)
        hiss = lfilter(b, a, rng.standard_normal(syl))
        b, a = butter(2, 10000, "highpass", fs=RATE)
        air = lfilter(b, a, rng.standard_normal(syl))
        y = y / (np.abs(y).max() + 1e-9) + 0.03 * hiss + 0.0012 * air
        if rng.random() < 0.35:
            b, a = butter(2, [4500, 10000], "bandpass", fs=RATE)
            fric = lfilter(b, a, rng.standard_normal(syl)) * 0.6
            y = np.concatenate([fric[: syl // 3], y[syl // 3:]])
        y *= np.hanning(syl)
        end = min(syl, n - pos)
        out[pos:pos + end] = y[:end]
        pos += syl + gap
    return (out / np.abs(out).max()).astype(np.float32)
