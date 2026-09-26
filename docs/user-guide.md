# User guide

The same guide is built into the app (the **Guide** button in the top bar).

## Before every recording

1. **On the camera:** Lv switch on **movie**, a charged battery (live view drains it fast; the EP-5B + EH-5c mains adapter avoids this), and HDMI to the capture card.
2. **Apply a preset** that matches your light (Presets panel). It sets M mode, 1080p 30p, 1/60, f/3.5, white balance, Picture Control, focus mode and more.
3. **Sit in position**, then press **Focus on my eyes** and **Expose for my face** (Face check panel).
4. **Mixer:** Audio tab → follow the 4 steps (start position, GAIN, analyse, check).
5. **Check the pre-flight panel.** Everything green (or understood) means you're good. Right before a long take, click the **⏱ LV** chip to reset the camera's live view timer.
6. **Record.** HDMI capture: start in your capture software. Camera card: Setup → *I record on* → Camera card, then press **REC** (or **R**) in the app.

## Face check

- **Expose for my face** adjusts ISO until your face reaches your target brightness, in a few damped steps. With a dark background the camera's own meter reads "under" even when your face is perfect, so the face check is what counts.
- **Remember this brightness:** once your face looks right to you, press it. That becomes the target, which depends on your skin tone and taste.
- **Focus on my eyes** autofocuses exactly on your eyes. The card warns if they get noticeably softer than right after that focus.
- **Framing:** the face overlay (**A**) draws a dashed line on the upper third. Your eyes should sit on it, with you centred.
- **Background:** for the dark-background look it should be at least 2 stops darker than your face.

## Audio (Mackie ProFX6v3)

The app listens to the mixer's USB feed, the same audio your recording software records. The **bar at the bottom** always shows your level (the green zone is the target for speech peaks), loudness, noise floor and a live GAIN hint.

Your Mic/Line 1 strip, top to bottom, per Mackie's manual:

| Control | Range / what it does |
|---|---|
| GAIN + level-set LED | Mic gain 0 → +60 dB. If the LED stays lit, it's too hot. |
| LOW CUT (switch) | Cuts below 100 Hz, 18 dB/octave |
| HI (knob) | ±15 dB shelf above 12 kHz, flat at the centre click |
| LOW (knob) | ±15 dB shelf below 80 Hz, flat at the centre click |
| FX (switch) | In = reverb/effects |
| STEREO PAN (switch) | In = channel 1 plays only on the **left** |
| LEVEL (knob) | Off … U … +10 dB. Changes the recording. |

There's no compressor and no mid EQ. MAIN MIX doesn't change the recording, because the USB feed is taken before it.

**Mic setup wizard.** Click the Mic bar at the bottom of the screen, or go to Audio tab → Open the mic setup wizard. It's full-screen, with 8 steps:

1. **Welcome:** sit where you'll record, headphones on, quiet room.
2. **Mic:** dynamic or condenser. This sets the distance (5–10 cm vs 15–20 cm, slightly off-axis) and the 48V switch.
3. **Start position:** tick each control on the Mic/Line 1 strip as you set it (GAIN ~9 o'clock, LOW CUT in, HI/LOW at 12, FX out, STEREO PAN out, LEVEL on U).
4. **GAIN:** read the passage and turn GAIN the way the panel on the right says. The needle averages 10 s of speech and has a dead band, so it won't flip-flop. Next unlocks after 5 s in the green zone.
5. **Read the passage:** the Rainbow Passage, the standard phonetically balanced text from speech science. The same words every time make readings comparable.
6. **Adjust:** gauges show your voice (orange dot) against the range real voices fall in (green). Then one change at a time: a big drawing of the control with the current position (grey) and the target (orange), what to do, and why.
7. **Check:** read again. Each change is compared with the first reading (hollow dot = before), and you're told whether it moved your voice as expected. If it barely moved, it asks whether you turned the right knob.
8. **Recording software:** exact OBS filter settings (the ProFX6v3 has no compressor), simulated on your voice to land at −16 LUFS.

Why the LOW knob stays at 12 o'clock: on the ProFX6v3 it's an 80 Hz shelf. With LOW CUT in (which a voice always wants), turning it 3 dB changes a voice's low end by only about 0.2 dB. Boominess comes from being close to the mic (proximity effect), so the wizard tells you to move back or closer instead.

**Match a voice I like…** uploads a clip (MP3/WAV/M4A/video) of a podcast voice you like. Its tone becomes the target instead of the built-in one.

## Session warnings

- **⏱ LV chip:** the camera turns live view off when its timer runs out (about 10 minutes by default), and the HDMI feed stops with it. Click the chip between takes to reset it. It's also worth setting a longer delay in the camera: Custom setting c3 → Power off delay → Live view.
- **Battery:** after a few minutes the chip shows the estimated minutes left.
- **Disk:** free space and minutes left in your recordings folder (Setup → Recordings folder, Recording bitrate).
- **Mic:** clipping or no signal shows in the mic meter (where REC used to be) and in the checklist.

## The screen

- **Top bar:** connection, exposure mode, Photo/Movie live view, frame size and rate, battery, card, Guide, shortcuts, fullscreen.
- **Preview:** click to focus (Shift+click moves the focus box without focusing). Top right shows the camera's exposure meter.
- **Under the preview:** the REC button, the exposure dials, the focus bar and overlay toggles. These are the only place these settings appear.
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
| Capture card shows black | Turn off *HDMI → Advanced → Live view on-screen display* if the picture has overlays; make sure live view is running (the app starts it); check the ⏱ timer hasn't expired. |
| Audio analysis says "Almost no signal" | Mic in Mic/Line 1, 48V on for condenser mics, channel LEVEL on U, and the right input selected in the Audio tab. |
| Preview is black in Photo mode | Exposure preview is on and the scene is dark. Use the *Show brightened preview* button, or add light. |
| Active D-Lighting / e-VR can't be changed | Not available in 4K. Pick a 1080p or 720p frame size. |
| Live view mode keeps going back to Photo | The camera's physical Lv switch wins whenever live view restarts. Leave it on movie. |
