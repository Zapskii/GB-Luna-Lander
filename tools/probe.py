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
T_DIGIT0, T_LETTER0, T_MINUS = 20, 30, 56

# terrain.h's geometry, mirrored for the same reason: tools/mklevel.py,
# terrain.h and this file are the second three-way contract.  A probe that read
# terrain.h could not tell a generator that gives the x2 pad the x1 row from one
# that gives it the right one.
#
# WORLD_COLS is 160 px / 8 px per tile.  NOT a power of two -- 160 is not 256 --
# which is why the wrap in sim.h is two compares and never an & WORLD_MASK.
WORLD_COLS = 20
PAD_COUNT = 2
PAD_ROW = {1: 12, 2: 9}         # multiplier -> the surface row that pad sits at,
                                # for the LANDER profile p2_terrain runs against

# P9's two numbers, mirrored for the same reason the tile ids are.  MAP_TILES
# is one BG map (32x32), which is the bound a profile that does not fit has to
# be blitted around; DESCENT_ROW0 is the profile row main.c's window top edge
# sits on, and it is nonzero on purpose -- the phase's whole target is that the
# surface tile lands where the OFFSET puts it, not where the profile's first
# rows are.
MAP_TILES = 32
DESCENT_ROW0 = 84

# main.c's screen state and its HUD layout, mirrored for the same reason the
# tile ids are.  Where a number SITS is part of the HUD, not a detail of it: a
# HUD that drew the right tank in the wrong row of the map is a bug, and this is
# the file that has to be able to see it, so the layout is written down here
# rather than derived from the ROM.
ST_TITLE, ST_PLAY = 0, 1
HUD_H = 2                       # the rows the HUD owns at the top of the field
HUD_FUEL_ROW, HUD_FUEL_COL, HUD_FUEL_W = 0, 5, 3
HUD_ALT_ROW, HUD_ALT_COL, HUD_ALT_W = 0, 13, 3
# Where the verdict lands in the strip once the life is over: the row the
# velocities are on, which is the row the outcome replaces.
HUD_VERDICT_ROW, HUD_VERDICT_COL = 1, 8
# That whole row, tile by tile, as the layout main.c writes it: 'd' is a digit
# and every other character is the tile the layout puts there.  Written out
# because the row is what a leftover from the last verdict shows up in, and a
# leftover is invisible to a string search -- see the check below.
HUD_VEL_ROW = "VX ddd VY ddd" + " " * (VIEW_W - 13)

FRAMES = 120                    # how long the tick-rate assertion runs

# sim.h's Ship, as SDCC laid it out -- offsets taken from the compiler's own
# CDB record for it (`T:Fmain$__00000006[...]` in luna.cdb), not guessed:
#   x @0 (u16)  y @2 (u16)  xf @4  yf @5  vx @6 (i16)  vy @8 (i16)
#   heading @10 (u8)  fuel @11 (u16)
#   state @13  verdict @14  mult @15                                 = 16 bytes
# Mirrored here for the same reason the tile ids are: a probe that asked sim.h
# for its own struct could not tell a reordered struct from a correct one, and
# reordering it is exactly how the fraction byte ends up somewhere this check
# is not looking.  fuel really is at an ODD offset -- SDCC packs structs, it
# does not pad them -- which is worth writing down because a probe that assumed
# alignment would read heading's neighbour.  P5's three bytes are APPENDED so
# that everything above them kept its address: this check reads a P4-era
# offset table plus three, and would silently misread state as fuel if the new
# fields had been inserted anywhere else.
SHIP_LEN = 16
SHIP_X, SHIP_Y, SHIP_XF, SHIP_YF, SHIP_VX, SHIP_VY = 0, 2, 4, 5, 6, 8
SHIP_HEADING, SHIP_FUEL = 10, 11
SHIP_STATE, SHIP_VERDICT, SHIP_MULT = 13, 14, 15

# sim.h's landing constants, mirrored for the same reason.  ST_FLY is what a
# ship that is still flying reads; LAND_* are the verdicts classify_landing()
# can return, and the check names the one it expects rather than "not SAFE" --
# a TOO_FAST that reported CRASH would be a rule nobody could read a score off.
ST_FLY, ST_LANDED, ST_CRASH = 0, 1, 2
LAND_SAFE, LAND_TOO_FAST, LAND_DRIFTING, LAND_TILTED, LAND_CRASH = 0, 1, 2, 3, 4

# The ship is one 8x8 sprite (mkgfx.py), so this is how far its top edge is
# above the surface it rests on.
SHIP_W = SHIP_H = 8

# main.c's spawn, mirrored: the ship starts in flight directly over the x2 pad,
# which is what makes "a hard drop" and "a soft descent" the same journey with
# different hands on the stick.
SPAWN_X, SPAWN_Y = 108, 16

# How long each half of the check may take before it gives up and FAILS.  A
# stuck ROM has to answer 1, not hang the harness into a timeout, which would
# answer 2 and look like a broken probe rather than a broken game.
DROP_LIMIT = 120                # a hard drop lands in about 39 ticks
DESCENT_LIMIT = 1500            # the scripted descent takes about 300

# The descent speed the soft-landing pilot burns above, in 8.8 px/frame.  Well
# under sim.h's SAFE_VY_MAX, because a pilot that flew the edge of the
# threshold would make this check a statement about the pilot and not the game.
VY_HOLD = 32

# sim.h's gravity and thrust knobs, mirrored.  P5 retunes the feel and WILL
# move these; the identities below -- the exact integrals and the exact
# fuel burn -- are what have to keep holding when it does.
GRAV = 16
THRUST = 32

# sim.h's fuel economy, mirrored for the same reason: the tank and the burn
# rate are P5's knobs, and the check is written as "the tank empties in
# FUEL_START / FUEL_BURN ticks" rather than against a hardcoded count.
FUEL_START = 600
FUEL_BURN = 1

# tables.h's heading count and gfx.h's first ship tile, mirrored: the sprite
# frame the PPU is told to draw is SPR_SHIP0 + heading, and that pairing is the
# wiring half of the phase.
ROT_STEPS = 16
SPR_SHIP0 = 0

