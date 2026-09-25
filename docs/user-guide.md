# User guide

The same guide is built into the app (the **Guide** button in the top bar).

## Before every recording

1. **On the camera:** Lv switch on **movie**, a charged battery (live view drains it fast; the EP-5B + EH-5c mains adapter avoids this), and HDMI to the capture card.
2. **Apply a preset** that matches your light (Presets panel). It sets M mode, 1080p 30p, 1/60, f/3.5, white balance, Picture Control, focus mode and more.
3. **Sit in position**, then press **Focus on my eyes** and **Expose for my face** (Face check panel).
4. **Mixer:** set the *ProFX6v3 starting point*, press **Voice check** and talk as you would on camera for 15 seconds. Turn the knobs it names, then check again.
5. **Check the pre-flight panel.** Everything green (or understood) means you're good. Right before a long take, click the **⏱ LV** chip to reset the camera's live view timer.
6. **Record** in your capture software. (Recording to the camera's card? Setup → *I record on* → Camera card, then use the camera's ● button.)

## Face check

- **Expose for my face** adjusts ISO until your face reaches your target brightness, in a few damped steps. With a dark background the camera's own meter reads "under" even when your face is perfect, so the face check is what counts.
- **Remember this brightness:** once your face looks right to you, press it. That becomes the target, which depends on your skin tone and taste.
- **Focus on my eyes** autofocuses exactly on your eyes. The card warns if they get noticeably softer than right after that focus.
- **Framing:** the face overlay (**A**) draws a dashed line on the upper third. Your eyes should sit on it, with you centred.
- **Background:** for the dark-background look it should be at least 2 stops darker than your face.

## Voice & mic (Mackie ProFX6v3)

- The app listens to the mixer's USB feed, which is the same audio your recording software records.
- **Starting point:** mic in channel 1, LOW CUT in, EQ at 12 o'clock, COMP at about 10 o'clock, FX down, PAN centre, LEVEL and MAIN MIX at U. Raise GAIN until the Level Set LED just flickers on your loudest words.
- **Voice check** says which knob to turn and roughly how much:

| Knob | When it's suggested |
|---|---|
| GAIN | Level too low, too hot, or clipping |
| PAN | Voice louder on one side |
| LOW CUT | Rumble under your voice |
| COMP | Level varies a lot (up) or sounds squashed (down) |
| LOW (80 Hz) | Boomy (down) or thin (up) |
| MID (2.5 kHz) | Muffled (up) or harsh (down) |
| HI (12 kHz) | Dull (up) or hissy/sibilant (down) |

- **Targets for a podcast voice:** speech peaks −12 to −6 dBFS, loudness −22 to −16 LUFS, below −60 dBFS between words. Normalise to −14 LUFS for YouTube in the edit.
- Trust your ears too. Check on headphones.

## Session warnings

- **⏱ LV chip:** the camera turns live view off when its timer runs out (about 10 minutes by default), and the HDMI feed stops with it. Click the chip between takes to reset it. It's also worth setting a longer delay in the camera: Custom setting c3 → Power off delay → Live view.
- **Battery:** after a few minutes the chip shows the estimated minutes left.
- **Disk:** free space and minutes left in your recordings folder (Setup → Recordings folder, Recording bitrate).
- **Mic:** clipping or no signal shows in the mic meter (where REC used to be) and in the checklist.

## The screen

- **Top bar:** connection, exposure mode, Photo/Movie live view, frame size and rate, battery, card, Guide, shortcuts, fullscreen.
- **Preview:** click to focus (Shift+click moves the focus box without focusing). Top right shows the camera's exposure meter.
- **Under the preview:** the REC button (it reads *ON CAMERA* when the camera has to start the take itself), the exposure dials, the focus bar and overlay toggles. These are the only place these settings appear.
- **Right panel:** pre-flight check, presets, and tabs with all the other settings. Every ⓘ explains its setting.

## Exposure settings

