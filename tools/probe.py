#!/usr/bin/env python3
"""Headless check harness for LUNA LANDEER.

WHY THIS EXISTS: tools/shot.py takes a picture, which only tells you the screen
is not blank.  This drives the game and reads the game's OWN variables out of the
emulator, so a rule can be asserted -- "the tiles went up before the display
did", "the ship's whole-pixel y advances" -- instead of eyeballed.  It is the
emulator counterpart to tests/test_sim.c: that one covers the maths in sim.h,
this one covers the wiring between the maths and main.c.

    make probe            # or: tools/probe.py luna.gb luna.map
    make fps              # one check on its own: ... luna.gb luna.map p1_boot

The variable addresses are PARSED FROM luna.map rather than hardcoded, so adding
or reordering a static cannot silently make this read the wrong byte.  Only
main.c's file-scope statics are reachable that way (`Fmain$name$0$0`), which is
where the storage this reads has to live.  Run `make sym` first: the map only
carries statics for a -debug build, and `make sym` is also what the emulator
debuggers want.

EXIT CODES -- the phase gate depends on this split:
    0  every check passed
    1  a check failed   (including "a symbol this phase introduces is absent",
                         which is what a power gate on an older ROM looks like)
    2  the harness broke (ROM will not boot, map unreadable, PyBoy raised)

This is a DEV TOOL. Nothing in the build depends on it.
"""
import re
import sys

from pyboy import PyBoy

KEYS = {"R": "right", "L": "left", "U": "up", "D": "down",
        "A": "a", "B": "b", "S": "start", "T": "select"}

# --- layout constants, straight out of main.c / mkgfx.py --------------------
MAP0 = 0x9800                   # the BG tilemap: 32x32 bytes, one per tile
MAP_W = MAP_H = 32
VIEW_W, VIEW_H = 20, 18         # what SCX/SCY = 0 puts on the screen
LCDC = 0xFF40
LCDC_ON = 0x80                  # bit 7: the display.  While it is set the PPU
                                # locks VRAM, which is the whole of p1_boot's
                                # second assertion.
OAM = 0xFE00                    # 4 bytes per slot: y, x, tile, attrs
OAM_DY, OAM_DX = 16, 8          # an 8x8 sprite DRAWS at (x-8, y-16), so the
                                # raw OAM byte is the position plus this.
                                # Reading the raw byte and comparing it to the
                                # ship's own y is the point: it is the only way
                                # to tell "the renderer reads the state" from
                                # "the renderer keeps its own copy".

# gfx.h's ids, mirrored here on purpose: mkgfx.py, gfx.h and this file are a
# three-way contract, and a probe that asked gfx.h for them could not tell a
# renamed tile from a wrong one.
T_BLANK = 0
T_TERRAIN = 1
T_TERRAIN_TOP = 2

# terrain.h's geometry, mirrored for the same reason: tools/mklevel.py,
# terrain.h and this file are the second three-way contract.  A probe that read
# terrain.h could not tell a generator that gives the x2 pad the x1 row from one
# that gives it the right one.
#
# WORLD_COLS is 160 px / 8 px per tile.  NOT a power of two -- 160 is not 256 --
# which is why the wrap in sim.h is two compares and never an & WORLD_MASK.
WORLD_COLS = 20
PAD_COUNT = 2
PAD_ROW = {1: 12, 2: 9}         # multiplier -> the surface row that pad sits at

FRAMES = 120                    # how long the tick-rate assertion runs

# sim.h's Ship, as SDCC laid it out -- offsets taken from the compiler's own
# CDB record for it (`T:Fmain$__00000005[...]` in luna.cdb), not guessed:
#   x @0 (u16)  y @2 (u16)  xf @4  yf @5  vx @6 (i16)  vy @8 (i16)  = 10 bytes
# Mirrored here for the same reason the tile ids are: a probe that asked sim.h
# for its own struct could not tell a reordered struct from a correct one, and
# reordering it is exactly how the fraction byte ends up somewhere this check
# is not looking.
SHIP_LEN = 10
SHIP_X, SHIP_Y, SHIP_XF, SHIP_YF, SHIP_VX, SHIP_VY = 0, 2, 4, 5, 6, 8