# The APU's registers, mirrored from gb/gb.h for the same reason the tile ids
# are: this file writes down WHAT it expects, so a ROM that powers the APU on
# and routes it can be told from one that does -- or from one that only looks
# like it does.
NR12 = 0xFF12                   # CH1 volume / envelope: what thrust writes.
                                # NOT 0xFF17, which is NR22 -- CH2's, and CH2
                                # is the LANDING: a check that read that one
                                # would be watching the wrong channel and
                                # would read 0x00 on every ROM that never
                                # landed, which is most of this one.
NR22 = 0xFF17                   # CH2's, which is the LANDING
NR42 = 0xFF21                   # CH4's, which is the CRASH
NR50, NR51, NR52 = 0xFF24, 0xFF25, 0xFF26
APU_ON = 0x80                   # NR52 bit 7.  CLEAR at main() entry: crt0
                                # powers the APU down, and while it is clear
                                # every sound-register write reads back zero.
NR50_BOOT, NR51_BOOT = 0x77, 0xFF   # full volume, all four channels both sides

GRAV_SPAN = 8                   # ticks between the two position samples
GRAV_POLL = 400                 # frames to wait for the cartridge to start

THRUST_SPAN = 8                 # ticks to hold the button in p4_thrust


def glyph(c):
    """Character -> its tile id, the probe's OWN copy of main.c's glyph().

    Deliberately not imported from anywhere: the check below is that the
    tilemap spells the title, and a decoder that asked the ROM which id 'A' is
    could not tell a font that renumbered the letters from one that did not.
    Anything outside this map has no tile, which is exactly the set main.c
    sends to T_BLANK -- a lowercase literal decodes as a hole, not as a
    character, so this raises rather than quietly answering blank."""
    if "A" <= c <= "Z":
        return ord(c) - ord("A") + T_LETTER0
    if "0" <= c <= "9":
        return ord(c) - ord("0") + T_DIGIT0
    if c == "-":
        return T_MINUS
    if c == " ":
        return T_BLANK
    raise ValueError("no tile for %r" % c)


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
        # sound_emulated=True is REQUIRED by p7_sound, and costs nothing else
        # (every frame count below is unmoved by it).  With sound off, PyBoy
        # does not implement the APU at all -- pyboy/core/sound.py's get()
        # returns 0 for every offset before it looks at anything --
        # so NR52/NR50/NR51/NR12 read 0x00 forever and writes to them are
        # swallowed.  A register check written against that build fails on
        # EVERY ROM, its own included, which is a check that reads as "has
        # power" and is really noise; this is the same switch the sibling
        # project's sfx check needed.
        self.p = PyBoy(rom, window="null", sound_emulated=True)
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

    def profile(self, name):
        """A named profile's bytes, straight out of the ROM's own memory.

        Read at the ARRAY's own symbol and not through `terrain`: the question
        here is what the GENERATOR put in the ROM, and a probe that asked the
        selected pointer could not tell a profile that never made it into the
        build from one that did."""
        a = self.addr[name]
        return list(self.p.memory[a:a + WORLD_COLS])

    def active_profile(self):
        """The bytes `terrain` currently POINTS AT.

        `terrain` is a POINTER as of P9, not the array itself: two profiles
        share the ONE symbol so that sim.h's collision and this file keep
        reading what the renderer reads.  Reading WORLD_COLS bytes at the
        symbol's own address would hand back the pointer's two bytes and
        eighteen bytes of whatever the linker put after it -- which is a
        plausible-looking list of small numbers, and would read as a terrain
        bug rather than as a dereference that was never taken."""
        a = self.u16("terrain")
        return list(self.p.memory[a:a + WORLD_COLS])

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
                "vx": s16(SHIP_VX), "vy": s16(SHIP_VY),
                "heading": b[SHIP_HEADING], "fuel": u16(SHIP_FUEL),
                "state": b[SHIP_STATE], "verdict": b[SHIP_VERDICT],
                "mult": b[SHIP_MULT]}

    def boot(self, limit=GRAV_POLL):
        """Run until the CARTRIDGE's own tick loop is running, and return how
        many frames that took -- `frame` is 0 until crt0 has run main().

        PyBoy runs the real boot ROM first, which is a couple of seconds of the
        cartridge not existing yet, so a fixed frame count would either read
        zeroes or catch a ship that had been falling since before the check
        started.  Everything that samples a falling ship wants this, and wants
        it identical: a check that poked its own poll would be comparing itself
        against a slightly different tick.
        """
        n = 0
        while self.u16("frame") == 0 and n < limit:
            self.run(1)
            n += 1
        return n

    def oam(self, slot=0):
        """The raw OAM bytes for one sprite slot: y, x, tile, attrs."""
        return list(self.p.memory[OAM + 4 * slot:OAM + 4 * slot + 4])

    def tile(self, x, y):
        return self.p.memory[MAP0 + y * MAP_W + x]

    def find_text(self, s):
        """Every (row, col) where the tilemap spells `s`, through this file's
        own copy of the font ids.  An empty list is "the string is not on the
        screen", which is what a title that was never drawn answers."""
        want = [glyph(c) for c in s]
        hits = []
        for y in range(VIEW_H):
            row = [self.tile(x, y) for x in range(MAP_W)]
            for x in range(MAP_W - len(want) + 1):
                if row[x:x + len(want)] == want:
                    hits.append((y, x))
        return hits

    def hud_num(self, row, col, w):
        """The number in the `w` digit tiles at (col,row), or None if they are
        not all digits -- a blank, a letter or a tile from an unloaded bank.
        Read off the SCREEN rather than out of main.c's `bg`, which is the
        whole point: it is what the PPU was told, after the tile ids went
        through the font."""
        v = 0
        for i in range(w):
            t = self.tile(col + i, row)
            if not T_DIGIT0 <= t < T_DIGIT0 + 10:
                return None
            v = v * 10 + (t - T_DIGIT0)
        return v

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

    def play(self, settle=2):
        """Clear the title with START, so the checks that are about the play
        field are looking at the play field.

        START is held for several frames because PyBoy swallows input for a
        few ticks after its own boot splash, and one of those frames has to be
        the EDGE main.c reads.  `settle` is kept SHORT on purpose: the ship is
        falling from the tick the title goes away, and a check that sampled it
        30 ticks later would be sampling a ship already most of the way down.
        An older ROM has no title to clear and simply restarts the life, which
        is why this is safe to call on one."""
        self.run(8, "S")
        self.run(settle)


