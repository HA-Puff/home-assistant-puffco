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

## The base ring (NOT yet working)

The base ring is the firmware's **mood-light** system, separate from the logo.
It is driven by NVM color/offset arrays + a compiled mood, and on AW firmware
it only **renders** from a **V3 `CompiledMoodLight`** blob.

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

## Why the base ring didn't light (experiments)

| Attempt | Result |
|---------|--------|
| Multi-color write to `/p/app/ltrn/colr` | Rejected (`Lorax error 22`, size) |
| Lamp mode: color + BLANK scratchpad + start + time | Logo only; `aclr` → red |
| Direct write `/p/app/led/aclr` | `Lorax error 2` (read-only) |
| Write preview `/p/app/led/pclr`, `ca/0` | Accepted, no visible base change |
| Table-mode lantern → existing `ca/5` rainbow | **No base activity** |
| Full V2 mood: `ca/5` red + table color + LANTERN_CUSTOM scratchpad | **No render**; `aclr` stayed idle-blue |

**Conclusion:** AW accepts the V2 array/table writes but only **renders** the
base ring from a **V3 `CompiledMoodLight`** blob written to `${target}ColorApi3`
(same path `/p/app/ltrn/colr`, dataType `raw`). The official/web app runs Puffco's
`MoodLightCompiler` (projectors → lamps → binary program) to produce it.

## To finish the base ring later (two options)
1. **Capture & replay**: sniff the bytes the web/mobile app writes to
   `/p/app/ltrn/colr` for a known pattern (e.g. solid red, Lava Lamp), then
   replay / parameterize them. Fastest reliable path.
2. **Port the compiler**: reproduce `MoodLightCompiler` + `CompiledMoodLight.serialize`
   for the peach projector defs (large effort; see community reverse-engineering
   writeups and the Puffco mobile app Lorax stack).