| Setting | What it does |
|---|---|
| **Shutter speed** | How long each frame is exposed. For video use about 1/(2 × frame rate): **1/60 at 30p**, 1/50 at 25p. Faster looks choppy, slower looks blurry. Matching your mains frequency (1/60 on 60 Hz, 1/50 on 50 Hz) also stops lights from flickering. |
| **Aperture (f/)** | How wide the lens opens. A **smaller number means more light and a blurrier background** (f/3.5). A bigger number is darker, with more in focus (f/8). |
| **ISO** | Brightens the image electronically. Set it last, after shutter and aperture. Higher is brighter but grainier; the D7500 stays clean up to about 3200. |
| **EV (exposure compensation)** | EV means *exposure value*, counted in stops: +1 EV is twice as bright, −1 EV half as bright. It asks the camera to go brighter or darker than *its own automatic choice*, so it only matters when the camera decides part of the exposure (Auto ISO, or P/S/A modes). In M with Auto ISO off, which is how the presets set things up, it does nothing. Change ISO instead. |
| **Exposure mode** | **M** (manual) keeps everything fixed so brightness never changes mid-take. P/S/A let the camera adjust things. |
| **White balance & Kelvin** | Makes white look white. Pick **Kelvin** and match your light: warm bulbs ≈ 3200 K, LED video lights ≈ 5600 K, window daylight ≈ 5500–6500 K. Skin too orange → raise the number; too blue → lower it. Avoid Auto, because it drifts during a shot. |
| **Exposure meter** | The bar at the top right: how far your settings are from what the camera thinks is correct. With a dark background it will read under, because the background pulls it down. Trust your face and the zebras instead. |

## Focus

| Control | What it does |
|---|---|
| **AF-S** | Focuses once when you click the preview or press AF (**F**), then holds. Best for sitting and talking. |
| **AF-F** | Keeps refocusing continuously. It follows you if you move, but may visibly "breathe". |
| **MF** | Manual: only Near/Far (or `[` `]`, `{` `}`) move the focus. |
| **AF-area** | Normal-area is a small box you place by clicking (click your eye). Wide-area is a bigger box. Face-priority and Subject-tracking choose the point themselves. |
| **Zoom** | Magnifies the preview around the focus box: 50% → 100% (1:1) → 200% → fit. It doesn't affect the recording. |

## Overlays

| Overlay | Key | Use |
|---|---|---|
| Zebras | E | Magenta stripes on nearly-white areas. Keep them off your skin. |
| Focus peaking | P | Green outlines on the sharpest edges. Your eyes and eyelashes should light up. |
| Histogram | H | Brightness distribution. A red bar on the right means clipped highlights; blue on the left means crushed blacks, which is fine for a dark background. |
| Level | L | Virtual horizon from the camera's tilt sensor. It turns green when the camera is level. |
| Grid | G | Rule of thirds. Put your eyes near the top line. |
| Safe areas | S | Keeps text away from the frame edges. |

## Getting a dark background

- Light your face from the front or side. Turn off the lights behind you, and keep a few metres between you and the background if you can.
- Expose for your face (ISO dial and zebras). The background falls into shadow on its own.
- Keep **Active D-Lighting off** (the presets do this). Otherwise it brightens the background.
- A small practical light in the background (a lamp or LED strip) adds depth without lighting the wall.

## Presets

- The **Recommended** presets are built in: talking head, day, night with an LED light, and night with warm lamps.
- **Save current…** stores every current setting under a name. **Apply** restores it. The active preset is highlighted.
- After applying, the pre-flight check tells you if anything drifts from the preset (for example, if someone changed white balance on the camera), and offers **Re-apply**. ISO is left to you and isn't checked.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Camera not connected" | Turn the camera on and wake it (half-press the shutter). Use a USB **data** cable plugged straight into the PC. Close Entangle and gphoto2. |
| "Camera is busy (another app is using it)" | Another program, usually Entangle or a file manager window showing the camera, holds the USB device. Close it. |
| "Live view blocked: Battery exhausted" | Charge or swap the battery. |
| REC shows *ON CAMERA* | Normal on the D7500 when recording to the card: start the take with the camera's ● button. |
| Capture card shows black | Turn off *HDMI → Advanced → Live view on-screen display* if the picture has overlays; make sure live view is running (the app starts it); check the ⏱ timer hasn't expired. |
| Voice check says "Almost no signal" | Mic in channel 1/2, +48V for condenser mics, LEVEL and MAIN MIX up, and the right input selected in the Voice & mic panel. |
| Preview is black in Photo mode | Exposure preview is on and the scene is dark. Use the *Show brightened preview* button, or add light. |
| Active D-Lighting / e-VR can't be changed | Not available in 4K. Pick a 1080p or 720p frame size. |
| Live view mode keeps going back to Photo | The camera's physical Lv switch wins whenever live view restarts. Leave it on movie. |