# ------------------------------------------------------------------ P1 -----
def p1_boot(g):
    """The ROM boots, ticks once per emulated frame, and draws the generated
    terrain -- with the tile load done before the display went on.

    The boot-level half is raw: nothing is pressed, because "the ROM ticks
    without a hand on it" is a claim about the boot and is the one thing here
    that START would paper over.  The screen half is behind one START as of P6,
    where the ROM legitimately boots to a TITLE rather than to the field -- so
    the terrain assertions moved to the field the phase's gameplay lives on
    instead of being weakened to fit a screen they are not about.
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

    # The screen the game opens on is the TITLE, and P6 is the phase that owns
    # it -- but the boot-level claim below is about the field, so it presses
    # through the title rather than asserting anything about it (p6_hud does
    # that, with the font).
    g.play()

    # The screen behind the title.  The tilemap records WHICH id was written,
    # never whether the bank behind it holds the art -- which is why T_TERRAIN
    # is a flecked tile and not a flat fill: a flat fill and an unloaded bank
    # look identical on a screenshot.
    #
    # P1 filled the whole map, so the whole view was the terrain tile here.  P2
    # blits the height profile over it and puts sky above the surface, so "the
    # whole screen is T_TERRAIN" stopped being true and this is NARROWED to what
    # survives both -- not deleted, because the one thing it proves that no
    # other check does is that the generated id reached the map at all.  P2
    # owns the layout now (see p2_terrain); this keeps the boot-level claim.
    #
    # The top two rows are the HUD as of P6, so the region this reads is below
    # them: the HUD is a strip of font tiles over sky, and a check that called
    # those "a tile from an unloaded bank" would be describing the HUD, not the
    # terrain.
    seen = set()
    ground = 0
    for y in range(HUD_H, VIEW_H):
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
          "one surface tile per column)" % (ground, VIEW_W * (VIEW_H - HUD_H)))


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
    g.play()                            # P6: past the title, onto the field

    # Read the level out of the ROM's OWN memory, not out of terrain.h.  The
    # question is what the ROM was BUILT with, and a probe that read the header
    # would pass on a terrain.h that never made it into the ROM.  As of P9
    # `terrain` is the selected profile POINTER, so this goes through it rather
    # than reading at the symbol -- see Game.active_profile().
    h = g.active_profile()

    # Every column's surface tile is at that column's terrain row.  This is the
    # whole target: the renderer and the data agreeing, cell by cell.
    bad = [(x, h[x], g.tile(x, h[x])) for x in range(WORLD_COLS)
           if g.tile(x, h[x]) != T_TERRAIN_TOP]
    check(not bad,
          "every column's surface tile is at its terrain[] row -- col:row:found "
          "%r" % bad[:5])

    # ...and the rest of the column follows from it: sky above, body below.
    # Starts BELOW the HUD strip, which P6 draws over the top two rows of every
    # column.  Those rows are sky in all of them (the highest surface row is 9,
    # well under the strip), so this skips text rather than terrain: the rows
    # the surface can actually reach are all still checked, in every column.
    bad = []
    for x in range(WORLD_COLS):
        for y in range(HUD_H, VIEW_H):
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

    # The ship starts falling on the cartridge's FIRST tick, so every sample
    # below has to be taken from the ROM's own loop rather than from a fixed
    # frame count: PyBoy runs the real boot ROM first, and a read before that
    # is over returns nothing but zeroes.
    boot = g.boot()
    if not check(0 < boot < GRAV_POLL,
                 "the ROM reached its own tick loop (frame is counting after "
                 "%d frames)" % boot):
        return

    # P6: the ROM opens on the title, where the ship is parked and the physics
    # is not running -- so the boot poll above finds the loop, and START is what
    # starts the fall.  Every check below is a differential or a spawn reading,
    # so the couple of ticks this costs change nothing.
    g.play()

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
    # One tick of slack, and no more.  move_sprite() writes GBDK's SHADOW OAM
    # and only a vblank copies it to 0xFE00, and that vblank falls within a
    # handful of instructions of the frame boundary this file samples at -- so
    # which SIDE of the copy a sample lands on is decided by the length of the
    # loop body, which is not a number any check should pin.  P6 grew the body
    # (the HUD blit) and moved it; the accepted state on either side of the copy
    # is therefore the tick before the sample or the tick after it.
    #
    # The slack is in the PHASE, never in the value.  What this still rejects,
    # on every tick: a sprite parked or hidden, one missing its +8/+16 offset
    # (out by 8 and 16, which is not one tick of anything), and -- the reason
    # the check exists -- a renderer carrying a position of its own, which
    # agrees at the spawn and is a pixel further out every frame after that.
    bad = []
    for _ in range(12):
        before = g.ship()
        g.run(1)
        after = g.ship()
        oy, ox = g.oam()[:2]
        if oy not in (((before["y"] + OAM_DY) & 0xFF),
                      ((after["y"] + OAM_DY) & 0xFF)) or \
           ox not in (((before["x"] + OAM_DX) & 0xFF),
                      ((after["x"] + OAM_DX) & 0xFF)):
            bad.append((before["y"], after["y"], oy, before["x"], after["x"], ox))
    check(not bad,
          "the sprite shows the ship's own position, one vblank behind -- "
          "state y before/after, OAM y, state x before/after, OAM x "
          "mismatches %r" % (bad[:4],))

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


# ------------------------------------------------------------------ P4 -----
def p4_thrust(g):
    """Thrust beats gravity while the tank lasts, and then does nothing at all.

    Two things can be wrong here and neither is a screenshot.  Thrust can be a
    MAGNITUDE without a direction -- the ship rises whichever way its nose
    points, which looks fine until you turn it -- and the fuel can burn in
    main.c's tick loop instead of inside sim.h's step, which reads identically
    until a frame overruns its budget and quietly buys the player fuel.  Both
    are asserted against the state the ROM itself is running on.
    """
    print("P4 thrust")
    # A symbol this phase reads being ABSENT is an assertion failure, not a
    # harness error: that is the power gate on P3's ROM, which has a `ship` but
    # no heading and no fuel, and it has to answer 1, not 2.
    if not g.need("ship"):
        return

    # The same poll p3_gravity uses: the ship is falling from the cartridge's
    # first tick, so sample from the ROM's own loop rather than from a fixed
    # frame count, which would catch it already most of the way down.
    boot = g.boot()
    if not check(0 < boot < GRAV_POLL,
                 "the ROM reached its own tick loop (frame is counting after "
                 "%d frames)" % boot):
        return

    # P6: past the title.  The ship is parked while the title is up, so nothing
    # has burned or turned before this -- which is exactly what the two checks
    # below read the spawn for.
    g.play()

    s = g.ship()
    check(s["heading"] == 0 and s["fuel"] == FUEL_START,
          "the ship spawns nose up with a full tank (heading %d, fuel %d)"
          % (s["heading"], s["fuel"]))

    # ---- held: the net vertical acceleration reverses ---------------------
    # The heading is 0, so thrust_dy[0] is -256 and the per-tick vy change is
    # GRAV + ((THRUST * -256) >> 8) == GRAV - THRUST.  Asserted as the exact
    # sum over the span, so a thrust that is merely "bigger than gravity"
    # rather than exactly THRUST fails here rather than passing on a sign.
    k = THRUST_SPAN
    a = g.ship()
    g.run(k, "U")
    b = g.ship()
    check(b["fuel"] == a["fuel"] - FUEL_BURN * k,
          "holding UP burns exactly %d fuel per tick (%d -> %d over %d ticks)"
          % (FUEL_BURN, a["fuel"], b["fuel"], k))
    check(b["vy"] - a["vy"] == (GRAV - THRUST) * k,
          "and the net vertical acceleration has REVERSED -- vy rises by "
          "(THRUST - GRAV) * %d == %d against gravity over those ticks "
          "(vy %d -> %d)" % (k, (THRUST - GRAV) * k, a["vy"], b["vy"]))

    # ---- released: the previous descent resumes, exactly ------------------
    c = g.ship()
    g.run(k)
    d = g.ship()
    check(d["vy"] - c["vy"] == GRAV * k,
          "on release the previous descent resumes at exactly GRAV per tick "
          "(%d -> %d over %d ticks)" % (c["vy"], d["vy"], k))
    check(d["fuel"] == c["fuel"],
          "and nothing burns with the button up (%d -> %d)"
          % (c["fuel"], d["fuel"]))

    # ---- the tank ---------------------------------------------------------
    # One emulated frame is one tick is one burn, so this counts FRAMES -- and
    # a step that burned fuel per RENDER rather than per tick lands somewhere
    # else entirely the moment the frame budget slips.  Bounded, so a ROM that
    # never burns (or a heading/fuel read out of a shorter struct) FAILS here
    # instead of hanging the harness: a timeout would answer 2, and the gate
    # needs 1.
    f0 = g.ship()["fuel"]
    spent = 0
    while g.ship()["fuel"] and spent < FUEL_START + 200:
        g.run(1, "U")
        spent += 1
    e = g.ship()
    if not check(e["fuel"] == 0,
                 "holding UP empties the tank (%d of %d fuel left after %d "
                 "ticks)" % (e["fuel"], FUEL_START, spent)):
        return
    check(spent == (f0 + FUEL_BURN - 1) // FUEL_BURN,
          "and it takes exactly the fuel it held: %d units at %d per tick is "
          "%d ticks (took %d)" % (f0, FUEL_BURN,
                                  (f0 + FUEL_BURN - 1) // FUEL_BURN, spent))

    # ---- empty: the button is inert ---------------------------------------
    # The other half of the target.  With the tank dry, holding UP changes the
    # trajectory by NOTHING at all -- vy falls by gravity alone and vx does not
    # move -- so the ship is committed to its descent.
    f = g.ship()
    g.run(k, "U")
    h = g.ship()
    check(h["vy"] - f["vy"] == GRAV * k and h["vx"] == f["vx"] and h["fuel"] == 0,
          "an empty tank makes thrust inert -- %d ticks of held UP change vy "
          "by exactly GRAV * %d == %d and leave vx at %d (vy %d -> %d)"
          % (k, k, GRAV * k, f["vx"], f["vy"], h["vy"]))

    # ---- the stick: one press, one step, and the frame follows it ---------
    # A and B are EDGES, so they are held for several frames on purpose: an
    # edge that fired once per frame would spin the ship through a whole
    # revolution on one press, and holding is the only way to tell from the
    # outside.  The heading is 0 here -- nothing above pressed A or B.
    h0 = g.ship()["heading"]
    g.run(4, "B")
    h1 = g.ship()["heading"]
    check(h1 == (h0 + 1) % ROT_STEPS,
          "four frames of held B are ONE rotation step, not four (heading "
          "%d -> %d)" % (h0, h1))

    # One vblank of slack, and no more: set_sprite_tile writes GBDK's SHADOW
    # OAM, which only reaches the PPU's 0xFE00 on the next vblank.  The slack
    # is in the phase, never in the value -- a ship drawn on frame 0 whatever
    # its heading fails here.
    g.run(3)
    check(g.oam()[2] == SPR_SHIP0 + h1,
          "and the sprite frame follows the heading (heading %d draws tile "
          "0x%02X, expected 0x%02X)" % (h1, g.oam()[2], SPR_SHIP0 + h1))

    g.run(4, "A")
    check(g.ship()["heading"] == h0,
          "A steps the other way, back to where we started (heading %d)"
          % g.ship()["heading"])

    # A button-free tick between two presses, and it is not optional: run()
    # holds the button for every frame it is given and releases it after the
    # tick, so the ROM's prev_keys is still A when the next run starts and the
    # following press is not an EDGE.  Two presses back to back would read as
    # one and this assertion would fail on a perfectly good ROM.
    g.run(2)
    g.run(4, "A")
    check(g.ship()["heading"] == (h0 - 1) % ROT_STEPS,
          "and keeps going the other way past it, wrapping rather than "
          "underflowing (heading %d)" % g.ship()["heading"])


# ------------------------------------------------------------------ P5 -----
def p5_landing(g):
    """A hard drop crashes; a soft descent onto the pad lands and scores it.

    The whole phase is a RULE in sim.h, so this reads the rule's own output --
    the state, the verdict and the multiplier the ROM wrote into its own
    storage -- and never the screen.  A check that read tiles would prove the
    renderer, and the renderer is three lines of wiring; tools/shot.py is what
    that is for.

    Both halves fly the same journey from the same spawn.  The ship starts in
    flight directly above the x2 pad, so nothing here has to steer: the drop
    does nothing at all, and the descent burns thrust whenever it is falling
    faster than VY_HOLD.  That is what makes this a check about the VERDICT
    rather than about a pilot -- one hand on the stick is the entire
    difference between the two outcomes.
    """
    print("P5 landing")
    # A symbol this phase reads being ABSENT is an assertion failure, not a
    # harness error.  terrain/pads are P2's and ship is P3's, so on those ROMs
    # this answers 1 -- but the real power gate is the P4 ROM, where every
    # symbol is present and the LANDING is not, and it is the behaviour below
    # (the ship coming to rest on the surface) that has to answer 1 there.
    if not g.need("ship", "terrain", "pads"):
        return

    boot = g.boot()
    if not check(0 < boot < GRAV_POLL,
                 "the ROM reached its own tick loop (frame is counting after "
                 "%d frames)" % boot):
        return

    # P6: past the title.  Both halves fly the same journey from the same
    # spawn, and the spawn is only reached once START has cleared the title --
    # the ship does not fall while the title is up, which is what lets this
    # check sample it from the top.
    g.play()

    # The level, out of the ROM's OWN memory, and the column the ship's own
    # spawn x stands on.  The check has to agree with the ROM about where the
    # ship is and what is under it -- reading main.c's or sim.h's constants
    # here would make this a check on the comments.  As of P9 this is the
    # SELECTED profile, through the pointer rather than at the symbol.
    h = g.active_profile()
    raw = g.var("pads", PAD_COUNT * 3)
    pads = [(raw[3 * i], raw[3 * i + 1], raw[3 * i + 2]) for i in range(PAD_COUNT)]

    s0 = g.ship()
    check(s0["x"] == SPAWN_X and s0["state"] == ST_FLY,
          "the ship spawns in flight above the pad (x %d, state %d)"
          % (s0["x"], s0["state"]))

    col = (s0["x"] + SHIP_W // 2) >> 3
    ground = h[col] * 8
    under = [m for (c0, c1, m) in pads if c0 <= col <= c1]
    # Deliberately NOT an early return.  A ROM with no landing rule at all --
    # the previous phase's -- fails the two assertions above, and it has to
    # fail everything below them as well rather than be excused from the half
    # of the check that is actually about landing.  `want` is the multiplier
    # the pad table names for this column, or 0 for ground that is not a pad.
    check(bool(under),
          "and what is under it is a pad, so the drop has somewhere to land "
          "(column %d of %d, pads %r, terrain %r)"
          % (col, WORLD_COLS, pads, h))
    want = under[0] if under else 0

    # ---- the hard drop: no buttons at all --------------------------------
    # Gravity from rest arrives at about 620/256 px/frame, nearly five times
    # SAFE_VY_MAX, so the verdict is TOO_FAST -- not CRASH, which is reserved
    # for ground that is not a pad at all.
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DROP_LIMIT:
        g.run(1)
        ticks += 1
    s = g.ship()
    check(s["state"] == ST_CRASH,
          "a hard drop ends in the crash state (state %d after %d ticks)"
          % (s["state"], ticks))
    # THIS is the assertion with power, and the reason the rest of the check
    # could not stand in for it: it holds whether or not the state byte reads
    # sanely, because it is about where the ship IS.  A ROM with no collision
    # -- the previous phase's -- falls straight through this row and fails here
    # however the three bytes appended to Ship happen to land in memory.
    check(s["y"] + SHIP_H == ground,
          "and it comes to rest ON the surface rather than falling through it "
          "(underside %d, surface %d)" % (s["y"] + SHIP_H, ground))
    check(s["verdict"] == LAND_TOO_FAST,
          "the verdict says why: the pad was there, the arrival was not "
          "(verdict %d, expected TOO_FAST)" % s["verdict"])
    check(s["mult"] == 0,
          "and a crash scores nothing (%d)" % s["mult"])

    # ---- START restarts --------------------------------------------------
    # An EDGE, so 8 held frames are one restart -- and the restart landing on
    # the last of them is why the ship is allowed a few ticks of falling below.
    g.run(8, "S")
    g.run(1)
    s = g.ship()
    check(s["state"] == ST_FLY and s["y"] < SPAWN_Y + 16 and
          s["fuel"] == FUEL_START and s["mult"] == 0,
          "START restarts the life -- back in flight near the spawn with a "
          "full tank (state %d, y %d, fuel %d, mult %d)"
          % (s["state"], s["y"], s["fuel"], s["mult"]))

    # ---- the soft descent ------------------------------------------------
    # Burn whenever the ship is falling faster than VY_HOLD.  Thrust at heading
    # 0 is straight up, and the ship is never rotated here, so this is a
    # one-dimensional descent: it comes down the same column it started on.
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1, "U" if g.ship()["vy"] > VY_HOLD else "")
        ticks += 1
    s = g.ship()
    check(s["state"] == ST_LANDED,
          "a controlled descent onto the pad ends in the LANDED state "
          "(state %d after %d ticks, vy %d)" % (s["state"], ticks, s["vy"]))
    check(s["verdict"] == LAND_SAFE,
          "and the verdict is SAFE (verdict %d)" % s["verdict"])
    check(s["y"] + SHIP_H == ground and s["vy"] == 0,
          "and it is resting on the surface with nothing left over (underside "
          "%d, surface %d, vy %d)" % (s["y"] + SHIP_H, ground, s["vy"]))
    # The multiplier the ROM scored, against the multiplier the ROM's OWN pads
    # table gives that column -- and then against the literal 2, because a
    # check that only compared the two would pass on a score hardcoded to
    # whatever the table said.
    check(s["mult"] == want == 2,
          "the landing scores the pad's multiplier out of terrain.h -- x2 for "
          "the pad under the spawn (scored %d, table says %d)"
          % (s["mult"], want))


# ------------------------------------------------------------------ P6 -----
def p6_hud(g):
    """The title spells itself on the screen, START clears it, and the HUD
    numbers are the ship's OWN state rather than a copy of it.

    Read through this file's copy of the font ids -- glyph() above -- because
    the claim is about what the PPU was told, and "the number changed" is not it:
    a HUD showing a counter of its own would change, and would still be wrong.
    Every reading below is therefore checked against the state byte the ROM is
    running on, the same tick.

    The title half needs NO symbol out of the map: it is a claim about the
    tilemap, so it is the half that fails on a ROM with no title screen at all
    -- which is exactly the power gate on the previous phase's ROM.
    """
    print("P6 hud")
    g.run(150)                          # let main() run and draw the title

    # ---- the title -------------------------------------------------------
    title = g.find_text("LUNA LANDEER")
    check(bool(title),
          "the title spells the game's name on the screen (%r)" % (title,))
    check(bool(g.find_text("PRESS START")),
          "and says how to start it (%r)" % (g.find_text("PRESS START"),))
    # The mode line, and THEN the map's mode byte, so a title that advertised a
    # mode the ROM had not selected fails here rather than reading well.
    if not g.need("game", "pick", "ship"):
        return
    check(g.var("pick") == 0 and bool(g.find_text("MODE LANDER")),
          "and offers the mode the ROM actually starts in -- LANDER, mode %d "
          "(%r)" % (g.var("pick"), g.find_text("MODE LANDER")))
    check(g.var("game") == ST_TITLE,
          "the title is the state the ROM boots into (game %d)" % g.var("game"))

    # SELECT is the mode toggle, and it is an EDGE -- held for four frames it
    # flips the mode once, not four times.  What it re-sends is ONE ROW of the
    # map: the whole title is only ever blasted at boot, so a title that still
    # advertised the old mode after a press would be a row blitted at the wrong
    # address, and this is the only thing that can tell.
    #
    # Not asserted here, either way: what START then does with DESCENT.  M2 is
    # where that question gets an answer, and a check written now would be
    # pinning P6's answer to it.
    g.run(4, "T")
    g.run(2)                            # button-free: the next press is an EDGE
    check(g.var("pick") == 1 and bool(g.find_text("MODE DESCENT")),
          "SELECT flips the mode and the title says so -- DESCENT, mode %d (%r)"
          % (g.var("pick"), g.find_text("MODE DESCENT")))
    g.run(4, "T")
    g.run(2)
    check(g.var("pick") == 0 and g.find_text("MODE DESCENT") == [] and
          bool(g.find_text("MODE LANDER")),
          "and flips it back, one row at a time -- LANDER, mode %d, %r left "
          "behind" % (g.var("pick"), g.find_text("MODE DESCENT")))

    # ---- START clears it -------------------------------------------------
    g.play()
    check(g.var("game") == ST_PLAY,
          "START clears the title (game %d)" % g.var("game"))
    check(g.find_text("LUNA LANDEER") == [] and
          g.find_text("PRESS START") == [],
          "and the title's text is gone from the screen (%r, %r)"
          % (g.find_text("LUNA LANDEER"), g.find_text("PRESS START")))
    check(bool(g.find_text("FUEL")),
          "the HUD takes its place (%r)" % (g.find_text("FUEL"),))

    # ---- the fuel counts down as fuel burns -------------------------------
    a = g.ship()
    f0 = g.hud_num(HUD_FUEL_ROW, HUD_FUEL_COL, HUD_FUEL_W)
    # One tick of slack, and no more.  main.c builds the buffer, waits for the
    # vblank and THEN blits it, so the tilemap the emulator hands back can be
    # one tick behind the state -- the same one-vblank relationship the shadow
    # OAM has had since P3.  The slack is in the phase, never in the value: a
    # HUD fed by a counter of its own is out by far more than one, immediately.
    check(f0 is not None and abs(f0 - a["fuel"]) <= 1,
          "the HUD's FUEL reads the ship's own tank (%r against %d)"
          % (f0, a["fuel"]))

    g.run(20, "U")                      # 20 ticks of held thrust
    b = g.ship()
    f1 = g.hud_num(HUD_FUEL_ROW, HUD_FUEL_COL, HUD_FUEL_W)
    check(b["fuel"] == a["fuel"] - FUEL_BURN * 20,
          "20 ticks of held UP burn %d fuel (%d -> %d)"
          % (FUEL_BURN * 20, a["fuel"], b["fuel"]))
    check(f1 is not None and f0 is not None and f1 < f0,
          "and the fuel digits on the screen change as it burns (%r -> %r)"
          % (f0, f1))
    check(f1 is not None and abs(f1 - b["fuel"]) <= 1,
          "and still read the tank they are showing (%r against %d)"
          % (f1, b["fuel"]))

    # ---- ALT tracks the ship ---------------------------------------------
    # The altitude on screen, against the gap between the ship's underside and
    # the surface the ROM's OWN terrain table puts under it.  A HUD that showed
    # the height above the SPAWN, or a depth fallen, is a number that moves with
    # the ship too, and only this comparison tells the two apart.
    # As of P9 `terrain` is the selected profile POINTER, so this dereferences
    # like p2_terrain and p5_landing do.  Reading WORLD_COLS bytes AT the symbol
    # hands back the pointer's own two bytes plus whatever follows, which is a
    # plausible list of small numbers -- the check fails with a nonsense
    # altitude that reads as a physics bug rather than as a missed dereference.
    col = ((b["x"] + SHIP_W // 2) >> 3) % WORLD_COLS
    want = g.active_profile()[col] * 8 - (b["y"] + SHIP_H)
    alt = g.hud_num(HUD_ALT_ROW, HUD_ALT_COL, HUD_ALT_W)
    check(alt is not None and abs(alt - want) <= 1,
          "and ALT is the height of the ship's underside over the ground beneath "
          "it (%r against %d px, column %d)" % (alt, want, col))

    # ---- the state machine's outcome line ---------------------------------
    # Where the verdict lands.  A loop that stopped rebuilding the HUD once the
    # ship stopped flying would leave the last live numbers frozen on the
    # screen forever, and nothing else in the harness would say so: this is the
    # one place the outcome has to reach the tilemap.
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DROP_LIMIT:
        g.run(1)                        # no hand on the stick: a hard drop
        ticks += 1
    # Two ticks of slack and no more: the loop leaves the moment the state
    # changes, and the HUD that reports it is built and blitted on the ticks
    # that follow -- the same one-vblank lag the numbers above are allowed.
    g.run(2)
    s = g.ship()
    check(s["state"] == ST_CRASH and bool(g.find_text("CRASHED")),
          "a hard drop ends the life, and the HUD says so (state %d after %d "
          "ticks, %r)" % (s["state"], ticks, g.find_text("CRASHED")))

    # ---- a restart over a crashed life ------------------------------------
    # Where a HUD that wrote only the tiles it needed would leave its tracks.
    # "CRASHED" is seven tiles and the velocity row it replaces is thirteen,
    # with a blank at column 6 that no reading ever writes -- so if that row
    # were not cleared first, the 'D' of the old verdict would still be sitting
    # in the middle of the new one.  Asserted as the WHOLE row against the
    # layout, because a leftover tile is exactly the sort of thing that no
    # string search finds and every screenshot shows.
    g.run(8, "S")                       # START restarts the life
    g.run(2)
    bad = []
    for x, c in enumerate(HUD_VEL_ROW):
        t = g.tile(x, HUD_VERDICT_ROW)
        if c == "d":
            if not T_DIGIT0 <= t < T_DIGIT0 + 10:
                bad.append((x, "a digit", t))
        elif t != glyph(c):
            bad.append((x, c, t))
    check(g.ship()["state"] == ST_FLY and not bad,
          "and START over a crashed life puts the velocity row back exactly as "
          "the layout says -- nothing left over from the verdict (%r)" % (bad[:4],))

    # ---- the other ending, which is the one that shows a SCORE ------------
    # The descent burns whenever the ship is falling faster than VY_HOLD, the
    # same pilot p5_landing flies.  What this reads is the digit the HUD
    # decoded, against the multiplier the ROM's own pads table gives the column
    # the ship landed on.
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1, "U" if g.ship()["vy"] > VY_HOLD else "")
        ticks += 1
    g.run(2)
    s = g.ship()
    shown = g.hud_num(HUD_VERDICT_ROW, HUD_VERDICT_COL, 1)
    check(s["state"] == ST_LANDED and bool(g.find_text("LANDED X")) and
          shown == s["mult"] == 2,
          "and a controlled descent lands and the HUD scores it -- state %d "
          "after %d ticks, showing %r, scored %d, %r"
          % (s["state"], ticks, shown, s["mult"], g.find_text("LANDED X")))

    # ---- the frame keeps its rate ----------------------------------------
    # The tick loop draws now -- a 40-tile HUD blitted on every iteration
    # against P5's nothing -- and this is where a build that no longer fits the
    # frame shows up: the loop would miss a vblank, one iteration would stop
    # being one tick, and every number above would agree with the physics while
    # running at half speed.  (The 20x18 field write is NOT in this loop: it
    # happens once, at the hand-over, and costs about three frames there.)
    n0 = g.u16("frame")
    g.run(FRAMES)
    check(g.u16("frame") - n0 == FRAMES,
          "the HUD-heavy loop is still one tick per emulated frame (%d frames "
          "-> +%d)" % (FRAMES, g.u16("frame") - n0))


# ------------------------------------------------------------------ P7 -----
def p7_sound(g):
    """The APU is powered on, and the thrust is a level the ROM turns up and
    back down again.

    NOTHING HERE CLAIMS ANY SOUND IS AUDIBLE, AND NONE OF IT COULD: this runs
    with window="null" and never opens an audio device, and no assertion below
    listens to a sample.  sound_emulated=True is on so that PyBoy IMPLEMENTS
    the APU registers at all (with it off they read 0x00 forever -- see the
    Game constructor); it buys readable registers, not ears.  What is asserted
    is only that the ROM WROTE the registers the APU reads, and wrote them in
    the shape the phase asks for.  Whether the three sounds actually come out
    of a speaker is owed to ears -- real hardware, or an emulator with audio
    switched on -- and is UNVERIFIED by this check and by every other one in
    this file.

    That is still worth asserting, because the failure it covers is silent in
    both senses.  GBDK's crt0 powers the APU DOWN, so at main() entry NR52 bit
    7 is CLEAR and every sound-register write reads back zero and vanishes --
    a ROM with three perfectly-shaped envelope writes and no boot line plays
    nothing, and no screenshot, no tilemap and no state byte says so.  Reading
    the register back is the only thing that can tell those two ROMs apart.

    The register is the RIGHT thing to read even though the sound is not
    emulated: 0xFF26/0xFF24/0xFF25/0xFF17 are ordinary memory to PyBoy, so what
    comes back is exactly what the ROM wrote.
    """
    print("P7 sound")
    g.run(150)                          # let main() run its boot

    # ---- the boot --------------------------------------------------------
    # Bit 7 SET means the ROM wrote NR52 = 0x80.  On the previous phase's ROM
    # this reads 0x70 -- bit 7 clear, all four channels off -- and that is the
    # whole of the power gate.
    apu = g.p.memory[NR52]
    check(apu & APU_ON == APU_ON,
          "the APU is powered on by the boot (NR52 0x%02X, bit 7 %s)"
          % (apu, "set" if apu & APU_ON else "CLEAR"))

    # ...and the routing went with it.  Powering the APU on RESETS NR50/NR51,
    # so a boot that set NR52 alone would be a powered APU with every channel
    # routed nowhere -- the same silence by another route, and this is the only
    # assertion that can tell the two apart.
    nr50, nr51 = g.p.memory[NR50], g.p.memory[NR51]
    check(nr50 == NR50_BOOT and nr51 == NR51_BOOT,
          "and the routing is set alongside it, which powering on resets -- "
          "full volume, all four channels to both outputs (NR50 0x%02X, "
          "NR51 0x%02X)" % (nr50, nr51))

    # ---- the thrust, which is a LEVEL ------------------------------------
    # Past the title, onto the field: the play branch is the only place the
    # sound functions are called from, so nothing has touched CH1 before this.
    g.play()

    idle = g.p.memory[NR12]
    check(idle >> 4 == 0,
          "CH1 is silent before the burn -- volume 0, nothing latched from "
          "the title or the boot (NR12 0x%02X, volume %d)" % (idle, idle >> 4))

    # One held frame.  run() presses the button, ticks once and releases it, so
    # the tick in between is a tick with UP down -- and the volume nibble of
    # NR12 is the engine: non-zero exactly when the ROM decided this tick
    # burned.
    g.run(1, "U")
    loud = g.p.memory[NR12]
    check(loud >> 4 != 0,
          "and a thrust tick turns it up (NR12 0x%02X, volume %d)"
          % (loud, loud >> 4))

    # ...and the channel came ON, which is the only READABLE trace the trigger
    # bit leaves.  The trigger is bit 7 of the high frequency register (NR14
    # here) and it is WRITE-ONLY -- it cannot be read back -- but a trigger is
    # what sets the channel's enable bit in NR52, and writing the envelope
    # alone never does.  So this is the assertion that fails if the 0x80 ever
    # comes off NR14, which is the phase's named trap: without it a repeat hit
    # only rewrites a running channel and the second sound is inaudible.
    check(g.p.memory[NR52] & 0x01 == 0x01,
          "and it came ON, so the high frequency register's trigger bit was "
          "really written -- NR14's bit 7 is write-only, and a trigger is what "
          "sets CH1's enable bit in NR52 (NR52 0x%02X)"
          % g.p.memory[NR52])

    # Released.  The thrust is re-armed every tick it lasts, so this is the
    # tick the re-arming stops: the ROM writes the channel down to volume 0.
    # Asserted as the VOLUME nibble and not as the whole byte on purpose: the
    # value that is correct here is 0x08, which keeps the DAC bit set and so
    # silences the channel rather than switching it off.  A byte-equality
    # check would have demanded 0x00, which is the switch-off this design
    # avoids.
    g.run(2)
    back = g.p.memory[NR12]
    check(back >> 4 == 0,
          "releasing the button returns it to zero -- the thrust is a level, "
          "not a latch (NR12 0x%02X, volume %d)" % (back, back >> 4))

    # ---- the two events, which write a channel ONCE ----------------------
    # The other two thirds of the deliverable, and they need no stop: each is
    # one written set of registers with a decreasing envelope, nothing writes
    # the channel again, and so the register keeps what the event left in it.
    # Read off CH4 and CH2 respectively -- the channels main.c assigns them,
    # so a crash wired to CH2 fails here.
    ticks = 0
    while g.ship()["state"] != ST_CRASH and ticks < DROP_LIMIT:
        g.run(1)                        # no hand on the stick: a hard drop
        ticks += 1
    crash = g.p.memory[NR42]
    check(g.ship()["state"] == ST_CRASH and crash >> 4 != 0,
          "and a hard drop writes CH4, on the tick the crash is classified "
          "(state %d after %d ticks, NR42 0x%02X, volume %d)"
          % (g.ship()["state"], ticks, crash, crash >> 4))

    # The same scripted descent p5_landing flies, for the same reason: the
    # spawn is over a pad, so a hand on the stick is the whole difference.
    g.run(8, "S")                       # START restarts the life
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1, "U" if g.ship()["vy"] > VY_HOLD else "")
        ticks += 1
    land = g.p.memory[NR22]
    check(g.ship()["state"] == ST_LANDED and land >> 4 != 0,
          "and a controlled descent writes CH2, on the tick it lands (state "
          "%d after %d ticks, NR22 0x%02X, volume %d)"
          % (g.ship()["state"], ticks, land, land >> 4))


# ------------------------------------------------------------------ P9 -----
def p9_window(g):
    """The visible rows are a WINDOW on the profile, not the profile's first
    rows -- and they come from the ACTIVE profile, through the one symbol both
    the renderer and sim.h's collision read.

    Every assertion here is about the OFFSET.  At window row 0 the arithmetic
    is the identity, so a blit that ignored the offset entirely would pass a
    check written that way; DESCENT_ROW0 is nonzero and every one of the
    descent's columns has its surface below the bottom of the screen at row 0,
    which is asserted at the end as the reason the offset has to exist.
    """
    print("P9 window")
    # A symbol this phase introduces being ABSENT is an assertion failure, not
    # a harness error: that is the power gate on the P8 ROM, and it answers 1.
    if not g.need("terrain", "terrain_lander", "terrain_descent"):
        return

    lander = g.profile("terrain_lander")
    descent = g.profile("terrain_descent")

    check(lander != descent and len(lander) == len(descent) == WORLD_COLS,
          "the two profiles are distinct from each other -- %r against %r"
          % (lander, descent))
    check(max(descent) > MAP_TILES > max(lander),
          "and the DESCENT profile is deeper than one BG map -- %d tiles "
          "against the map's %d, where LANDER's deepest is %d and fits on one "
          "screen" % (max(descent), MAP_TILES, max(lander)))

    g.run(150)
    g.run(4, "T")           # SELECT: flip the title to DESCENT (an EDGE)
    g.run(2)                # button-free: the next press is an EDGE
    check(g.var("pick") == 1,
          "the title selected the DESCENT half (pick %d)" % g.var("pick"))
    g.run(8, "S")           # START clears the title, hands the field over
    g.run(2)

    check(g.u16("terrain") == g.addr["terrain_descent"]
          and g.active_profile() == descent,
          "and the one `terrain` symbol points at the DESCENT profile "
          "(terrain -> 0x%04X, terrain_descent at 0x%04X)"
          % (g.u16("terrain"), g.addr["terrain_descent"]))

    # Column by column: the surface tile is where the OFFSET puts it.
    bad = []
    for x in range(WORLD_COLS):
        y = descent[x] - DESCENT_ROW0
        got = g.tile(x, y) if 0 <= y < VIEW_H else None
        if got != T_TERRAIN_TOP:
            bad.append((x, descent[x], y, got))
    check(not bad,
          "every column's surface tile is at terrain_descent[col] - %d -- "
          "col:profile-row:screen-row:found %r" % (DESCENT_ROW0, bad[:5]))

    # ...and the rest of the window is sky above it and body below it, so a
    # blit that painted the surface and left the buffer alone fails too.
    bad = []
    for x in range(WORLD_COLS):
        for y in range(HUD_H, VIEW_H):
            wr = DESCENT_ROW0 + y
            want = (T_BLANK if wr < descent[x] else
                    T_TERRAIN_TOP if wr == descent[x] else T_TERRAIN)
            if g.tile(x, y) != want:
                bad.append((x, y, want, g.tile(x, y)))
    check(not bad,
          "the whole window is sky/surface/body exactly as the profile and the "
          "offset say -- col:row:want:found %r" % (bad[:5]))

    # The offset is not decoration: at row 0 the descent shows no ground at all.
    off0 = [x for x in range(WORLD_COLS) if 0 <= descent[x] < VIEW_H]
    check(DESCENT_ROW0 > 0 and not off0,
          "and it is the offset that shows it -- at row 0 the descent's surface "
          "would be off the bottom of the screen in all %d columns (%d would "
          "show it), so a blit that ignored %d would draw %d rows of sky"
          % (WORLD_COLS, len(off0), DESCENT_ROW0, VIEW_H))


CHECKS = [("p1_boot", p1_boot), ("p2_terrain", p2_terrain),
          ("p3_gravity", p3_gravity), ("p4_thrust", p4_thrust),
          ("p5_landing", p5_landing), ("p6_hud", p6_hud),
          ("p7_sound", p7_sound), ("p9_window", p9_window)]


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
