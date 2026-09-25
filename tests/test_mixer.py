"""ProFX6v3 advice on a synthetic voice with known problems."""

import numpy as np
from pedalboard import HighpassFilter, HighShelfFilter, LowShelfFilter, Pedalboard

from nikon_remote import mixer
from tests.voice import RATE, voice

FLAT = {"low_cut": True, "low": 0.0, "hi": 0.0}


def blocks_of(stereo):
    return [(stereo[i:i + 4800], 0.0, True, 0.0) for i in range(0, len(stereo) - 4800, 4800)]


def analyse(level_db=-8, lr=(1.0, 1.0), fx=None, current=FLAT, secs=20, hiss=0.0):
    v = voice(secs, seed=3)
    if fx is not None:
        v = fx(v[None, :], RATE)[0]
    if hiss:
        v = v + hiss * Pedalboard([HighpassFilter(cutoff_frequency_hz=9000)])(
            np.random.default_rng(1).standard_normal(len(v)).astype(np.float32)[None, :], RATE)[0]
    v = v / np.abs(v).max() * 10 ** (level_db / 20)
    return mixer.analyse(blocks_of(np.stack([v * lr[0], v * lr[1]], axis=1)), [], -80.0, current)


def kinds(r):
    return {(s["type"], s["key"]) for s in r["steps"]}


def step(r, key):
    return next(s for s in r["steps"] if s["key"] == key)


def test_silence_is_reported_as_no_signal():
    silent = np.zeros((RATE * 12, 2), np.float32)
    r = mixer.analyse(blocks_of(silent), [], -90.0, FLAT)
    assert "Almost no signal" in r["error"]


def test_gain_advice_follows_level_with_dead_band():
    assert step(analyse(-30), "gain")["direction"].startswith("clockwise")
    assert step(analyse(-0.2), "gain")["direction"].startswith("counter")
    assert ("gain", "gain") not in kinds(analyse(-8))


def test_one_sided_voice_means_stereo_pan_switch_is_in():
    assert ("switch", "stereo_pan") in kinds(analyse(lr=(1.0, 0.05)))


def test_boomy_voice_gets_moved_back_not_a_low_knob_change():
    r = analyse(fx=Pedalboard([LowShelfFilter(cutoff_frequency_hz=260, gain_db=20)]))
    s = step(r, "distance")
    assert s["expect"] == "down"
    assert ("knob", "low") not in kinds(r)


def test_thin_voice_gets_moved_closer():
    r = analyse(fx=Pedalboard([HighpassFilter(cutoff_frequency_hz=380) for _ in range(3)]))
    assert step(r, "distance")["expect"] == "up"


def test_dull_voice_gets_hi_turned_up_as_a_clock_position():
    r = analyse(fx=Pedalboard([HighShelfFilter(cutoff_frequency_hz=8000, gain_db=-30)]))
    s = step(r, "hi")
    assert s["to"] > 0 and s["direction"].startswith("clockwise")
    assert s["to_clock"] in ("1 o'clock", "2 o'clock")
    assert s["expected_shift"] > 0


def test_hissy_voice_gets_hi_turned_down():
    s = step(analyse(hiss=0.08), "hi")
    assert s["to"] < 0


def test_low_knob_off_centre_is_brought_back_to_flat():
    r = analyse(current={"low_cut": True, "low": -6.0, "hi": 0.0}, fx=Pedalboard([LowShelfFilter(cutoff_frequency_hz=80, gain_db=-6)]))
    s = step(r, "low")
    assert s["to"] == 0.0 and s["to_clock"].startswith("12")


def test_software_chain_hits_podcast_loudness():
    for level in (-20, -8):
        pred = analyse(level)["software"]["predicted"]
        assert abs(pred["loudness"] - mixer.RECORDING_LUFS) <= 0.7
        assert pred["peak"] <= -0.8


def test_eq_clock_positions():
    assert mixer.eq_clock(0) == "12 o'clock (centre detent)"
    assert mixer.eq_clock(3) == "1 o'clock"
    assert mixer.eq_clock(-3) == "11 o'clock"
    assert mixer.eq_clock(4.5) == "half past 1"
    assert mixer.eq_clock(-6) == "10 o'clock"
