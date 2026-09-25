"""ProFX6v3 advice on a synthetic voice with known problems."""

import numpy as np
from pedalboard import HighShelfFilter, LowShelfFilter, Pedalboard

from nikon_remote import mixer
from tests.voice import RATE, voice

FLAT = {"low_cut": True, "low": 0.0, "hi": 0.0}


def blocks_of(stereo):
    return [(stereo[i:i + 4800], 0.0, True, 0.0) for i in range(0, len(stereo) - 4800, 4800)]


def analyse(level_db=-8, lr=(1.0, 1.0), fx=None, current=FLAT, secs=14):
    v = voice(secs, seed=3)
    if fx is not None:
        v = fx(v[None, :], RATE)[0]
    v = v / np.abs(v).max() * 10 ** (level_db / 20)
    return mixer.analyse(blocks_of(np.stack([v * lr[0], v * lr[1]], axis=1)), [], -80.0, current)


def test_silence_is_reported_as_no_signal():
    silent = np.zeros((RATE * 10, 2), np.float32)
    r = mixer.analyse(blocks_of(silent), [], -90.0, FLAT)
    assert "Almost no signal" in r["error"]


def test_gain_advice_follows_level():
    assert analyse(-30)["controls"]["gain"]["action"] == "up"
    assert analyse(-8)["controls"]["gain"]["action"] == "ok"
    assert analyse(-0.2)["controls"]["gain"]["action"] == "down"


def test_one_sided_voice_means_stereo_pan_switch_is_in():
    r = analyse(lr=(1.0, 0.05))
    assert r["controls"]["stereo_pan"]["action"] == "release"


def test_boomy_voice_gets_low_turned_down():
    boomy = Pedalboard([LowShelfFilter(cutoff_frequency_hz=150, gain_db=12)])
    assert analyse(fx=boomy)["recommended"]["low"] < analyse()["recommended"]["low"]


def test_dull_voice_gets_hi_turned_up():
    dull = Pedalboard([HighShelfFilter(cutoff_frequency_hz=6000, gain_db=-12)])
    assert analyse(fx=dull)["recommended"]["hi"] > analyse()["recommended"]["hi"]


def test_second_check_is_relative_to_current_settings():
    # Having already set LOW to −6, the same (unchanged) voice shouldn't be pushed further.
    first = analyse()["recommended"]["low"]
    again = analyse(current={"low_cut": True, "low": first, "hi": 0.0}, fx=Pedalboard([LowShelfFilter(cutoff_frequency_hz=80, gain_db=first)]))
    assert abs(again["recommended"]["low"] - first) <= 1.5


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