# sim.h's gravity knob, mirrored.  P5 retunes the feel and WILL move this; the
# p3_gravity identity below is what has to keep holding when it does.
GRAV = 16

GRAV_SPAN = 8                   # ticks between the two position samples
GRAV_POLL = 400                 # frames to wait for the cartridge to start


def parse_map(path):
    """`     0000C0B6  Fmain$frame$0$0   main$` -> {'frame': 0xC0B6}.

    Only the file-scope objects of main (Fmain$...), which is all this needs."""
    out = {}
    for line in open(path):
        m = re.match(r"\s*([0-9A-Fa-f]{8})\s+Fmain\$(\w+?)(?:\$\d+_\d+)?\$\d+", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


fails = []


def check(cond, msg):
    print("  %s  %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        fails.append(msg)
    return cond


class Game:
    def __init__(self, rom, mapfile):
        self.p = PyBoy(rom, window="null", sound_emulated=False)
        self.addr = parse_map(mapfile)
        self.rom = rom
        self.mapfile = mapfile

    def need(self, *names):
        """Record a failure for each symbol absent from the map.

        A missing symbol is an ASSERTION failure, not a harness error: it means
        the phase that introduces it has not run.  That is exactly the question
        a power gate asks, and it must answer 1, not 2."""
        for n in names:
            check(n in self.addr, "symbol %s is in the map" % n)
        return all(n in self.addr for n in names)

    def var(self, name, n=1):
        b = self.p.memory[self.addr[name]:self.addr[name] + n]
        return b[0] if n == 1 else list(b)

    def u16(self, name):
        b = self.p.memory[self.addr[name]:self.addr[name] + 2]
        return b[0] | (b[1] << 8)

    def ship(self):
        """The ship's own state, field by field (see the offset table above)."""
        b = self.var("ship", SHIP_LEN)

        def u16(i):
            return b[i] | (b[i + 1] << 8)

        def s16(i):
            v = u16(i)
            return v - 0x10000 if v & 0x8000 else v

        return {"x": u16(SHIP_X), "y": u16(SHIP_Y),
                "xf": b[SHIP_XF], "yf": b[SHIP_YF],
                "vx": s16(SHIP_VX), "vy": s16(SHIP_VY)}

    def oam(self, slot=0):
        """The raw OAM bytes for one sprite slot: y, x, tile, attrs."""
        return list(self.p.memory[OAM + 4 * slot:OAM + 4 * slot + 4])

    def tile(self, x, y):
        return self.p.memory[MAP0 + y * MAP_W + x]

    def lcdc(self):
        return self.p.memory[LCDC]

    def run(self, frames, buttons=""):
        ks = [KEYS[c] for c in buttons if c in KEYS]
        for _ in range(frames):
            for k in ks:
                self.p.button_press(k)
            self.p.tick(1, True)
            for k in ks:
                self.p.button_release(k)

    def start(self, boot=150, settle=30):
        """Boot, then tap START.  START is held across several frames because
        PyBoy swallows input for a few ticks after its own boot splash.  P1 has
        no title screen to press through, so this is the seam later phases use
        and nothing here depends on it."""
        self.run(boot)
        self.run(8, "S")
        self.run(settle)


# ------------------------------------------------------------------ P1 -----
def p1_boot(g):
    """The ROM boots, ticks once per emulated frame, and draws the generated
    terrain -- with the tile load done before the display went on.

    Raw, with no start() helper: P1 has no title screen, so there is nothing to
    press, and pressing START to reach the screen would make this unable to tell
    a ROM that boots from one that needs a button first.
    """
    print("P1 boot")
    if not g.need("frame", "lcdc_at_load"):
        return

    # The Game constructor ticks NOTHING: without this burst first, every read
    # below is of an emulator that has not run main() yet.  150 frames is past
    # PyBoy's own boot splash and past the tile load either way.
    g.run(150)
    f0 = g.u16("frame")
    g.run(FRAMES)
    f1 = g.u16("frame")
    # One loop iteration is one tick, and wait_vbl_done() paces the loop, so N
    # emulated frames advance the counter by N.  Anything else means the loop
    # ran twice in a frame or not at all -- which is also the frame-rate check:
    # a render that overruns the budget halves the game and reads as +0 per
    # frame here, with no other symptom.
    check(f1 - f0 == FRAMES,
          "frame advances once per emulated frame (%d emulated frames -> +%d)"
          % (FRAMES, f1 - f0))

    # The tiles went into VRAM with the display OFF, and the display is on now.
    # PyBoy does not model the PPU's VRAM write lock, so the finished screen
    # cannot tell the two orders apart and no pixel check can stand in for this:
    # lcdc_at_load in main.c samples LCDC at the last tile write, which IS the
    # order rather than a proxy for it.  (On hardware, getting this wrong shows
    # as a garbage frame or a half-loaded bank; here only the sample can.)
    at_load = g.var("lcdc_at_load")
    check(at_load & LCDC_ON == 0,
          "the tiles were loaded with the display off (LCDC 0x%02X at the "
          "last VRAM write)" % at_load)
    now = g.lcdc()
    check(now & LCDC_ON == LCDC_ON,
          "and the display is on once the boot is done (LCDC 0x%02X)" % now)

    # The screen that boot leaves behind.  The tilemap records WHICH id was
    # written, never whether the bank behind it holds the art -- which is why
    # T_TERRAIN is a flecked tile and not a flat fill: a flat fill and an
    # unloaded bank look identical on a screenshot.
    #
    # P1 filled the whole map, so the whole view was the terrain tile here.  P2
    # blits the height profile over it and puts sky above the surface, so "the
    # whole screen is T_TERRAIN" stopped being true and this is NARROWED to what
    # survives both -- not deleted, because the one thing it proves that no
    # other check does is that the generated id reached the map at all.  P2
    # owns the layout now (see p2_terrain); this keeps the boot-level claim.
    seen = set()
    ground = 0
    for y in range(VIEW_H):
        for x in range(VIEW_W):
            t = g.tile(x, y)
            seen.add(t)
            if t in (T_TERRAIN, T_TERRAIN_TOP):
                ground += 1
    extra = sorted(seen - {T_BLANK, T_TERRAIN, T_TERRAIN_TOP})
    check(not extra,
          "the first screen holds only generated tiles -- nothing from an "
          "unloaded bank (%r is on screen)" % extra)
    check(ground >= VIEW_W,
          "and the generated ground is really drawn (%d of %d cells, at least "
          "one surface tile per column)" % (ground, VIEW_W * VIEW_H))


# ------------------------------------------------------------------ P2 -----
def p2_terrain(g):
    """The generator's heightmap and the screen agree, column by column.

    Two things can be wrong here while both look entirely plausible: the row
    blitted can be a different number than terrain[col] (a `<< 3`, an
    off-by-one, a stale terrain.h the ROM was not rebuilt against), and a pad
    can be flat in the generator and stepped on the screen.  Neither is visible
    on a screenshot, which is why this reads the ROM's own arrays.
    """
    print("P2 terrain")
    # A symbol this phase introduces being ABSENT is an assertion failure, not a
    # harness error: that is exactly the power gate on an older ROM, and it has
    # to answer 1.
    if not g.need("terrain", "pads"):
        return

    g.run(150)                          # let main() run and blit

    # Read the level out of the ROM's OWN memory, not out of terrain.h.  The
    # question is what the ROM was BUILT with, and a probe that read the header
    # would pass on a terrain.h that never made it into the ROM.
    h = g.var("terrain", WORLD_COLS)

    # Every column's surface tile is at that column's terrain row.  This is the
    # whole target: the renderer and the data agreeing, cell by cell.
    bad = [(x, h[x], g.tile(x, h[x])) for x in range(WORLD_COLS)
           if g.tile(x, h[x]) != T_TERRAIN_TOP]
    check(not bad,
          "every column's surface tile is at its terrain[] row -- col:row:found "
          "%r" % bad[:5])

    # ...and the rest of the column follows from it: sky above, body below.
    bad = []
    for x in range(WORLD_COLS):
        for y in range(VIEW_H):
            want = (T_BLANK if y < h[x] else
                    T_TERRAIN_TOP if y == h[x] else T_TERRAIN)
            if g.tile(x, y) != want:
                bad.append((x, y, want, g.tile(x, y)))
    check(not bad,
          "the whole column is sky/surface/body exactly as terrain[col] says -- "
          "col:row:want:found %r" % bad[:5])

    # The pads.  Each is a flat run across its WHOLE width, and sits at the row
    # its multiplier earns: a x2 pad at the x1 row is flat and wrong, which is
    # the difference this reads the table for.
    raw = g.var("pads", PAD_COUNT * 3)
    for i in range(PAD_COUNT):
        col0, col1, mult = raw[3 * i], raw[3 * i + 1], raw[3 * i + 2]
        row = PAD_ROW.get(mult)
        if row is None or not col0 <= col1 < WORLD_COLS:
            check(False, "pad %d is malformed: cols %d..%d x%d, expected a span "
                         "inside 0..%d and a multiplier in %r"
                         % (i, col0, col1, mult, WORLD_COLS - 1,
                            sorted(PAD_ROW)))
            continue
        span = h[col0:col1 + 1]
        onscreen = [g.tile(x, h[x]) for x in range(col0, col1 + 1)]
        check(span == [row] * len(span) and set(onscreen) == {T_TERRAIN_TOP},
              "pad %d (cols %d..%d, x%d) is flat across its whole width at row "
              "%d -- terrain %r, screen %r"
              % (i, col0, col1, mult, row, span, onscreen))


# ------------------------------------------------------------------ P3 -----
def p3_gravity(g):
    """The ship falls, the fall is sub-pixel, and the sprite is drawn from the
    state rather than from a second copy of the position.

    Three things can be wrong here and only one of them is visible.  The render
    can track its own y (the sprite slides slowly away from the physics), and
    the fraction byte can live in ship_step()'s LOCALS instead of in the state
    -- which still moves the ship at every whole pixel but throws the sub-pixel
    remainder away, so it reads as "the physics is fine, it is just chunky".
    Neither is a screenshot.
    """
    print("P3 gravity")
    # A symbol this phase introduces being ABSENT is an assertion failure, not
    # a harness error -- that is the power gate on an older ROM (P2's has no
    # ship at all) and it has to answer 1, not 2.
    if not g.need("ship"):
        return

    # PyBoy runs the real boot ROM first, and that is a couple of seconds of
    # the CARTRIDGE not existing yet -- p1_boot's 150 frames covers it, and a
    # read before it returns nothing but zeroes.  This cannot simply run 150
    # frames and look, though: the ship starts falling on the cartridge's first
    # tick, so by then it has been falling for a second and a half and its y
    # has been round the 16-bit wrap.  Poll for the ROM's own loop instead --
    # `frame` is 0 until crt0 has run main() -- and sample from there.
    boot = 0
    while g.u16("frame") == 0 and boot < GRAV_POLL:
        g.run(1)
        boot += 1
    if not check(0 < boot < GRAV_POLL,
                 "the ROM reached its own tick loop (frame is counting after "
                 "%d frames)" % boot):
        return

    a = g.ship()
    g.run(GRAV_SPAN)
    b = g.ship()

    # The whole-pixel part advances.  (Masked to a byte: OAM holds a byte, and
    # move_sprite() is what does the truncation.)
    check(b["y"] > a["y"],
          "the ship's whole-pixel y advances as it falls (%d -> %d)"
          % (a["y"], b["y"]))

    # ... and the sprite is AT the state.  This is the assertion that fails if
    # main.c ever tracks a position of its own: the two would agree at first
    # and drift apart from there, and no tilemap or screenshot check can see it.
    #
    # One tick of slack, and no more.  move_sprite() writes GBDK's SHADOW OAM;
    # that only reaches the PPU's 0xFE00 on a vblank, so the bytes the hardware
    # is showing at any instant were written on the PREVIOUS tick -- this
    # compares the state read before a tick against the OAM read after it.  The
    # slack is in the phase, never in the value: a sprite that is ahead of the
    # state, parked, or missing its +8/+16 offset fails on every tick.
    bad = []
    for _ in range(12):
        s = g.ship()
        g.run(1)
        oy, ox = g.oam()[:2]
        if oy != ((s["y"] + OAM_DY) & 0xFF) or ox != ((s["x"] + OAM_DX) & 0xFF):
            bad.append((s["y"], oy, s["x"], ox))
    check(not bad,
          "the sprite shows the ship's own position, one vblank behind -- "
          "state y/OAM y/state x/OAM x mismatches %r" % (bad[:4],))

    # The 8.8 position moved by EXACTLY the integral of the velocity ramp over
    # the ticks between the two samples: sum of (v + GRAV*i) for i = 1..k.
    # This is the assertion the trap fails.  With the fraction byte in a local,
    # every tick returns v >> 8 and the remainders are discarded, so the ship
    # travels the sum of the whole-pixel parts instead -- roughly half of the
    # correct distance by here, and the only place that shows up is this number.
    k = (b["vy"] - a["vy"]) // GRAV
    got = (b["y"] - a["y"]) * 256 + (b["yf"] - a["yf"])
    want = k * a["vy"] + GRAV * k * (k + 1) // 2
    check(k > 0 and b["vy"] - a["vy"] == k * GRAV and got == want,
          "the 8.8 position advanced by the exact integral of the velocity "
          "ramp over %d ticks: got %d/256 px, want %d/256 px (vy %d -> %d)"
          % (k, got, want, a["vy"], b["vy"]))

    # ... and the fraction byte is ALIVE: it is non-zero on ticks where the
    # whole-pixel y has not moved.  A `frac` in a local leaves this byte at 0
    # for the whole run, which is the same statement as the line above from the
    # other side.  Four consecutive ticks rather than one because yf happens to
    # be 0 on the tick the 8.8 position lands exactly on a pixel boundary, and
    # four in a row cannot all land there for any sane gravity.
    live = 0
    for _ in range(4):
        g.run(1)
        live += 1 if g.ship()["yf"] else 0
    check(live, "the ship state's fraction byte is carrying the sub-pixel "
                "remainder between ticks (yf was 0 on all 4 sampled ticks)")


CHECKS = [("p1_boot", p1_boot), ("p2_terrain", p2_terrain),
          ("p3_gravity", p3_gravity)]


def main(rom, mapfile, only=None):
    # `fails` counts ASSERTIONS; a check group holds many.  Reporting one
    # against the other prints nonsense like "FAILED: 10 of 8 checks" in the
    # gate logs, so track the two separately.
    todo = [(n, f) for n, f in CHECKS if only is None or n == only]
    if not todo:
        raise ValueError("no check named %r (have %s)"
                         % (only, ", ".join(n for n, _ in CHECKS)))
    groups = 0
    for _name, fn in todo:
        g = Game(rom, mapfile)
        before = len(fails)
        try:
            fn(g)
        finally:
            g.p.stop()
        if len(fails) > before:
            groups += 1

    if fails:
        print("FAILED: %d assertions in %d of %d checks"
              % (len(fails), groups, len(todo)))
        return 1
    print("OK: %d checks passed" % len(todo))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "luna.gb",
                      sys.argv[2] if len(sys.argv) > 2 else "luna.map",
                      sys.argv[3] if len(sys.argv) > 3 else None))
    except Exception as e:                      # noqa: BLE001 -- the exit-2 edge
        print("HARNESS ERROR: %s: %s" % (type(e).__name__, e))
        sys.exit(2)
