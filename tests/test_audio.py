import numpy as np

from nikon_remote.audio import BLOCK, RATE, AudioMonitor, analyse_voice


def run_blocks(signal: np.ndarray):
    """Feed a stereo float signal through the monitor; return (monitor, emitted states)."""
    states = []
    mon = AudioMonitor(lambda kind, payload: states.append(payload))
    for i in range(0, len(signal) - BLOCK + 1, BLOCK):
        mon._process(signal[i:i + BLOCK].astype(np.float32))
    return mon, states


def tone(freq, dbfs, secs, channels=(1.0, 1.0)):
    t = np.arange(int(RATE * secs)) / RATE
    x = 10 ** (dbfs / 20) * np.sin(2 * np.pi * freq * t)
    return np.stack([x * channels[0], x * channels[1]], axis=1)


def speechlike(level_dbfs, secs, rng, low_rumble=0.0, channels=(1.0, 1.0)):
    """Noise shaped roughly like speech, in 250 ms syllables separated by short pauses."""
    n = int(RATE * secs)
    noise = rng.standard_normal(n)
    # crude speech spectrum: emphasise 200 Hz–3 kHz
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(n, 1 / RATE)
    shape = np.where(f < 100, 0.05, 1.0) * np.where(f > 3000, (3000 / np.maximum(f, 1)) ** 1.5, 1.0)
    x = np.fft.irfft(spec * shape, n)
    env = (np.sin(2 * np.pi * 2 * np.arange(n) / RATE) > -0.3).astype(float)
    x = x * env
    x = x / np.abs(x).max() * 10 ** (level_dbfs / 20)
    if low_rumble:
        x = x + low_rumble * np.sin(2 * np.pi * 40 * np.arange(n) / RATE)
    return np.stack([x * channels[0], x * channels[1]], axis=1)


def test_k_weighted_loudness_matches_bs1770_reference():
    # A 1 kHz sine peaking at −20 dBFS in both channels reads −20 LUFS (±0.5).
    _, states = run_blocks(tone(997, -20, 4))
    assert abs(states[-1]["lufs_s"] - (-20.0)) < 0.5
    assert abs(states[-1]["peak"] - (-20.0)) < 0.2


def feed_check(signal):
    mon, _ = run_blocks(np.zeros((RATE * 3, 2)) + 1e-5)  # establish a noise floor
    fut = mon.voice_check(seconds=len(signal) / RATE - 0.2)
    for i in range(0, len(signal) - BLOCK + 1, BLOCK):
        mon._process(signal[i:i + BLOCK].astype(np.float32))
    return fut.result(timeout=1)


def controls(report, level=None):
    return {(r["control"], r["action"]) for r in report["recommendations"] if level is None or r["level"] == level}


def test_silence_asks_to_check_input():
    report = analyse_voice([(np.zeros((BLOCK, 2)), 1e-12, False, -120)] * 100, [], -90)
    assert ("INPUT", "check") in controls(report)


def test_clipping_voice_says_gain_down():
    rng = np.random.default_rng(1)
    report = feed_check(speechlike(-0.1, 12, rng))
    assert ("GAIN", "down") in controls(report, "bad")


def test_quiet_voice_says_gain_up():
    rng = np.random.default_rng(2)
    report = feed_check(speechlike(-30, 12, rng))
    assert ("GAIN", "up") in controls(report)


def test_good_level_voice_is_ok():
    rng = np.random.default_rng(3)
    report = feed_check(speechlike(-8, 12, rng))
    assert ("GAIN", "ok") in controls(report, "ok")


def test_voice_on_one_side_says_center_pan():
    rng = np.random.default_rng(4)
    report = feed_check(speechlike(-8, 12, rng, channels=(1.0, 0.1)))
    assert ("PAN", "center") in controls(report)


def test_rumble_says_low_cut():
    rng = np.random.default_rng(5)
    report = feed_check(speechlike(-10, 12, rng, low_rumble=0.2))
    assert ("LOW CUT", "press") in controls(report)
