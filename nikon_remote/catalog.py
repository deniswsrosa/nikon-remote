"""D7500 settings catalog: what each PTP property means and how the UI shows it.

Values stay raw on the wire; the browser formats them using `fmt` + `labels`.
Every property the camera reports but that isn't listed here still appears in
the "All settings" tab under its PTP name.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

MOVIE = "movie"
PHOTO = "photo"
BOTH = "both"

ON_OFF = {0: "Off", 1: "On"}
METERING = {2: "Center-weighted", 3: "Matrix", 4: "Spot", 0x8010: "Highlight-weighted"}
WHITE_BALANCE = {
    2: "Auto",
    4: "Daylight",
    5: "Fluorescent",
    6: "Incandescent",
    7: "Flash",
    0x8010: "Cloudy",
    0x8011: "Shade",
    0x8012: "Kelvin",
    0x8013: "Preset manual",
    0x8015: "Same as photo",
}
PICTURE_CONTROL = {
    1: "Standard",
    2: "Neutral",
    3: "Vivid",
    4: "Monochrome",
    5: "Portrait",
    6: "Landscape",
    7: "Flat",
    8: "Auto",
    100: "Same as photo",
    **{200 + i: f"Custom {i}" for i in range(1, 10)},
}
# Measured on a D7500 via shadow brightness in movie live view (1080p): raw 0 darkest,
# rising to 4; raw 5 matched the photo setting. Photo ADL follows libgphoto2's D850 table.
MOVIE_ADL = {0: "Off", 1: "Low", 2: "Normal", 3: "High", 4: "Extra high", 5: "Same as photo"}
ACTIVE_D_LIGHTING = {0: "Auto", 1: "Off", 2: "Low", 3: "Normal", 4: "High", 5: "Extra high"}
NOISE_REDUCTION = {0: "Off", 1: "Low", 2: "Normal", 3: "High"}
EXPOSURE_MODE = {
    1: "M",
    2: "P",
    3: "A",
    4: "S",
    0x8010: "AUTO",
    0x8016: "SCENE",
    0x8018: "Flash off",
    0x8019: "EFFECTS",
    0x8050: "U1",
    0x8051: "U2",
}
FRAME_SIZE = {
    0: "3840×2160 30p",
    1: "3840×2160 25p",
    2: "3840×2160 24p",
    3: "1920×1080 60p",
    4: "1920×1080 50p",
    5: "1920×1080 30p",
    6: "1920×1080 25p",
    7: "1920×1080 24p",
    8: "1280×720 60p",
    9: "1280×720 50p",
}
MICROPHONE = {0: "Auto", 1: "High", 2: "Medium", 3: "Low", 4: "Off", 5: "Manual"}
# D7500: 0/2/4 accepted; 3 ("fixed" MF) is rejected by the body.
LV_AF_MODE = {0: "AF-S", 2: "AF-F", 4: "MF"}
LV_AF_AREA = {0: "Face-priority", 1: "Wide-area", 2: "Normal-area", 3: "Subject-tracking", 4: "Pinpoint"}
VF_AF_MODE = {0: "AF-S", 1: "AF-C", 2: "AF-A", 3: "MF", 4: "MF (selection)"}
# Verified on a D7500 via the live view header (value 1 is rejected). 100% = 1 preview px per sensor px.
LV_ZOOM = {0: "Fit", 2: "25%", 3: "33%", 4: "50%", 5: "67%", 6: "100%", 7: "200%"}
LV_SIZE = {1: "QVGA", 2: "VGA", 3: "XGA"}
FLICKER = {0: "50 Hz", 1: "60 Hz", 2: "Auto"}
VIGNETTE = {0: "High", 1: "Normal", 2: "Low", 3: "Off"}
COLOR_SPACE = {0: "sRGB", 1: "Adobe RGB"}
LV_SELECTOR = {0: "Photo", 1: "Movie"}
MOVIE_FILE = {0: "MOV", 1: "MP4"}
MOVIE_QUALITY = {0: "Normal", 1: "High"}


@dataclass
class Setting:
    key: str
    code: int
    label: str
    section: str
    fmt: str = "raw"  # shutter | aperture | iso | ev1000 | kelvin | enum | raw | text
    labels: dict[int, str] | None = None
    scope: str = BOTH
    help: str = ""
    pc_mode: bool = False  # only writable in PC-control mode

    def to_json(self) -> dict:
        d = asdict(self)
        d["code"] = self.code
        if self.labels is not None:
            d["labels"] = {str(k): v for k, v in self.labels.items()}
        return d


@dataclass
class Section:
    key: str
    label: str
    settings: list[Setting] = field(default_factory=list)


S = Setting

# Settings in the "deck" section are the quick controls under the preview
# (dials, focus bar, zoom); the side tabs don't repeat them.
SETTINGS: list[Setting] = [
    # ---- quick controls under the preview --------------------------------
    S("movie_shutter", 0xD1A8, "Shutter speed", "deck", "shutter", None, MOVIE,
      "How long each frame is exposed. For natural-looking motion use about 1/(2 × frame rate): 1/60 at 30p, 1/50 at 25p. Faster looks choppy, slower looks smeary. Under mains-powered lights, 1/60 (60 Hz) or 1/50 (50 Hz) also avoids flicker."),
    S("movie_aperture", 0xD1A9, "Aperture", "deck", "aperture", None, MOVIE,
      "The lens opening. A smaller f-number (f/3.5) lets in more light and blurs the background more; a bigger one (f/8) keeps more in focus but is darker."),
    S("movie_iso", 0xD1AA, "ISO", "deck", "iso", None, MOVIE,
      "Sensor amplification. Raise it to brighten the image when shutter and aperture are set; higher ISO adds noise. On the D7500 up to about ISO 3200 stays clean for YouTube."),
    S("movie_ev", 0xD1AB, "Exposure compensation", "deck", "ev1000", None, MOVIE,
      "EV = exposure value, measured in stops (+1 EV = twice as bright). Tells the camera to make the image brighter (+) or darker (−) than its automatic choice. It only does something when the camera picks part of the exposure itself (Auto ISO or P/S/A mode); in M with Auto ISO off it has no effect."),
    S("movie_wb", 0xD23A, "White balance", "deck", "enum", WHITE_BALANCE, MOVIE,
      "Makes white look white under different light colors. Avoid Auto for video, it can drift mid-shot. Pick 'Kelvin' and set the value to match your light."),
    S("movie_kelvin", 0xD21A, "Color temperature", "deck", "kelvin", None, MOVIE,
      "Light color in Kelvin, used when white balance is 'Kelvin'. Warm household bulbs ≈ 2700–3200 K, most LED video lights ≈ 5600 K, daylight through a window ≈ 5500–6500 K. If skin looks orange, raise the number; if it looks blue, lower it."),
    S("shutter", 0xD100, "Shutter speed", "deck", "shutter", None, PHOTO,
      "How long the sensor is exposed for a photo. Faster freezes motion; slower lets in more light."),
    S("aperture", 0x5007, "Aperture", "deck", "aperture", None, PHOTO,
      "The lens opening. A smaller f-number lets in more light and blurs the background more."),
    S("iso", 0x500F, "ISO", "deck", "iso", None, PHOTO, "Sensor amplification: brighter image, more noise."),
    S("ev", 0x5010, "Exposure compensation", "deck", "ev1000", None, PHOTO,
      "EV = exposure value in stops. Brightens (+) or darkens (−) the camera's automatic exposure. No effect in M with Auto ISO off."),
    S("wb", 0x5005, "White balance", "deck", "enum", WHITE_BALANCE, PHOTO, "Makes white look white under different light colors."),
    S("kelvin", 0xD01E, "Color temperature", "deck", "kelvin", None, PHOTO,
      "Light color in Kelvin, used when white balance is 'Kelvin'."),
    S("lv_af_mode", 0xD061, "Focus mode", "deck", "enum", LV_AF_MODE, BOTH,
      "AF-S focuses once when you click the preview or press AF, then holds: best for a talking head. AF-F keeps refocusing all the time (can 'breathe' on camera). MF: only the Near/Far buttons move focus."),
    S("lv_af_area", 0xD05D, "AF-area mode", "deck", "enum", LV_AF_AREA, BOTH,
      "Normal-area: a small box you place by clicking the preview (click your eye). Wide-area: a bigger box. Face-priority and Subject-tracking pick the point themselves."),
    S("lv_zoom", 0xD1A3, "Preview zoom", "deck", "enum", LV_ZOOM, BOTH,
      "Magnifies the preview around the focus box so you can check focus on your eyes. Doesn't affect the recording."),
    # ---- exposure -------------------------------------------------------
    S("mode", 0x500E, "Exposure mode", "exposure", "enum", EXPOSURE_MODE, BOTH,
      "M (manual) keeps shutter, aperture and ISO exactly where you put them, so brightness never changes during a take — what you want for video. P/S/A let the camera decide some of it. Can be changed from here while the preview is running; the camera's dial takes over again when the app closes.", pc_mode=True),
    S("movie_auto_iso", 0xD0AD, "Auto ISO", "exposure", "enum", ON_OFF, MOVIE,
      "When on, the camera changes ISO by itself even in M, so brightness can pump when you move. Turn it off for talking-head videos."),
    S("movie_metering", 0xD1AF, "Metering", "exposure", "enum", METERING, MOVIE,
      "Which part of the frame the exposure meter looks at. Center-weighted suits a person in the middle of the frame. The meter only advises in M; it doesn't change your settings."),
    S("flicker", 0xD034, "Flicker reduction", "exposure", "enum", FLICKER, MOVIE,
      "Set it to your mains frequency to avoid dark bands rolling through the image under artificial light: 60 Hz in Brazil and the Americas, 50 Hz in Europe and most of Asia/Africa."),
    S("auto_iso", 0xD16A, "Auto ISO", "exposure", "enum", ON_OFF, PHOTO,
      "Photo Auto ISO. When on, the camera overrides the ISO you set."),
    S("metering", 0x500B, "Metering", "exposure", "enum", METERING, PHOTO,
      "Which part of the frame the meter looks at: Matrix = whole frame, Center-weighted = middle, Spot = the focus point."),
    S("exposure_preview", 0xD1A5, "Exposure preview", "exposure", "enum", ON_OFF, PHOTO,
      "Photo mode only: makes the preview show how bright the photo will really be, instead of an automatically brightened image. (Movie mode always shows the real brightness.)", pc_mode=True),
    # ---- image / color ----------------------------------------------------
    S("movie_picture", 0xD237, "Picture Control", "image", "enum", PICTURE_CONTROL, MOVIE,
      "The 'look' baked into the video. Neutral: natural, good straight out of camera. Standard: a bit more contrast and color. Flat: very low contrast, only if you color-grade afterwards."),
    S("movie_adl", 0xD23B, "Active D-Lighting", "image", "enum", MOVIE_ADL, MOVIE,
      "Brightens shadows automatically. Turn it off for a dark background look, otherwise it lifts the background and adds noise. Not available in 4K."),
    S("movie_nr", 0xD236, "High ISO noise reduction", "image", "enum", NOISE_REDUCTION, MOVIE,
      "Smooths out grain at high ISO. Normal is a good balance; High can make skin look waxy."),
    S("picture", 0xD200, "Picture Control", "image", "enum", PICTURE_CONTROL, PHOTO, "The look baked into photos."),
    S("adl", 0xD14E, "Active D-Lighting", "image", "enum", ACTIVE_D_LIGHTING, PHOTO, "Brightens shadows automatically."),
    S("nr", 0xD070, "High ISO noise reduction", "image", "enum", NOISE_REDUCTION, PHOTO, "Smooths out grain at high ISO."),
    S("color_space", 0xD032, "Color space", "image", "enum", COLOR_SPACE, PHOTO, "sRGB for the web; Adobe RGB only for print workflows."),
    S("vignette", 0xD0F7, "Vignette control", "image", "enum", VIGNETTE, BOTH,
      "Brightens the darker corners some lenses produce. Normal is fine."),
    S("distortion", 0xD0F8, "Auto distortion control", "image", "enum", ON_OFF, BOTH,
      "Straightens the barrel distortion of wide-angle lenses. Useful at 18 mm."),
    # ---- video ----------------------------------------------------------
    S("lv_selector", 0xD1A6, "Live view mode", "video", "enum", LV_SELECTOR, BOTH,
      "The photo/movie switch around the camera's Lv button. Must be Movie to record. The app can switch it while the preview runs, but the camera goes back to the physical switch position when the preview restarts — leave the switch on movie.", pc_mode=True),
    S("frame_size", 0xD0A0, "Frame size / rate", "video", "enum", FRAME_SIZE, MOVIE,
      "Resolution and frames per second. 1920×1080 30p is the safe choice for YouTube. 4K on the D7500 crops the image 1.5× (tighter framing) and doesn't allow electronic VR."),
    S("movie_quality", 0xD0A7, "Movie quality", "video", "enum", MOVIE_QUALITY, MOVIE,
      "High quality records at a higher bitrate: fewer compression artifacts, bigger files. Use High."),
    S("movie_file", 0xD0AF, "File type", "video", "enum", MOVIE_FILE, MOVIE,
      "MOV or MP4. Both work in every editor and on YouTube."),
    S("mic", 0xD0A2, "Microphone sensitivity", "video", "enum", MICROPHONE, MOVIE,
      "Applies to the built-in mic and to a mic plugged into the camera's mic jack. Manual keeps the level fixed so it doesn't pump between sentences."),
    S("mic_level", 0xD0A8, "Manual mic level", "video", "raw", None, MOVIE,
      "Used when Microphone sensitivity is Manual (1–20). Speak at your normal volume and raise it until the camera's level meter peaks around −12 dB."),
    S("wind_nr", 0xD0AA, "Wind noise reduction", "video", "enum", ON_OFF, MOVIE,
      "Cuts low rumble on the built-in mic. Leave off indoors; it also thins out your voice."),
    S("evr", 0xD314, "Electronic VR", "video", "enum", ON_OFF, MOVIE,
      "Digital stabilization for handheld shots (1080p/720p only; crops slightly). Off on a tripod."),
    S("lv_size", 0xD1AC, "Preview resolution", "video", "enum", LV_SIZE, BOTH,
      "Resolution of the preview sent to the PC (not the recording). XGA is sharper for judging focus."),
    # ---- setup ----------------------------------------------------------
    S("vf_af_mode", 0xD161, "Viewfinder focus mode (photos)", "setup", "enum", VF_AF_MODE, PHOTO,
      "Focus mode used when shooting photos through the viewfinder, not live view."),
    S("artist", 0xD072, "Artist", "setup", "text", None, BOTH, "Your name, written into every file's metadata."),
    S("copyright", 0xD073, "Copyright", "setup", "text", None, BOTH, "Copyright notice written into file metadata."),
    S("copyright_on", 0xD053, "Embed copyright info", "setup", "enum", ON_OFF, BOTH, "Whether the artist/copyright text is written into files."),
    S("comment", 0xD090, "Image comment", "setup", "text"),
    S("comment_on", 0xD091, "Attach image comment", "setup", "enum", ON_OFF),
    S("clock", 0x5011, "Camera clock", "setup", "text", None, BOTH, "The camera's date and time, used for file dates. Use 'Sync to PC' in the checklist if it's wrong."),
]

SECTIONS = [
    ("exposure", "Exposure"),
    ("image", "Image"),
    ("video", "Video & audio"),
    ("setup", "Setup"),
]

# Status properties polled regularly (read-only).
STATUS_CODES = {
    "battery": 0x5001,
    "remaining_shots": 0xD1F1,
    "meter": 0xD1B1,
    "lv_status": 0xD1A2,
    "lv_prohibit": 0xD1A4,
    "movie_prohibit": 0xD0A4,
    "focal_length": 0x5008,
    "focal_min": 0xD0E3,
    "focal_max": 0xD0E4,
    "ac_power": 0xD101,
    "af_lock": 0xD104,
    "ae_lock": 0xD105,
    "warning": 0xD102,
}

MOVIE_PROHIBIT_BITS = {
    0: "No memory card",
    1: "Card error",
    2: "Card not formatted",
    3: "Card full",
    9: "Camera is still writing to the card",
    10: "Already recording",
    11: "Card is write-protected",
    12: "Preview is zoomed in",
    13: "Live view is in photo mode",
    14: "The D7500 only starts recording from its own record button",
}

LV_PROHIBIT_BITS = {
    2: "Sequence error",
    4: "Shutter button is fully pressed",
    5: "Minimum aperture warning",
    8: "Battery exhausted",
    9: "TTL error",
    12: "An image is still waiting in camera memory",
    14: "Recording to card but no card (or it's protected)",
    15: "Camera is busy processing a shot",
    17: "Camera is too hot",
    18: "Card is write-protected",
    19: "Card error",
    20: "Card not formatted",
    21: "Bulb warning",
    22: "Mirror-up in progress",
    24: "Lens is retracting",
    31: "Exposure mode must be P/A/S/M",
}


def decode_bits(value: int, table: dict[int, str]) -> list[str]:
    reasons = [text for bit, text in table.items() if value & (1 << bit)]
    known = sum(1 << b for b in table)
    if value & ~known:
        reasons.append(f"Other reason (code 0x{value & ~known:08x})")
    return reasons


def catalog_json() -> dict:
    return {
        "sections": [{"key": k, "label": label} for k, label in SECTIONS],
        "settings": [s.to_json() for s in SETTINGS],
    }


# ---------------------------------------------------------------------------
# Built-in presets: a developer talking to camera, with a mic, dark background.
# Values are raw camera values keyed by catalog setting key. ISO is only a
# starting point — fine-tune it with the dial until your face looks right.
_TALKING_HEAD = {
    "lv_selector": 1,
    "mode": 1,  # M
    "frame_size": 5,  # 1920×1080 30p: full sensor width (4K crops 1.5× and disables ADL/e-VR)
    "movie_quality": 1,  # High
    "movie_shutter": 0x0001003C,  # 1/60: 180° rule at 30p, flicker-free on 60 Hz mains
    "movie_aperture": 350,  # f/3.5, widest on the 18–140 at 18 mm: most light, most background blur
    "movie_auto_iso": 0,
    "movie_ev": 0,  # no effect in M without Auto ISO; zero avoids confusion
    "movie_metering": 2,  # center-weighted: reads your face, not the dark background
    "movie_picture": 2,  # Neutral: natural skin, no grading needed
    "movie_adl": 0,  # Off: keeps the background dark
    "movie_nr": 2,  # Normal
    "movie_wb": 0x8012,  # Choose color temperature
    "evr": 0,  # tripod
    "wind_nr": 0,  # indoors
    "lv_af_mode": 0,  # AF-S: focus once on your eye, then it holds (no hunting mid-sentence)
    "lv_af_area": 2,  # Normal-area: click your eye in the preview
}

BUILTIN_PRESETS = [
    {
        "name": "Talking head · Day (window light)",
        "description": "Daylight from a window in front of you or to one side. ISO 400, 5500 K.",
        "values": {**_TALKING_HEAD, "movie_iso": 400, "movie_kelvin": 5500},
    },
    {
        "name": "Talking head · Night (LED video light)",
        "description": "A daylight-balanced LED panel/key light, room lights off behind you. ISO 800, 5600 K.",
        "values": {**_TALKING_HEAD, "movie_iso": 800, "movie_kelvin": 5600},
    },
    {
        "name": "Talking head · Night (warm lamps)",
        "description": "Ordinary warm household bulbs or a desk lamp as your light. ISO 1600, 3200 K.",
        "values": {**_TALKING_HEAD, "movie_iso": 1600, "movie_kelvin": 3200},
    },
]

_BY_KEY = {s.key: s for s in SETTINGS}


def builtin_presets_json() -> dict:
    """Presets in the same shape as user presets: {name: {movie, values{code: raw}, builtin, description}}."""
    out = {}
    for p in BUILTIN_PRESETS:
        out[p["name"]] = {
            "movie": True,
            "builtin": True,
            "description": p["description"],
            "values": {str(_BY_KEY[k].code): v for k, v in p["values"].items()},
        }
    return out
