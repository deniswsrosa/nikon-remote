# Nikon D7500 over PTP: verified notes

Everything here was measured on a D7500 (firmware 1.10, AF-S DX 18–140 lens) connected over USB. Codes are PTP property codes. Where libgphoto2's tables disagree with the camera, the camera wins.

## Session and modes

- Vendor ID `04b0`, product `0440`. There are 238 properties: the device-info list plus Nikon's `GetVendorPropCodes` (`0x90CA`).
- **While live view runs**, even in normal camera mode, these become writable: `0x500E` exposure program (P/S/A/M, whatever the physical dial says), `0xD1A6` Lv selector (0 photo, 1 movie) and `0xD1A5` exposure preview.
- The Lv selector reverts to the **physical switch** whenever live view restarts.
- `ChangeCameraMode(1)` (`0x90C2`), PC-control mode, makes the above writable even without live view. It doesn't make recording possible.
- Writing **ApplicationMode `0xD1F0` is refused.** The camera answers *Access denied* about 5 s later, which breaks a short USB timeout and desynchronises the session. Never write it.

## Recording

- `StartMovieRecInCard` (`0x920A`) / `EndMovieRec` (`0x920B`) are advertised.
- MovRecProhibitCondition `0xD0A4` bits:
  - bit 13 = Lv selector on photo;
  - bit 14 = **not in application mode**;
  - bit 10 = already recording;
  - bits 0–3 cover the card.
- **ApplicationMode `0xD1F0`** must be 1 to clear bit 14. It's accepted in ~200 ms **only with live view off** (fresh session). While live view runs, or after `ChangeCameraMode(1)`, the write is refused ~5 s later or hangs the session. It resets to 0 when the session closes. libgphoto2's `movie` config sets it the same way before starting live view; see [gphoto2 issue #531](https://github.com/gphoto/gphoto2/issues/531).
- Tried and refused while ApplicationMode was 0: every combination of photo/movie Lv, PC-control mode on/off, and the selector set before or after live view.
- With the Lv selector on movie, `InitiateCaptureRecInMedia` (`0x9207`) takes a still photo, even with MovieReleaseButton `0xD197` = 1.
- The D7500 doesn't list MovieRecordStarted/Complete (`0xC10A`/`0xC108`) events. The app watches bit 10.

## Live view header (`GetLiveViewImg` 0x9203)

Big-endian. The JPEG starts at the first `FF D8 FF`.

| Offset | Size | Meaning |
|---|---|---|
| 8 / 10 | u16 | JPEG width / height (640×424 photo, 640×360 movie at VGA) |
| 12 / 14 | u16 | Coordinate space: 5568×3712 photo, 3840×2160 movie 4K (1:1 crop), 5568×3128 movie 1080p/720p |
| 16 / 18 | u16 | Displayed area width / height (shrinks when zoomed) |
| 20 / 22 | u16 | Displayed area centre |
| 24 / 26 | u16 | AF box width / height (Normal-area 450×378; 900×756 seen in Face-priority) |
| 28 / 30 | u16 | AF box centre |
| 46 | u16 | Seconds until live view auto-off (599 right after start with a 10 min c3 setting). Counts down; only a live view restart resets it (property writes, AF and focus drive don't) |
| 52 | u32 | Roll, 16.16 fixed-point degrees, 0–360 |
| 56 | u32 | Pitch, same format |
| 60 | u32 | Yaw (`0xFFFFFFFF`, not available) |
| 64 | u32 | Remaining clip time in ms (1 799 000 = 29:59) |

`ChangeAfArea` (`0x9205`) takes x, y in the same coordinate space. The camera must be in Normal-area or Wide-area AF; in Face-priority it picks its own point. Zoom centres on the AF box.

## Value tables

| Property | Values |
|---|---|
| `0xD1A3` LV zoom | 0 fit, 2 = 25%, 3 = 33%, 4 = 50%, 5 = 67%, 6 = 100% (1:1), 7 = 200%. **1 is rejected.** |
| `0xD061` LV focus mode | 0 AF-S, 2 AF-F, 4 MF. **3 is rejected.** |
| `0xD05D` LV AF area | 0 face-priority, 1 wide, 2 normal, 3 subject tracking |
| `0xD23B` movie Active D-Lighting | 0 Off, 1 Low, 2 Normal, 3 High, 4 Extra high, 5 Same as photo. Measured from shadow brightness in movie live view. **Refused at 4K.** |
| `0xD14E` photo Active D-Lighting | D850 table: 0 Auto, 1 Off, 2 Low, 3 Normal, 4 High, 5 Extra high (libgphoto2 uses the D90 table for this body, which is wrong) |
| `0xD0A0` movie frame size | 0–2 = 4K (verified by the header coordinate space), 3–9 = 1080p/720p. Frame rates follow the D850 table: 0 4K30, 1 4K25, 2 4K24, 3 1080p60, 4 50, 5 30, 6 25, 7 24, 8 720p60, 9 50. |
| `0xD1AC` preview size | 1 QVGA, 2 VGA, 3 XGA |
| `0xD1A8` / `0xD100` shutter | `(numerator << 16) \| denominator`, e.g. `0x0001003C` = 1/60. `0xFFFFFFFF` = Bulb. |
| `0x5007` / `0xD1A9` aperture | f-number × 100 |
| `0xD1AB` movie EV | EV × 1000 |
| `0xD1B1` exposure indicator | −60…60 |
| `0x500E` exposure program | 1 M, 2 P, 3 A, 4 S, `0x8010` AUTO, `0x8050` U1, `0x8051` U2 |
| `0x5011` date/time | `YYYYMMDDThhmmss`, writable |

## Manual focus

- `MfDrive` (`0x9204`): param 1 = 1 moves toward closest, 2 toward infinity; param 2 = steps.
- The 18–140 travels about **6000 steps** end to end.
- At an end stop, further moves in that direction return `0xA00E`.

## Autofocus

`AfDrive` (`0x90C1`), then poll `DeviceReady` (`0x90C8`). It returns OK, `0x2019` busy, or `0xA002` out of focus.

## HDMI

The D7500 exposes no HDMI properties over PTP: `0xD0CC` HDMIOutputDataDepth is absent from its property list. Output resolution, the on-screen display and the output range can only be set in the camera menu.
