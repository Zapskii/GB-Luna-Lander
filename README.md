# LUNA LANDEER

A lunar lander for the Game Boy (DMG), written in GBDK-2020 C with no game
engine. Same lineage as GB-Protector and GB-Draughts: procedural art from a
Python script, and hardware-independent physics in a `sim.h` that is tested on
the host before anything touches GBDK.

**Just want to play it? [PLAY.md](PLAY.md) is the player's guide** — the
controls, the landing rule, what the numbers on the screen mean, and the pads.
The ROM is a [release asset](https://github.com/Zapskii/GB-Luna-Landeer/releases):
download it and load it in an emulator, or flash it to a cartridge. Everything
below this line is the build and the internals.

**Current stage: Milestone 1 complete.** One mode plays end to end: a ship that
rotates, thrusts, burns fuel and falls through a wrap-around 160 px world, a
landing verdict that either puts it down on a pad or crashes it, live telemetry
over the ground, a title screen that picks the mode, and three sounds. `make`
builds the ROM, `make test` runs the physics' unit tests on the host, and
`make probe` drives the ROM in a headless emulator and asserts on what it did.
Milestone 2 — the taller world and the camera that follows the ship — is not
started.

## Modes

| Mode | The world | Status |
|---|---|---|
| **LANDER** | One 160 px screen, wrapping left to right. The whole world fits on the screen and there is no camera. | The mode that plays, and what the ROM boots into. |
| **DESCENT** | A world taller than the screen, with a camera following the ship down it. | Offered on the title and selectable — and **inert**: START starts LANDER whatever the title says. |

The two modes are meant to differ only in their level data and their camera,
and M1 is where that bet had to be made good on. Terrain is one array of surface
heights in **8 px tile units**, and the type reaches 255 of them — far more than
one screenful — so the descent's ~100-tile profile is new data rather than a
refactor of the physics, the tests and the checks. `terrain.h` and
`tools/mklevel.py` carry that argument in full.

## Controls

| Button | What it does |
|---|---|
| d-pad UP | thrust. **Hold** it to keep burning — this one reads the held button, not the edge |
| A | rotate one step anticlockwise |
| B | rotate one step clockwise |
| START | restart the life — mid-flight, after a landing, after a crash |
| SELECT | on the title screen, switch between **LANDER** and **DESCENT** |

A and B are edges: one press is one 22.5° step, and holding one down does not
spin the ship. There are 16 headings and the nose always points the way thrust
acceleration does, because the sprite frame and the thrust vector come out of
the same heading byte.

## The landing

A life ends the tick the ship's underside reaches the surface row under its
centre, and `classify_landing()` in `sim.h` decides which ending it was. The
verdicts are checked in a fixed order and each failure has a named threshold:

| Verdict | The rule | The threshold |
|---|---|---|
| **CRASH** | the column under the ship is not a landing pad | no pad — checked first, because it outranks everything else |
| **TOO_FAST** | the ship is coming down too hard | descent > 0.5 px/frame |
| **DRIFTING** | it is moving sideways when it touches down | sideways speed > 0.25 px/frame |
| **TILTED** | the nose is too far off vertical | more than one 22.5° step |
| **SAFE** | inside all of the above | — |

Only a pad is safe ground; a perfectly gentle touchdown anywhere else is still a
CRASH. Each threshold is compared with a single `>` at the exact edge,
the same style Protector's `human_fall_step` uses, so "just barely safe" and
"just barely fatal" are both pinned — the host tests straddle every one of them
from both sides.

Pad multipliers come out of `terrain.h`, not out of the renderer:

| Pad | Columns | Score |
|---|---|---|
| LOW | 4–7 | ×1 |
| HIGH | 13–14 | ×2 |

The ship spawns directly above the ×2 pad, at rest, so a drop with nobody at the
controls is a crash and the whole of the skill is arriving slowly.

## Build

    make          # luna.gb — the ROM
    make test     # host unit tests for sim.h, plain gcc, no emulator
    make probe    # headless PyBoy checks against the built ROM
    make fps      # the tick-rate assertion on its own (one frame per emulated frame)
    make shot     # a screenshot, to /tmp/luna.png
    make gfx      # regenerate gfx.h from mkgfx.py (committed)
    make level    # regenerate terrain.h from tools/mklevel.py (committed)
    make tab      # regenerate tables.h from tools/mktab.py (committed)
    make usage    # ROM/RAM headroom
    make sym      # a -debug build: luna.map carries every symbol, not just globals
    make image    # build the gbdk-dev Docker image (only needed once)
    make clean

The toolchain is GBDK-2020 4.5.0. `make` uses a local `GBDK_HOME` when one is
set and otherwise runs the toolchain out of a Docker image (`make image` builds
it); the Dockerfile picks the right GBDK tarball for the host's architecture.

`make probe` builds a `-debug` ROM into `luna.gb`, because the linker map has to
list the statics the checks read. That ROM is then newer than the sources, so a
plain `make` after probing has nothing to do — run `make clean` and then `make`
to get the release binary back.

`make probe` and `make fps` need PyBoy and a `-debug` build; neither is needed
to *play* the game, and `make` on its own builds the ROM with no Python at all.

## Layout

| File | What it is |
|---|---|
| `main.c` | Everything that touches hardware: boot, the tick loop, input, rendering, the HUD and the sound |
| `sim.h` | THE RULES — pure C, `<stdint.h>` only, never `gb/gb.h`. Sub-pixel stepping, gravity, thrust, fuel, the wrap and the landing verdict |
| `tools/mklevel.py` | Generates `terrain.h`: the height profile and the pad table, with self-checks |
| `terrain.h` | Generated, committed — a plain `make` needs no Python |
| `tools/mktab.py` | Generates `tables.h`: the 16 thrust unit vectors |
| `tables.h` | Generated, committed |
| `mkgfx.py` | Generates `gfx.h`: the font, the terrain tiles and the 16 ship frames |
| `gfx.h` | Generated, committed. Included by `main.c` only |
| `tests/test_sim.c` | Host tests for the physics and the landing rule |
| `tools/probe.py` | Headless emulator checks: the wiring between `sim.h` and `main.c` |
| `tools/shot.py` | Screenshot helper |
| `Dockerfile` | The GBDK toolchain image `make image` builds |

## Testing strategy

The project is split so that each half can be checked by the tool that suits
it, and neither half is trusted to check itself.

`tests/test_sim.c` compiles `sim.h` with plain `gcc -std=c99` and runs the
physics on the host — no emulator, no ROM. It pins what the maths is: the exact
8.8 trajectory gravity produces from rest, the fraction bytes carrying between
ticks (a fraction byte that lived in a local instead of the state would quantise
the motion to whole pixels and look merely "chunky"), thrust as a direction out
of `tables.h`, the fuel economy, the heading wrap, and every landing threshold
from both sides. An early case asserts the widths the rest of the file is
written in, because GBDK's `int` is 16-bit and a type that silently widened here
would poison everything below it.

`tools/probe.py` covers the other half: whether `main.c` asks the rules the
right question at the right moment, and whether the screen agrees with the
state. It boots the ROM in a headless emulator, plays it with button presses,
and asserts on the BG tilemap and on `main.c`'s own variables, which it reads
out of the linker map by name rather than by hardcoded address. That is where
the wiring lives that the host cannot see: that the tiles go up before the
display does, that the sprite's position is the state's position, that the HUD
digits are the ship's own fuel and altitude, and that the tick loop still runs
one iteration per emulated frame with the HUD blitted every tick.

`make probe` exits 0 when every check passes, 1 when a check fails, and 2 when
the harness itself broke — so a stuck ROM is never mistaken for a passing one.

## Not implemented yet (by design)

- **The DESCENT mode.** It is on the title screen and the title says which one
  is selected, and START ignores it: there is no camera, no scrolling and no
  taller level yet. The mode line is honest about being a choice, not about
  being a second game.
- **Levels, and any score that outlives a life.** One landing scores its pad's
  multiplier and START is the only thing that follows it.
- **A saved high score.** It needs a battery-backed cart, which is a
  hardware/BOM decision rather than just a code change.
- **Difficulty or a wind model.** Gravity and thrust are two constants; the
  weather is not a feature yet.
- **A Super Game Boy border.** The path and its two hazards are known
  (`-Wm-ys`, and a border of exactly 128 tiles transfers nothing) but nothing
  is drawn.
- **Music.** The three event sounds are hand-written register writes; there is
  no sound driver.

## Release

The ROM is never committed: `*.gb`, the linker map and the object files are all
gitignored, and the built `luna.gb` is attached to a
[GitHub release](https://github.com/Zapskii/GB-Luna-Landeer/releases) instead.
To reproduce a release binary, run `make probe` and then `make clean` and `make`
(the probe leaves a `-debug` ROM in `luna.gb`, and it is newer than the sources),
and record the md5 before you upload it.
