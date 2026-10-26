# Puffco Peak Pro LED / Lantern Reverse-Engineering Notes

Findings from validating LED control on recent Lorax firmware (peach-series Peak Pro).
Captured while building the BLE library so the base-ring ("mood light") feature can be
finished later.

## What works today

- **Logo light**: single solid color via the lantern color characteristic.
  - Path: `/p/app/ltrn/colr` (`lanternColorApi2`, `rgbtApi2` = **8 bytes**)
  - Layout: `[R, G, B, T, lumaAnim(uint32 LE)]`, e.g. red steady = `ff 00 00 00 01 00 00 00`
  - On/off: `/p/app/ltrn/cmd` (`lanternStart`, uint8 0/1)
  - Duration: `/p/app/ltrn/time` (`lanternTime`, float32). App uses `LANTERN_TIME_SEC = 7200`.
  - Scratchpad (for solid color): `/p/app/ltrn/scpd`, BLANK = 128 bytes of `0xFF`.

## The base ring (working: exclusive patterns)

The base ring is the firmware's **mood-light** system, separate from the logo.
How a mood is written depends on the unit's LED API, not the firmware letter.

### LED API 2 vs 3
The app picks the LED API at connect time (`getLedApiVersion`):
- apiVersion < `T` → led-api-1; < `AF` → led-api-2.
- Otherwise it reads the heat-cycle 0 preheat color. If that file exists → **led-api-2**,
  if it is `ENOENT` → **led-api-3**.

Our Peak Pro (firmware AW) is **led-api-2**. On led-api-3 the app writes even solid
colors as compiled blobs, so the fact that 8-byte colors work is a quick tell.

**led-api-2 mood write (`UnitLedApiV2.writeMoodLight`), what the integration does:**
1. Compile the mood and take `lamp.param` (`color`, `offset`, `bright`, `speed`, `anim`,
   `plNum`, `plDenom`, `colorLen`).
2. Write `/u/app/led/ca/{slot}`: 32 × `[R,G,B,0]` (128 B). Write-short, truncate flag 4.
3. Write `/u/app/led/oa/{slot}`: `offset` as uint32 LE (80 B).
4. Write the 8-byte **table** color to `/p/app/ltrn/colr`.
5. The lantern slot alternates between 5 and 6 (whichever the current table color does not
   point at), so the running pattern is never overwritten.

Heat profiles work the same way: profile N (0-3) uses arrays `ca/{1+N}` / `oa/{1+N}` and the
table color goes to `/u/app/hc/{N}/colr`. That file needs a short write (truncate flag 4),
like the app's `writeRaw`. The old opcode-34 write with handle 0 returned `EBADF 9`.

**led-api-3** (`UnitLedApiV3`) writes the serialized `CompiledMoodLight` (CBOR, lamp
`pikaled2`) straight to `/p/app/ltrn/colr` as `raw`. On a led-api-2 unit every form of
that write is refused: short write `EINVAL 22`, truncate `ENOTSUP 134`, file write via
open/write `EINVAL 22` at any chunk size.

The exclusive presets in `lantern_presets.py` are those compiled blobs (peach / AW).
`lantern_effects.mood_from_blob` decodes the CBOR into the led-api-2 arrays at import.

### Relevant paths
| Path | Meaning |
|------|---------|
| `/p/app/led/aclr` | Active (live) LED color output — **read-only** (`rgbtApi2`) |
| `/p/app/led/pclr` | Preview color (writable, no visible effect outside preview UI) |
| `/u/app/led/ca/0..7` | userColorArray — 32 × `[R,G,B,0]` (128B). Lantern uses index **5** |
| `/u/app/led/oa/0..7` | userOffsetArray (animation offsets, ~80B) |
| `/u/app/led/aa/0..5` | anim arrays (not readable on this unit) |
| `/p/app/led/dia,diao,dif,difo` | dabbing breathing-animation params (float32) |

### NVM array indices (`NVM_ARRAY_INDICES`)
`HEAT_PROFILE_TEMP=0, HEAT_PROFILE_0..3 = 1..4, DEFAULT_LANTERN=5, ALTERNATIVE_LANTERN=6`.
Table color index byte = `(8 + nvmIndex)` in both nibbles → index 5 = `0xDD`.

### Lantern color in "table" mode (`RgbtColor.fromTable`)
8 bytes: `[luma, speed, lumaAnim, 0x01(table marker), pllNum, pllDenom, (offIdx<<4|colIdx), colorLen]`

### MoodType enum
`NO_ANIMATION=0, DISCO=1, FADE=2, SPIN=3, SPLIT_GRADIENT=4, VERTICAL_SLIDESHOW=5,
TORNADO=6, BREATHING=7, CIRCLING_SLOW=8, LAVA_LAMP=9, CONFETTI=10`

Lava Lamp default colors: `#4D0013,#FF7000,#FFD000` + tempo/density sliders.

### LANTERN_CUSTOM scratchpad (version 16) — 128B, zero-filled
`version(1) + moodUlid(16) + moodName(32) + moodDateModified(u32) + moodType(1)
+ tempoFrac(float) + userColors(18 = 6×RGB) + originalMoodUlid(16)`

## Early experiments (before the led-api-2 path worked)

These ran before the offset array and app-compiled params were used. The table
approach itself is correct; these attempts were missing pieces.

| Attempt | Result |
|---------|--------|
| Multi-color write to `/p/app/ltrn/colr` | Rejected (`Lorax error 22`, size) |
| Lamp mode: color + BLANK scratchpad + start + time | Logo only; `aclr` → red |
| Direct write `/p/app/led/aclr` | `Lorax error 2` (read-only) |
| Write preview `/p/app/led/pclr`, `ca/0` | Accepted, no visible base change |
| Table-mode lantern → existing `ca/5` rainbow | **No base activity** |
| Full V2 mood: `ca/5` red + table color + LANTERN_CUSTOM scratchpad | **No render**; `aclr` stayed idle-blue |

Exclusive moods are a cloud ULID catalog (`MoodLightCategory.Exclusive`,
`GET /api/v1/mood-lights?category=exclusive`). Their definitions were compiled with the
web app's own `MoodLightCompiler` (app 3.13.47) for series `peach`, revision `AW`, and
stored as `lantern_presets.py`.

## Still open
- **Custom moods** (Lava Lamp, Confetti, user colors) need the compiler. Porting
  `MoodLightCompiler` for the peach projectors is a large job; precompiling a fixed set the
  same way as the exclusives is the cheap path.
- **led-api-3 units**: the raw blob write is untested on real hardware. Those units would
  need the app's write-short-or-file-write path for `lanternColorApi3`.
