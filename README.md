# LUNA LANDER

A lunar lander for the Game Boy (DMG), written in GBDK-2020 C with no game
engine. Same lineage as GB-Protector and GB-Draughts: procedural art from a
Python script, and hardware-independent physics in a `sim.h` that is tested on
the host before anything touches GBDK.

**Just want to play it? [PLAY.md](PLAY.md) is the player's guide** — the
controls, the landing rule, what the numbers on the screen mean, and the pads.
[luna-lander-field-guide.html](luna-lander-field-guide.html) is the same guide
as a single self-contained page, plus a drawn chart of the safe landing envelope
and a review of the game; open it in a browser.
The ROM is a [release asset](https://github.com/Zapskii/GB-Luna-Lander/releases):
download it and load it in an emulator, or flash it to a cartridge. Everything
below this line is the build and the internals.

**Current stage: Milestone 3 complete.** Two modes play end to end — LANDER's
fixed 160 px worlds and DESCENT's 808 px ones — **twelve fixed levels a mode**,
each a hand-designed layout expanded from a recipe at build time, walked by
landing and retried by crashing. Clear the twelfth and the chain replays from
level 1 on a lap with a smaller tank; the ramp lives in the fuel, never in the
layouts or the physics. Over that: one ship that leans, thrusts, burns fuel,
wraps at the world's edges, and comes to rest on a pad or crashes — a landing
verdict with a named reason and a score, a full-screen page for each ending, a
completion page, live telemetry over the ground in a status bar that the
scrolling does not touch, a burst where the ship died, three sounds, and a Super
Game Boy border.
`make` builds the ROM, `make test` runs the physics' unit tests on the host, and
`make probe` drives the ROM in a headless emulator and asserts on what it did.

## Modes

| Mode | The world | Levels | Status |
|---|---|---|---|
| **LANDER** | One 160 px screen, wrapping left to right. The whole world fits on the screen, so the camera is pinned at 0 and the view is fixed. | 12, each under 18 tiles deep so its pad is never under the status bar | Plays. What the ROM boots into. |
| **DESCENT** | 808 px of world in the same 160 px of width, with a camera following the ship down it and the map streamed a row at a time around it. | 12, each deeper than a single BG map can hold | Plays. SELECT it on the title and START opens it. |

Both are the same game over two profiles, and P12's boot default is a single
`pick` byte: the title's mode line, the profile the renderer and the collision
read, and the world the camera clamps against are one answer from the first tick.

**Each mode is its own chain of twelve levels.** A landing advances you one
level; a crash puts you back on the one you were on; SELECT to the title does
not cost your place, and the title names the level it will resume. Nothing about
the ship changes between levels — gravity, thrust and the landing thresholds are
the same constants on all twenty-four — so what a level is, is a layout.

## The levels

A level is **a recipe, expanded at build time**: a shape, an amplitude, a base
depth, a pad span or two and a spawn column, which `tools/mklevel.py` turns into
a 20-byte height profile. The ROM carries only the expanded bytes — there is no
recipe in the cart and no runtime expansion, because `ship_step()` reads
`terrain[col]` every tick. Five triangle-wave shapes, each **zero at both seam
columns by construction**, so no choice of depth or amplitude can make the
world's wrap visible.

The generator **rejects a bad recipe rather than drawing it**: a spawn not over
a pad, a spawn level with its own pad, a pad shoulder steeper than 4 tiles, a
profile that breaks its chain's size rule — all of those are `make level`
failures. That is what makes the set hand-tunable, and it is why there is no
PRNG anywhere near the layouts: a seed gives determinism but nothing to
reject against, and a level that cannot be validated is a level that ships
unwinnable.

Level 1 of each chain is **byte-identical to the single world the game used to
have**, which is what kept the host tests and the existing probe checks honest
through the change.

Twelve a chain is an authoring budget rather than a space one: the tables cost
about 32 bytes a level, and the ROM has room for hundreds. The constraints are
that every level has to be hand-tuned against those assertions, and that the
probe has to be able to fly one.

The sky is one line in both modes. `row_blit()` writes the stars out of
`terrain.h`'s `star_cells[]`, indexed by **world** row — so LANDER's pinned
camera leaves them standing still while the ship crosses them, DESCENT's scrolls
them with the terrain, and a row the ring re-blits after wrapping gets the same
stars back instead of a reshuffled sky. They are a motion reference: at the top
of a fall the ground is off the screen and the ship is the only other thing
moving, so a steady few pixels a frame reads as hovering. The density is not a
taste call — the free-fall tick in `probe.p13_descent` has one frame of
tolerance and `tools/mklevel.py` carries the measurement that spends it.

The two modes are meant to differ only in their level data and their camera,
and M1 is where that bet had to be made good on. Terrain is one array of surface
heights in **8 px tile units**, and the type reaches 255 of them — far more than
one screenful — so the descent's ~100-tile profile is new data rather than a
refactor of the physics, the tests and the checks. `terrain.h` and
`tools/mklevel.py` carry that argument in full.

## Controls

| Button | What it does |
|---|---|
| d-pad LEFT | lean and push the ship left. **Hold** to keep pushing |
| d-pad RIGHT | lean and push the ship right. **Hold** to keep pushing |
| A or B | thrust along the nose. **Hold** one to keep burning — this is the held control, not the edge |
| START | restart the life mid-flight, **advance to the next level** after a landing, retry the same level after a crash, and start a new lap off the completion page |
| SELECT | back to the title — in flight, after a landing, after a crash; on the title itself, switch between **LANDER** and **DESCENT**. Your place is kept either way |

LEFT and RIGHT are held levels, like the engine: a direction down leans the nose
into a fixed angle and adds a sideways acceleration every tick, and letting go
stands the nose up again on that same tick and hands the drift to friction,
which takes it back off at a constant rate and clamps it to zero rather than
running through it. So a correction is a press and a wait, not a press and a
counter-press, and sideways thrust spends fuel at the engine's own rate. Thrust
is a held level too, on both face buttons because the DMG has no shoulder pair
to put it on. The nose only ever sits at three angles — upright, or leaned into
whichever direction is held — and the sprite frame and the thrust vector come
out of the same heading byte, so the lean is not decoration: a landing mid-strafe
is a landing with the nose off vertical, which is a crash.

## The landing

A life ends the tick the ship's underside reaches the surface row under its
centre, and `classify_landing()` in `sim.h` decides which ending it was. The
verdicts are checked in a fixed order and each failure has a named threshold:

| Verdict | The rule | The threshold |
|---|---|---|
| **CRASH** | the column under the ship is not a landing pad | no pad — checked first, because it outranks everything else |
| **TOO_FAST** | the ship is coming down too hard | descent > 0.5 px/frame |
| **DRIFTING** | it is moving sideways when it touches down | sideways speed > 0.25 px/frame |
| **TILTED** | the nose is too far off vertical | more than one 22.5° step — and the lean is two, so landing mid-strafe is a crash |
| **SAFE** | inside all of the above | — |

Only a pad is safe ground; a perfectly gentle touchdown anywhere else is still a
CRASH. Each threshold is compared with a single `>` at the exact edge,
the same style Protector's `human_fall_step` uses, so "just barely safe" and
"just barely fatal" are both pinned — the host tests straddle every one of them
from both sides.

A crash is drawn and not merely reported. The ship's own sprite slot plus the
three beside it — the only four the field uses — become a 16x16, four-frame
burst centred on the cell the ship died in, and go dark when it has run: the
wreck is not left standing, because the thing that landed is gone. The frame
comes off the same tick clock the physics runs on rather than off a drawn frame,
so a frame that overruns its budget cannot animate the burst faster than the
thing it is reporting on.

## The endings

The field is not where a life is reported. Each ending gets a full-screen page,
built into the same shadow buffer the title is and blitted **once** — the same
idiom, so an ending costs one map write paid on a single tick and the tick loop
carries none of it while it is up:

| Page | What it says | When it comes up |
|---|---|---|
| **LANDED** | the pad's multiplier, and the fuel left in the tank | the tick the ship comes to rest |
| **CRASHED** | the verdict `classify_landing()` returned, named — TOO FAST, DRIFTING, TILTED, NO PAD | the tick after the crash burst finishes |
| **MISSION COMPLETE** | the lap just finished, and the tank the next one starts on | in place of LANDED, on the last level of a chain |

The asymmetry is the burst's and not a preference. A landing is a ship at rest
with nothing left to watch, so its page is immediate; an explosion *is* the
death, and a page drawn over it would delete the one thing that says the ship was
destroyed rather than merely stopped. Both pages read `ship.verdict` and
`ship.mult` — the rule's own answers — so a page can never disagree with the rule
about why a life ended.

The status bar is cleared with the world. It is the WINDOW layer and covers the
screen's bottom two rows whatever the background holds, and its readings are
about a flight that has finished: ALT is 0 on both pages, the tank is whatever
was left, and the verdict row would be repeating the page's own heading.

**START is where the progression rule lives, and it reads `ship.state` rather
than which page was drawn** — so the rule and the page cannot disagree about
what just happened. Off LANDED it advances to the next level; off CRASHED it
retries the same one and does **not** rebuild the field, because a retry is the
same world and `terrain` and `world_h` still describe it; off MISSION COMPLETE
it starts a new lap with a tank shorter by `FUEL_LAP_STEP`, floored at
`FUEL_FLOOR`, over the same twelve designs. Only the advance rebuilds the field,
because it is the only one that changes the world. SELECT goes back to the
title from any of them, and the title keeps your place.

The crash page is also the reason `build_hud()`'s second row has no LANDED case
any more — that row would be written and covered on the same tick — and why
probe.p13 stops sampling the camera on the tick a descent ends: that tick's
screen is no longer one the camera draws.

**Pad multipliers and pad columns are level data**, out of `terrain.h` and not
out of the renderer: every level declares one or two spans and the row each is
carved flat to, and `mklevel.py` rejects a level whose pads overlap or whose
shoulder is a cliff. L1 of each chain is the world the game used to have:

| Pad | Columns | Score |
|---|---|---|
| LOW | 4–7 | ×1 |
| HIGH | 13–14 | ×2 |

**A pad is drawn as a pad.** `row_blit()` picks the surface tile with
`pad_mult(col)` — `T_PAD_TOP` on a pad column, `T_TERRAIN_TOP` everywhere else —
so the places a life can end well are the only lit things on the ground rather
than stretches that merely happen to be flat. The question is asked only on the
surface row, which is what keeps it off the per-cell path `p13`'s frame budget
is measured on.

Every level spawns the ship at rest, directly above its **smaller, ×2 pad** —
that is one of the generator's assertions, not a convention — so a drop with
nobody at the controls is a crash and the whole of the skill is arriving slowly.

## The Super Game Boy border

On a Super Game Boy the game is framed by a scene: a rocket either side of the
screen standing on the lunar surface, the two mode names along the bottom, and
a porthole rim around the window — the screen is the view out of the ship. The
border is a 256x224 image with the 160x144 game window punched out of it, and
it is **drawn rather than painted**: `tools/mkborder.py` generates
`art/border_sgb.png` the way `mkgfx.py` generates the tiles — procedurally, on
the 8-pixel grid, lettered in the game's own font, and capped at 16 colours
because that is what one SGB border palette holds. `make border` then turns the
PNG into `border_data.c/.h` with png2asset, and `main.c` hands the three blobs
(tiles, tilemap, palette) to `set_sgb_border()` once at boot, after
`DISPLAY_ON` and behind four `vsync()`s — a PAL SNES needs that delay before it
will take the packets, and the transfer trashes VRAM, so the game's own tiles
and its `bg` shadow buffer are rebuilt and re-blitted immediately after.

Three things about it are traps, and each is commented where it bites:

- **`-Wm-ys`** puts the SGB flag in the ROM header. Without it the SGB silently
  discards the border packets and the border never appears — no error, and
  identical behaviour on a DMG, so it is invisible everywhere except on the
  real thing.
- **A border of exactly 128 tiles transfers nothing.** `sgb_border.c` sends a
  single CHR_TRN block with the tile count shifted left for 4bpp, so 128 comes
  back as 256 in a `uint8_t` and the payload goes out empty. Over 128 is fine
  (it goes as two blocks) and 256 is the SGB's ceiling. `mkborder.py` asserts
  the tile count at generation time and `probe.p14_sgb_border` re-derives it
  from the blob the linker actually placed.
- **The ~5 KB of border data lives in bank 1**, because a `png2asset` blob that
  size would eat bank 0. The cart is ROM-only and never switches banks, so bank
  1 is permanently mapped at 0x4000 and `main.c`'s plain pointers reach it.

**No automated check covers the pixels.** PyBoy emulates a DMG, where
`sgb_check()` is false and every line of the border path is skipped, and a ROM
without `-Wm-ys` renders no border in mGBA either — so a border can look
finished and appear nowhere. The artwork is therefore owed to an eyeball in an
emulator with SGB emulation on; `probe.p14_sgb_border` asserts only the bytes
that can be read.

## Build

    make          # luna.gb — the ROM
    make test     # host unit tests for sim.h, plain gcc, no emulator
    make probe    # headless PyBoy checks against the built ROM
    make fps      # the tick-rate assertion on its own (one frame per emulated frame)
    make shot     # a screenshot, to /tmp/luna.png
    make gfx      # regenerate gfx.h from mkgfx.py (committed)
    make border   # regenerate border_data.c from art/border_sgb.png (committed)
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
| `tools/mklevel.py` | Generates `terrain.h`: the level recipes, the profiles and pad tables they expand to, the two chain tables and the star field, with self-checks |
| `terrain.h` | Generated, committed — a plain `make` needs no Python |
| `tools/mktab.py` | Generates `tables.h`: the 16 thrust unit vectors |
| `tables.h` | Generated, committed |
| `mkgfx.py` | Generates `gfx.h`: the font, the terrain tiles, the pad deck, the four star tiles, the 16 ship frames and the four crash-burst frames |
| `gfx.h` | Generated, committed. Included by `main.c` only |
| `tools/mkborder.py` | Generates `art/border_sgb.png`, the Super Game Boy border, with self-checks |
| `art/border_sgb.png` | Generated, committed — the 256x224 border art |
| `sgb_border.c` / `.h` | The SGB border transfer, lifted verbatim from the sibling projects |
| `border_data.c` / `.h` | Generated by `make border`, committed — the border's tiles, map and palette, in bank 1 |
| `tests/test_sim.c` | Host tests for the physics and the landing rule |
| `tools/probe.py` | Headless emulator checks: the wiring between `sim.h` and `main.c` |
| `tools/shot.py` | Screenshot helper |
| `PLAY.md` | The player's guide |
| `luna-lander-field-guide.html` | The player's guide as one self-contained page, with the landing-envelope chart and the review. Hand-written, not generated |
| `Dockerfile` | The GBDK toolchain image `make image` builds |

## Testing strategy

The project is split so that each half can be checked by the tool that suits
it, and neither half is trusted to check itself.

`tests/test_sim.c` compiles `sim.h` with plain `gcc -std=c99` and runs the
physics on the host — no emulator, no ROM. It pins what the maths is: the exact
8.8 trajectory gravity produces from rest, the fraction bytes carrying between
ticks (a fraction byte that lived in a local instead of the state would quantise
the motion to whole pixels and look merely "chunky"), thrust as a direction out
of `tables.h`, the fuel economy, the sideways lean and the friction that settles
it, and every landing threshold
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
one iteration per emulated frame with the HUD blitted every tick. Since P13 the
DESCENT mode is covered by the same contract as LANDER — a full descent scripted
from the spawn to the pad, the camera held against the ship and clamped at both
bounds, the map streamed across its own wrap twice, the horizontal wrap under the
tall profile, and that same one-tick-per-frame check on the mode that had escaped
it. P14 is bytes rather than pixels: it asserts the ROM's SGB header and that
the border data is linked in at full length in bank 1, and says plainly that the
artwork itself is owed to a human looking at it on an emulated Super Game Boy.
P15 is the same split for the endings: it reads the pages off the BG tilemap
through the probe's own font ids — the heading, and the reason the ROM's own
`ship.verdict` says the crash was — and asserts the timing a screenshot cannot
show, that a crash's burst plays every frame of itself before the page covers it
and that a landing's page is immediate. Two crashes with different verdicts are
driven on purpose, so a page that always said the same word fails. P16 has two
halves and they fail for different reasons: a **data read** of all twenty-four
level rows against the profile symbol the generator named for each, the spawn
inside it and the pads under it — which is what would catch two good profiles
emitted in the wrong order, something no flight can see — and a **flight** of
the LANDER chain that lands, crashes, advances, resumes from the title and
arrives at the completion page into a lap whose tank is measurably shorter.

`make probe` exits 0 when every check passes, 1 when a check fails, and 2 when
the harness itself broke — so a stuck ROM is never mistaken for a passing one.

## Not implemented yet (by design)

- **A score that outlives a life, or a saved high score.** A landing scores its
  pad's multiplier on its page and that is the end of it. Keeping one across
  sessions needs a battery-backed cart, which is a hardware/BOM decision rather
  than just a code change.
- **Difficulty or a wind model.** Gravity and thrust are two constants, and no
  level tunes them — the only thing that ramps is the tank, once per lap. The
  weather is not a feature yet.
- **Music.** The three event sounds are hand-written register writes; there is
  no sound driver.

## Release

The ROM is never committed: `*.gb`, the linker map and the object files are all
gitignored, and the built `luna.gb` is attached to a
[GitHub release](https://github.com/Zapskii/GB-Luna-Lander/releases) instead.
To reproduce a release binary, run `make probe` and then `make clean` and `make`
(the probe leaves a `-debug` ROM in `luna.gb`, and it is newer than the sources),
and record the md5 before you upload it.
