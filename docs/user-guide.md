# User guide

The same guide is built into the app (the **Guide** button in the top bar).

## Before every recording

1. **On the camera:** Lv switch on **movie**, a charged battery (live view drains it fast; the EP-5B + EH-5c mains adapter avoids this), and a card with space.
2. **Apply a preset** that matches your light (Presets panel). It sets M mode, 1080p 30p, 1/60, f/3.5, white balance, Picture Control, focus mode and more.
3. **Click your eye** in the preview. In AF-S the focus locks there and stays put. Press **Z** to zoom to 100% and check it's sharp, then **Z** again to go back.
4. **Set ISO** with the dial until your face looks right. Turn on zebras (**E**): stripes on your forehead or cheeks mean it's too bright.
5. **Check the pre-flight panel.** Everything green (or understood) means you're good.
6. **Press the red ● button on the camera** to start and stop. The D7500 doesn't allow a computer to start recording; the app follows along and shows the timer.

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
| REC shows *ON CAMERA* | Normal on the D7500: start the take with the camera's ● button. |
| Preview is black in Photo mode | Exposure preview is on and the scene is dark. Use the *Show brightened preview* button, or add light. |
| Active D-Lighting / e-VR can't be changed | Not available in 4K. Pick a 1080p or 720p frame size. |
| Live view mode keeps going back to Photo | The camera's physical Lv switch wins whenever live view restarts. Leave it on movie. |
