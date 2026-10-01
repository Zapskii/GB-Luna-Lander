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
WIN0 = 0x9C00                   # the WINDOW tilemap, the second 32x32 map
MAP_W = MAP_H = 32
VIEW_W, VIEW_H = 20, 18         # what SCX/SCY = 0 puts on the screen
LCDC = 0xFF40
LCDC_ON = 0x80                  # bit 7: the display.  While it is set the PPU
                                # locks VRAM, which is the whole of p1_boot's
                                # second assertion.
SCY = 0xFF42                    # the BG's vertical scroll: what main.c's
                                # camera writes, and the ONE register this
                                # phase is about.  Read in VBlank by the PPU as
                                # it draws, so a mid-frame write tears the frame
                                # -- which PyBoy will not show and no tilemap
                                # read can catch, so the check below is about
                                # the VALUE, not about where the write sits.
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
T_STAR0, STAR_TILES = 3, 4      # mkgfx.py's star tiles, in the id gap
T_DIGIT0, T_LETTER0, T_MINUS = 20, 30, 56

# THE SKY IS A SET, NOT A TILE.  A cell above the surface is T_BLANK or one of
# the four star tiles, and WHICH one is tools/mklevel.py's star_field[], indexed
# by world row.  That is a pattern and not a rule, so these checks assert the
# CATEGORY -- a sky cell is always a sky tile and never terrain -- and leave the
# exact scatter to mklevel.py's own self-check.  Restating the generator's LCG
# here would buy nothing and be a second copy of it to keep in step.
#
# What the probe does add is the COUNT: that the stars are really on the screen
# and not merely in the header.  A floor and not the exact 29, because the
# scatter is the generator's to change -- the number this has to stay clear of
# is 0, which is what a ROM with no starfield has.
STAR_IDS = frozenset(range(T_STAR0, T_STAR0 + STAR_TILES))
SKY_IDS = frozenset({T_BLANK}) | STAR_IDS
MIN_STARS = 8

# terrain.h's geometry, mirrored for the same reason: tools/mklevel.py,
# terrain.h and this file are the second three-way contract.  A probe that read
# terrain.h could not tell a generator that gives the x2 pad the x1 row from one
# that gives it the right one.
#
# WORLD_COLS is 160 px / 8 px per tile.  NOT a power of two -- 160 is not 256 --
# which is why the wrap in sim.h is two compares and never an & WORLD_MASK.
WORLD_COLS = 20
PAD_COUNT = 2
PAD_ROW = {1: 15, 2: 12}        # multiplier -> the surface row that pad sits at,
                                # for the LANDER profile p2_terrain runs against

# P9's number, mirrored for the same reason the tile ids are.  MAP_TILES is one
# BG map (32x32), which was the bound a profile that did not fit had to be
# blitted around -- and is, as of P11, the SIZE OF THE RING: the map row a world
# row goes in is its own index modulo this, which is what lets a 101-row profile
# live on a 32-row map at all.
#
# P9's DESCENT_ROW0 -- the fixed profile row the window's top edge sat on -- is
# gone with P9's hand-wound window.  The offset is the CAMERA's now, so a mirror
# of it here would be a second answer to a question the ROM already answers, and
# the one thing a probe must not do is read its expectations out of the thing it
# is checking.  It is read from `cam` in the checks that need it.
MAP_TILES = 32

# P10's camera, mirrored for the same reason.  VIEW_H_PX is sim.h's SCREEN_H_PX
# -- the panel is 144 px -- and CAM_ANCHOR is how far up the screen the camera
# holds the ship, a third of it.  What the bottom clamp SUBTRACTS is not the
# panel but PLAY_H_PX, the band above P12's status bar; see the block below.
# `world_h` is NOT mirrored here: it is read out of the ROM's own map, because
# the point of that symbol is that main.c derives it from the profile rather
# than from a constant somebody could forget to change.
VIEW_H_PX = VIEW_H * 8
CAM_ANCHOR = VIEW_H_PX // 3

# P12's STATUS BAR, and the visible height it costs the world.  The panel is
# 144 px and the telemetry is the WINDOW layer's now: the window runs to the
# bottom-right corner from WY, so its two rows COVER the last two rows of
# background and the player sees PLAY_H_PX of world.  sim.h's camera clamps on
# THAT and not on the panel -- a clamp two rows too generous leaves the ground at
# the end of a descent scrolled under the bar and never seen.
#
# Mirrored here rather than derived from the ROM for the same reason the tile
# ids are: a probe that asked the ROM what its own camera bounds were could not
# tell a camera clamped on the wrong one from a correct one.
HUD_H = 2                       # the rows the status bar owns, at the BOTTOM
PLAY_H = VIEW_H - HUD_H
PLAY_H_PX = PLAY_H * 8
HUD_BAR0, HUD_BAR1 = PLAY_H * 8, PLAY_H * 8 + 8        # those rows, in SCREEN px

# main.c's screen state and its HUD layout, mirrored for the same reason the
# tile ids are.  Where a number SITS is part of the HUD, not a detail of it: a
# HUD that drew the right tank in the wrong row of the map is a bug, and this is
# the file that has to be able to see it, so the layout is written down here
# rather than derived from the ROM.
#
# THE ROWS ARE WINDOW ROWS as of P12: HUD_ROW 0 is the window's first row, which
# is screen row PLAY_H.  Every read below therefore goes through the WINDOW map
# and not the BG one -- the same tile id at the same (x, y) means two different
# things in the two maps, which is exactly the confusion this phase is about.
ST_TITLE, ST_PLAY = 0, 1
HUD_FUEL_ROW, HUD_FUEL_COL, HUD_FUEL_W = 0, 5, 3
HUD_ALT_ROW, HUD_ALT_COL, HUD_ALT_W = 0, 13, 3
# The target-pad indicator, on the velocity row: "PAD X" then the multiplier
# sim.h's pad_mult() gives the column under the ship, one digit wide.
HUD_PAD_ROW, HUD_PAD_COL, HUD_PAD_W = 1, 19, 1
# Where the verdict lands in the strip once the life is over: the row the
# velocities are on, which is the row the outcome replaces.
HUD_VERDICT_ROW, HUD_VERDICT_COL = 1, 8
# That whole row, tile by tile, as the layout main.c writes it: 'd' is a digit
# and every other character is the tile the layout puts there.  Written out
# because the row is what a leftover from the last verdict shows up in, and a
# leftover is invisible to a string search -- see the check below.
HUD_VEL_ROW = "VX ddd VY ddd " + "PAD Xd"

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

# The descent speed the soft-landing pilot burns above, in 8.8 px/frame.  Well
# under sim.h's SAFE_VY_MAX, because a pilot that flew the edge of the
# threshold would make this check a statement about the pilot and not the game.
VY_HOLD = 32

# sim.h's gravity and thrust knobs, mirrored.  P5 retunes the feel and WILL
# move these; the identities below -- the exact integrals and the exact
# fuel burn -- are what have to keep holding when it does.
GRAV = 8
THRUST = 32

# The pilot's brake rule divides by the NET deceleration, so it is derived here
# and not written as a literal.  It WAS a literal -- 8192, which is
# 2 * (THRUST - GRAV) * 256 at the old GRAV 16 -- and halving GRAV left it
# silently describing a brake the ship no longer has, which shows up as a pilot
# that brakes too late and a check that fails for a reason that is not the game.
# The 2 is the integral; the 256 converts the 8.8 velocity to px.
BRAKE_DIV = 2 * (THRUST - GRAV) * 256

# How long each half of the check may take before it gives up and FAILS.  A
# stuck ROM has to answer 1, not hang the harness into a timeout, which would
# answer 2 and look like a broken probe rather than a broken game.
#
# A CEILING, and deliberately loose.  The loops below leave on the tick the
# state changes and a drop still in flight at the end fails the state check under
# it, so surplus costs ticks and never buys a false pass.  It is scaled by GRAV
# because the longest journey in this file is p6_hud's: it burns 20 ticks of held
# thrust BEFORE it lets go, so the ship releases already climbing at
# (THRUST-GRAV) a tick and coasts to its apex (THRUST-GRAV)*20/GRAV ticks later
# before it falls the whole way back past the spawn to the ground.
# The flat 120 that used to sit here was a GRAV-16 measurement of a shorter
# fall, and it did not survive halving the knob.
DROP_LIMIT = 200 + 2 * (THRUST - GRAV) * 20 // GRAV
DESCENT_LIMIT = 1500            # the scripted descent takes about 300

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

# sim.h's sideways thruster, mirrored for the same reason as the knobs above.
# STRAFE is what a held d-pad direction adds to vx each tick and DRAG is what
# letting go takes back out of it; both are asserted here as IDENTITIES, so a
# retune of either follows in the check's arithmetic instead of failing as a
# complaint about the game.  LEAN_STEPS is the nose's tilt while a direction is
# held -- not a step the stick took, a lean it is holding.
STRAFE = 16
DRAG = 16
LEAN_STEPS = 2

# gfx.h's crash burst and main.c's clock for it, mirrored for the same reason as
# the tile ids: SPR_BOOM0 is the burst's first sprite tile, BOOM_TILES is how
# many tiles make one 16x16 frame (a 2x2 of 8x8 quadrants), BOOM_STEPS is how
# many frames it has and BOOM_HOLD how many ticks each one is held.  The tiles
# are asserted here as the exact four a frame owns, so a burst drawn from the
# wrong base or in the wrong quadrant order fails rather than merely looking off.
SPR_BOOM0 = 16
BOOM_TILES = 4
BOOM_STEPS = 4
BOOM_HOLD = 4
BOOM_TICKS = BOOM_STEPS * BOOM_HOLD
BOOM_PX = 16

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

# --- P13: the DESCENT suite's own numbers -----------------------------------
#
# THE BRAKE-LATE PILOT, and why P5's pilot cannot fly this world.  LANDER's
# air is 96 px (12 blank rows above the surface at GRAV 8; it was 72 at GRAV 16)
# and VY_HOLD (a quarter of SAFE_VY_MAX) walks down it in ~300 ticks.  The
# DESCENT world is 752 px of air over a 600 unit tank: a hold at
# 0.125 px/frame needs ~4800 ticks and ~2400 units of fuel, so the slow pilot
# runs dry two thirds of the way down and free-falls the rest.  The mode's own
# numbers therefore ask for a DIFFERENT shape -- fall hard, brake late -- and
# the check has to fly that shape, or it could not reach the ending it is here
# for.
#
# The rule: burn while the height left is within P13_BRAKE times the distance a
# full stop would take.  Thrust against gravity is a net (THRUST - GRAV)/256
# px/frame^2, so a full stop from vy covers vy^2 / (2 * (THRUST - GRAV) * 256)
# px -- which is BRAKE_DIV above, and it is derived rather than written down for
# the reason given there.  FOUR, and not one:
# at exactly the stopping distance the pilot arrives at zero, and at four it
# arrives at about 48/256 px/frame against sim.h's 128 threshold.  A margin is
# what keeps this a check on the GAME: a pilot tuned to the threshold would be
# asserting about itself, and one that braked too late would be asserting that
# the ship CAN fall 752 px on 600 units, which it can only just.
#
# Calibrated against the ROM and reported by the check: the landing is asserted
# to arrive under SAFE_VY_MAX and with fuel in the tank, so a retune of GRAV,
# THRUST or FUEL_START that made the descent unaffordable fails here.
P13_BRAKE = 4

# The two bounded flights.  Named separately and kept tight -- PyBoy runs the
# ROM a frame at a time and the DESCENT loop costs about two of them per
# iteration (see p10_camera), so an unbounded script here is minutes of
# wall-clock and a stuck ROM has to FAIL rather than be timed out into a
# harness error.
P13_LAND_LIMIT = 900            # the braking descent takes ~650 frames
P13_WRAP_LIMIT = 400            # the sideways flight reaches the ground ~200

# The tile column count the world wraps in -- sim.h's WORLD_W in px, mirrored
# here for the same reason the tile ids are: a probe that asked the ROM where
# its own world ended could not tell a wrap at 160 from one at 256.
WORLD_W_PX = WORLD_COLS * 8


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


def rate_ok(frames, advanced):
    """Did the ROM keep ONE TICK PER EMULATED FRAME over `frames` frames?

    The one-iteration slack is the seam of the measurement and not a licence:
    the window opens and closes on the EMULATOR's frame boundaries while the
    counter is the ROM's own main-loop variable, so an iteration that starts
    before the first frame or ends after the last is clipped by the edge -- and
    a free fall's heaviest tick (the camera moving two tile rows and the ring
    writing two) measured exactly one such over 126.  One frame of slack in a
    measurement that runs to hundreds of frames, against a mode that was 147
    short over 484 before this phase fixed it."""
    return frames - 1 <= advanced <= frames


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

    def tile(self, x, y, base=MAP0):
        """One tile id out of a tilemap.  WHICH map is a parameter and not a
        constant as of P12: the BG map holds terrain and the WINDOW map holds
        the status bar, and the same (x, y) means two different things in the
        two.  Reading the HUD out of the BG map is the exact confusion this
        phase exists to settle, so the map is always named at the call."""
        return self.p.memory[base + y * MAP_W + x]

    def find_text(self, s, base=MAP0):
        """Every (row, col) where the tilemap spells `s`, through this file's
        own copy of the font ids.  An empty list is "the string is not on the
        screen", which is what a title that was never drawn answers."""
        want = [glyph(c) for c in s]
        hits = []
        for y in range(VIEW_H):
            row = [self.tile(x, y, base) for x in range(MAP_W)]
            for x in range(MAP_W - len(want) + 1):
                if row[x:x + len(want)] == want:
                    hits.append((y, x))
        return hits

    def hud_num(self, row, col, w, base=WIN0):
        """The number in the `w` digit tiles at (col,row) of a tilemap, or None
        if they are not all digits -- a blank, a letter or a tile from an
        unloaded bank.  Read off the TILEMAP rather than out of main.c's `bg`,
        which is the whole point: it is what the PPU was told, after the tile
        ids went through the font.  The HUD's own map is the WINDOW's as of
        P12, so that is the default."""
        v = 0
        for i in range(w):
            t = self.tile(col + i, row, base)
            if not T_DIGIT0 <= t < T_DIGIT0 + 10:
                return None
            v = v * 10 + (t - T_DIGIT0)
        return v

    def scanline(self, row):
        """One row of the FRAMEBUFFER, as a list of RGBA tuples.

        The only reader here that asks what the PPU DREW rather than what it was
        told to draw, and P12 needs it because the defect is precisely a
        disagreement between the two: `tile()` addresses MAP coordinates, and
        "the status bar's two rows are the top of the screen" is a claim about
        SCREEN coordinates that no tilemap read can make.  PyBoy hands back the
        finished 160x144 image, so this is the player's view.
        """
        return [tuple(int(v) for v in px) for px in self.p.screen.ndarray[row]]

    def pixels(self, row, x0, x1):
        """The bytes of a horizontal SLICE of a framebuffer row, for comparing
        one frame's bar against another's."""
        return bytes(bytearray(self.p.screen.ndarray[row, x0:x1].reshape(-1)))

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
    # The WHOLE of the BG map's visible rows, and it is the whole of them as of
    # P12: P6's HUD was two rows of BG MAP over the top of this, so the region
    # read had to stop below them or it would have been describing the HUD and
    # not the terrain.  The telemetry is the WINDOW layer's now and the BG map is
    # terrain from row 0 down, so the skip is gone with the reason for it.
    seen = set()
    ground = 0
    stars = 0
    for y in range(VIEW_H):
        for x in range(VIEW_W):
            t = g.tile(x, y)
            seen.add(t)
            if t in (T_TERRAIN, T_TERRAIN_TOP):
                ground += 1
            elif t in STAR_IDS:
                stars += 1
    extra = sorted(seen - SKY_IDS - {T_TERRAIN, T_TERRAIN_TOP})
    check(not extra,
          "the first screen holds only generated tiles -- nothing from an "
          "unloaded bank (%r is on screen)" % extra)
    check(ground >= VIEW_W,
          "and the generated ground is really drawn (%d of %d cells, at least "
          "one surface tile per column)" % (ground, VIEW_W * VIEW_H))
    check(stars >= MIN_STARS,
          "and the sky above it is NOT empty -- %d star cells on the first "
          "screen, against the %d floor a screen with no starfield at all "
          "would miss by every one.  The ship is the only thing in that sky "
          "that moves, so a blank one is a fall with nothing to measure it "
          "against: at a steady few px a frame it reads as hovering"
          % (stars, MIN_STARS))


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

    # ...and the rest of the column follows from it: sky above, body below.  The
    # WHOLE column as of P12 -- P6's HUD used to sit over the top two rows of
    # every column and the loop had to start below it, and the telemetry is the
    # WINDOW layer's now, so the BG map is terrain the whole way down and there
    # is nothing left for the skip to be protecting.
    bad = []
    for x in range(WORLD_COLS):
        for y in range(VIEW_H):
            t = g.tile(x, y)
            # SKY is a category and not one tile now -- see SKY_IDS.  Surface
            # and body are still exact: those two are the profile's answer.
            ok = (t in SKY_IDS if y < h[x] else
                  t == T_TERRAIN_TOP if y == h[x] else t == T_TERRAIN)
            if not ok:
                bad.append((x, y, "sky" if y < h[x] else h[x], t))
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
    g.run(k, "A")
    b = g.ship()
    check(b["fuel"] == a["fuel"] - FUEL_BURN * k,
          "holding A burns exactly %d fuel per tick (%d -> %d over %d ticks)"
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

    # ---- and B is the same button -----------------------------------------
    # Both face buttons thrust.  That is one OR in main.c's decode and the only
    # line of it a probe press can see directly, so it is asserted against A's
    # own numbers over the same span: a B left inert, or left wired to a
    # rotation step that has since moved out from under it, fails here -- and
    # it fails as the heading changing, which is not a thrust bug at all.
    e0 = g.ship()
    g.run(k, "B")
    e1 = g.ship()
    check(e1["fuel"] == e0["fuel"] - FUEL_BURN * k and
          e1["vy"] - e0["vy"] == (GRAV - THRUST) * k,
          "and B thrusts identically -- the same %d fuel burnt and the same "
          "reversal (%d -> %d fuel, vy %d -> %d)"
          % (FUEL_BURN * k, e0["fuel"], e1["fuel"], e0["vy"], e1["vy"]))
    check(e1["heading"] == e0["heading"],
          "and neither face button turns the ship any more (heading %d)"
          % e1["heading"])

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
        g.run(1, "A")
        spent += 1
    e = g.ship()
    if not check(e["fuel"] == 0,
                 "holding A empties the tank (%d of %d fuel left after %d "
                 "ticks)" % (e["fuel"], FUEL_START, spent)):
        return
    check(spent == (f0 + FUEL_BURN - 1) // FUEL_BURN,
          "and it takes exactly the fuel it held: %d units at %d per tick is "
          "%d ticks (took %d)" % (f0, FUEL_BURN,
                                  (f0 + FUEL_BURN - 1) // FUEL_BURN, spent))

    # ---- empty: the button is inert ---------------------------------------
    # The other half of the target.  With the tank dry, holding A changes the
    # trajectory by NOTHING at all -- vy falls by gravity alone and vx does not
    # move -- so the ship is committed to its descent.
    f = g.ship()
    g.run(k, "A")
    h = g.ship()
    check(h["vy"] - f["vy"] == GRAV * k and h["vx"] == f["vx"] and h["fuel"] == 0,
          "an empty tank makes thrust inert -- %d ticks of held A change vy "
          "by exactly GRAV * %d == %d and leave vx at %d (vy %d -> %d)"
          % (k, k, GRAV * k, f["vx"], f["vy"], h["vy"]))

    # ---- the stick: a held lean, a sideways push, and friction ------------
    # A FRESH LIFE FIRST, and it is not tidiness: the tank above is dry, and the
    # sideways thruster is under exactly the same fuel gate as the engine -- so
    # a strafe flown here would be a check on the gate, and would pass on a ROM
    # whose sideways push did not exist at all.  START, and the ship is back
    # above the pad with a full tank.
    g.run(8, "S")
    g.run(2)
    h0 = g.ship()
    check(h0["heading"] == 0 and h0["fuel"] == FUEL_START and
          h0["state"] == ST_FLY,
          "START seats a fresh ship, upright and fuelled (heading %d, fuel %d, "
          "state %d)" % (h0["heading"], h0["fuel"], h0["state"]))

    # HELD, not an EDGE, and that is the whole difference from the stick this
    # replaces: the nose LEANS into the push and stays leaning for as long as
    # the direction is down.  The fuel is counted in the same breath because the
    # sideways thruster burns at the engine's own rate -- sideways motion is not
    # free, or the tank stops being the whole clock.
    g.run(2, "R")
    h1 = g.ship()
    check(h1["heading"] == LEAN_STEPS and h1["fuel"] == h0["fuel"] - 2 * FUEL_BURN,
          "held RIGHT leans the nose to %d and holds it there, at %d unit a "
          "tick like the engine (heading %d, fuel %d -> %d)"
          % (LEAN_STEPS, FUEL_BURN, h1["heading"], h0["fuel"], h1["fuel"]))

    # One vblank of slack, and no more: set_sprite_tile writes GBDK's SHADOW
    # OAM, which only reaches the PPU's 0xFE00 on the next vblank.  The slack
    # is in the phase, never in the value -- a ship drawn on frame 0 whatever
    # its heading fails here.
    g.run(3, "R")
    check(g.oam()[2] == SPR_SHIP0 + LEAN_STEPS,
          "and the sprite leans with it (heading %d draws tile 0x%02X, expected "
          "0x%02X)" % (LEAN_STEPS, g.oam()[2], SPR_SHIP0 + LEAN_STEPS))

    # ACCELERATION, and both axes at once on purpose: vx climbs by exactly
    # STRAFE a tick -- no gravity term leaking into the sideways axis -- and vy
    # falls by exactly GRAV a tick, which is what makes this a sideways PUSH
    # rather than a second way of holding the ship up.
    a = g.ship()
    g.run(k, "R")
    b = g.ship()
    check(b["vx"] - a["vx"] == STRAFE * k and b["vy"] - a["vy"] == GRAV * k,
          "held RIGHT accelerates sideways at exactly STRAFE a tick and leaves "
          "the vertical to gravity -- %d ticks add %d to vx and %d to vy "
          "(vx %d -> %d, vy %d -> %d)"
          % (k, STRAFE * k, GRAV * k, a["vx"], b["vx"], a["vy"], b["vy"]))

    # FRICTION, and the release in the same breath: letting go takes DRAG back
    # out of vx a tick AND stands the nose up on that very tick.  "The icon
    # returns to upright" is the heading, and that is the half of it a state
    # read can prove.
    c = g.ship()
    g.run(k)
    d = g.ship()
    check(c["vx"] - d["vx"] == DRAG * k and d["heading"] == 0,
          "and letting go takes exactly DRAG a tick back out and stands the nose "
          "up on the same tick (vx %d -> %d, heading %d)"
          % (c["vx"], d["vx"], d["heading"]))
    g.run(3)
    check(g.oam()[2] == SPR_SHIP0,
          "which the sprite follows back to the upright frame (tile 0x%02X, "
          "expected 0x%02X)" % (g.oam()[2], SPR_SHIP0))

    # LEFT is the same thruster the other way, and its lean is the FAR END of
    # the heading table rather than a negative index: the frame drawn is
    # SPR_SHIP0 + heading, so an index of -2 would draw the tile two before the
    # ship's block -- the terrain, not a ship.
    a = g.ship()
    g.run(k, "L")
    b = g.ship()
    check(b["vx"] - a["vx"] == -STRAFE * k and
          b["heading"] == ROT_STEPS - LEAN_STEPS,
          "LEFT mirrors it -- %d ticks at -STRAFE a tick and the nose off the "
          "far end of the table (vx %d -> %d, heading %d, expected %d)"
          % (k, a["vx"], b["vx"], b["heading"], ROT_STEPS - LEAN_STEPS))

    # And it comes to REST rather than to a shiver: friction comes off in DRAG
    # steps and the last of it is CLAMPED to zero, so a ship left alone reads 0
    # and stays 0.  Without the clamp the residue under one DRAG would be a
    # permanent drift -- invisible in a single frame, and fatal at a landing.
    g.run(8)
    check(g.ship()["vx"] == 0,
          "and friction comes to rest rather than crawling -- vx is 0 after "
          "letting go, not a permanent sub-DRAG drift (vx %d)" % g.ship()["vx"])

    # The aggregate, against the per-tick claim above: every strafing tick this
    # block flew cost FUEL_BURN and nothing else did, the settle and the two
    # sprite reads included.
    strafe_ticks = 2 + 3 + 2 * k
    check(g.ship()["fuel"] == FUEL_START - strafe_ticks * FUEL_BURN,
          "and the whole flight of it cost the engine's own rate -- %d ticks of "
          "sideways thrust is %d units out of %d (fuel %d)"
          % (strafe_ticks, strafe_ticks * FUEL_BURN, FUEL_START,
             g.ship()["fuel"]))


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
    # Free fall over the whole of LANDER's air arrives at sqrt(2*GRAV*d*256) in
    # 8.8 units -- several times SAFE_VY_MAX at either GRAV -- so the verdict is
    # TOO_FAST, not CRASH, which is reserved for ground that is not a pad.
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
        g.run(1, "A" if g.ship()["vy"] > VY_HOLD else "")
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
    # ...and the telemetry is in the WINDOW map, which is where P12 puts it.  The
    # string has to be looked for THERE and not in the BG map: the two maps are
    # 32x32 each and the same (x, y) in both is a different cell, so a "FUEL"
    # found at BG row 0 would be the title's leftovers and not the HUD at all.
    check(bool(g.find_text("FUEL", WIN0)),
          "the HUD takes its place, in the WINDOW map (%r)"
          % (g.find_text("FUEL", WIN0),))

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

    g.run(20, "A")                      # 20 ticks of held thrust
    b = g.ship()
    f1 = g.hud_num(HUD_FUEL_ROW, HUD_FUEL_COL, HUD_FUEL_W)
    check(b["fuel"] == a["fuel"] - FUEL_BURN * 20,
          "20 ticks of held A burn %d fuel (%d -> %d)"
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
    check(s["state"] == ST_CRASH and bool(g.find_text("CRASHED", WIN0)),
          "a hard drop ends the life, and the HUD says so (state %d after %d "
          "ticks, %r)" % (s["state"], ticks, g.find_text("CRASHED", WIN0)))

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
        t = g.tile(x, HUD_VERDICT_ROW, WIN0)
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
        g.run(1, "A" if g.ship()["vy"] > VY_HOLD else "")
        ticks += 1
    g.run(2)
    s = g.ship()
    shown = g.hud_num(HUD_VERDICT_ROW, HUD_VERDICT_COL, 1)
    check(s["state"] == ST_LANDED and bool(g.find_text("LANDED X", WIN0)) and
          shown == s["mult"] == 2,
          "and a controlled descent lands and the HUD scores it -- state %d "
          "after %d ticks, showing %r, scored %d, %r"
          % (s["state"], ticks, shown, s["mult"], g.find_text("LANDED X", WIN0)))

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
    # the tick in between is a tick with A down -- and the volume nibble of
    # NR12 is the engine: non-zero exactly when the ROM decided this tick
    # burned.
    g.run(1, "A")
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
        g.run(1, "A" if g.ship()["vy"] > VY_HOLD else "")
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
    check written that way; the descent's surface is 96..100 rows down and every
    column of it is below the bottom of the screen at row 0, which is asserted
    at the end as the reason the offset has to exist.

    THE OFFSET IS THE CAMERA'S NOW, and it is read out of the ROM rather than
    mirrored here.  P9 wound it by hand to a constant; P10's camera computes the
    row and P11 streams the profile through a ring on it, so a mirrored constant
    would be a second answer to a question the ROM already answers -- and a
    probe that took its expectations from the thing it is checking could not
    tell a wrong window from a right one.  The flight to the bottom is what
    makes the offset nonzero and the surface rows visible: at the top of an
    800 px world the window is eighteen rows of SKY, and "sky where the profile
    says sky" is a claim a window that blitted nothing would pass.
    """
    print("P9 window")
    # A symbol this phase introduces being ABSENT is an assertion failure, not
    # a harness error: that is the power gate on the P8 ROM, and it answers 1.
    if not g.need("terrain", "terrain_lander", "terrain_descent", "cam"):
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
    g.run(4)                # ...and the ring's first fill lands

    check(g.u16("terrain") == g.addr["terrain_descent"]
          and g.active_profile() == descent,
          "and the one `terrain` symbol points at the DESCENT profile "
          "(terrain -> 0x%04X, terrain_descent at 0x%04X)"
          % (g.u16("terrain"), g.addr["terrain_descent"]))

    # Fly it to the ground.  The camera is the offset now and it starts at 0 --
    # the identity -- so the window only becomes something worth checking once
    # the descent has wound it down to where the profile's surface can be seen.
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1)
        ticks += 1
    g.run(2)
    top = g.u16("cam") >> 3
    check(0 < top <= descent[0],
          "the camera has wound the window %d rows down the DESCENT world, so "
          "the check below is not the identity it warns about (%d ticks)"
          % (top, ticks))

    # The map row a world row lives in is its own index modulo the map's height
    # -- the RING P11 wound the profile onto.  Screen row y shows the world row
    # `top + y`, and that world row's tile is at map row `(top + y) & 31`, which
    # is the same as `world_row & 31`: the two agree because both wrap at 32.
    def slot(wr):
        return wr & (MAP_TILES - 1)

    # Column by column: the surface tile is where the OFFSET puts it -- on the
    # screen at row descent[x] - top, and at the ring slot that world row owns.
    bad = []
    for x in range(WORLD_COLS):
        y = descent[x] - top
        got = g.tile(x, slot(descent[x])) if 0 <= y < VIEW_H else None
        if got != T_TERRAIN_TOP:
            bad.append((x, descent[x], y, got))
    check(not bad,
          "every column's surface tile is at terrain_descent[col] - %d -- "
          "col:profile-row:screen-row:found %r" % (top, bad[:5]))

    # ...and the rest of the window is sky above it and body below it, so a ring
    # that painted the surface and left the row alone fails too.  Rows 0 and 1
    # are terrain as of P12 -- the telemetry moved to the WINDOW layer -- so the
    # loop no longer starts below them.
    bad = []
    for x in range(WORLD_COLS):
        for y in range(VIEW_H):
            wr = top + y
            got = g.tile(x, slot(wr))
            ok = (got in SKY_IDS if wr < descent[x] else
                  got == T_TERRAIN_TOP if wr == descent[x] else
                  got == T_TERRAIN)
            if not ok:
                bad.append((x, y, wr, descent[x], got))
    check(not bad,
          "the whole window is sky/surface/body exactly as the profile and the "
          "offset say -- col:row:world-row:surface-row:found %r" % (bad[:5]))

    # The offset is not decoration: at the top of the world the descent shows no
    # ground at all, which is what a life that opens there would be looking at.
    off0 = [x for x in range(WORLD_COLS) if 0 <= descent[x] < VIEW_H]
    check(top > 0 and not off0,
          "and it is the offset that shows it -- at row 0 the descent's surface "
          "would be off the bottom of the screen in all %d columns (%d would "
          "show it), so a window that opened there would draw %d rows of sky"
          % (WORLD_COLS, len(off0), VIEW_H))


# ----------------------------------------------------------------- P10 -----
def p10_camera(g):
    """The camera tracks the ship while it is free and holds at each bound --
    and both halves of it are observable here, which is the whole point.

    SCY is what the PPU is told to scroll the background by.  The SHIP's own
    screen position is what the sprite is drawn at, and it is the half a camera
    written to a variable but never SUBTRACTED from the draw call would fail:
    SCY moves the background and nothing else, so the ship would slide off the
    top of the screen at exactly the speed the view scrolled beneath it, while
    SCY itself tracked the ship perfectly and a check that only read SCY would
    call that a pass.  The sprite is therefore read too, and it is the assertion
    with the real power.

    The world is DESCENT's, because it is the only one with anywhere to travel:
    LANDER's is 104 px against a 144 px screen, so its camera is pinned at 0 and
    reads identical to P9's there.  Selecting it is the same two presses
    p9_window makes, and for the same reason -- P9 wired the title's mode to the
    terrain POINTER, so the tall world is reachable even though playing it is
    M2's job.

    NO CLAIM IS MADE about how it LOOKS.  P9's window blit is still a fixed
    band, so the view below it is blank by design and P11 is what fills it; what
    is asserted is the SCROLL and the SHIP, both of which are live now.
    """
    print("P10 camera")
    if not g.need("terrain", "terrain_descent", "ship"):
        return

    g.run(150)
    g.run(4, "T")           # SELECT: the title's DESCENT half
    g.run(2)                # button-free: the next press is an EDGE
    g.run(8, "S")           # START: the tall world, and the field is handed over
    g.run(2)

    # A symbol this phase introduces being ABSENT is an assertion failure, not a
    # harness error, and both are named here BEFORE either is read: a missing
    # one would raise and answer 2, which a power gate must not.  The descent
    # below runs either way -- see the SCY assertion -- so an older ROM fails on
    # the behaviour as well as on the name.
    have = g.need("cam", "world_h")

    # ---- fly it, sampling every tick -------------------------------------
    # SCY is ordinary memory to PyBoy and the ship is P3's struct, so this half
    # needs NO symbol this phase introduces -- and that is deliberate: it is the
    # power gate.  The previous phase's ROM has the DESCENT world and the ship
    # and never writes SCY at all, so over a whole descent the scroll is pinned
    # at 0 and the assertion below fails on the behaviour rather than on a
    # missing name.
    samples = []
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1)
        ticks += 1
        samples.append((g.ship()["y"], g.u16("cam") if have else None,
                        g.p.memory[SCY]))
    check(len(samples) > 8 and g.ship()["state"] != ST_FLY,
          "the scripted descent reached the ground in %d ticks (%d samples)"
          % (ticks, len(samples)))

    scy_seen = sorted({s[2] for s in samples})
    check(len(scy_seen) > 1,
          "and SCY MOVED during it -- the camera is written at all (SCY took "
          "%d distinct values over %d ticks, first %r, last %r)"
          % (len(scy_seen), len(samples), samples[0][2], samples[-1][2]))
    if not have:
        return

    # ---- the ROM's own geometry ------------------------------------------
    descent = g.profile("terrain_descent")
    world_h = (max(descent) + 1) * 8        # the deepest column, +1 tile of ground
    # The bound is on what is VISIBLE and not on the panel: P12's status bar is a
    # WINDOW at the bottom of the screen and covers the last HUD_H rows, so the
    # camera must stop PLAY_H_PX above the world's end.  A bound taken on the
    # panel is 16 px too generous, and those 16 px are the ground.  See p12_mode.
    cam_max = world_h - PLAY_H_PX
    check(g.u16("world_h") == world_h and world_h > PLAY_H_PX,
          "the ROM takes the world's height from the profile it is drawing, so "
          "the clamp and the tiles cannot be about two worlds -- %d px from "
          "DESCENT's deepest row %d, against the visible band's %d"
          % (g.u16("world_h"), max(descent), PLAY_H_PX))

    # ---- the camera, tick by tick ----------------------------------------
    # Every sample against the rule, written out here rather than imported from
    # sim.h -- a probe that asked the ROM what the answer should be could not
    # tell a camera whose anchor had drifted from one that had not.
    #
    # ONE ITERATION OF SLACK, and no more.  main.c computes cam from ship.y
    # inside the tick, and these are two separate reads of the emulator's memory
    # -- so a sample that lands between the step and the camera is legitimately
    # this tick's altitude against the previous tick's camera.  The slack is in
    # the PHASE, never in the value: the accepted answer is the rule at the
    # altitude before or the altitude now, and a camera with the wrong anchor,
    # or one clamped to the map's 256 px, answers neither at any altitude.
    #
    # SCY is the camera's LOW BYTE and not the camera: the world is ~800 px and
    # one scroll register is 256, so the scroll wraps and repeats.  Comparing it
    # to the full 664 would be comparing against a value the hardware cannot
    # hold; what has to be true is the fold, and pinning the fold is what says
    # P11 has a wrap to make seamless rather than a mystery.
    #
    # SCY carries the same one-iteration slack for the same reason and from the
    # other end of the tick: cam is computed BEFORE wait_vbl_done() and SCY is
    # written in the vblank AFTER it, so a sample taken between the two sees the
    # new camera against the scroll that was written a tick ago.
    def want_cam(y):
        return min(max(y - CAM_ANCHOR, 0), cam_max)

    bad = []
    for k, (y1, c1, s1) in enumerate(samples):
        y0 = samples[k - 1][0] if k else y1
        c0 = samples[k - 1][1] if k else c1
        if c1 not in (want_cam(y0), want_cam(y1)) or s1 not in (c0 & 0xFF, c1 & 0xFF):
            bad.append((y0, y1, c1, s1))
    check(not bad,
          "cam is the clamp of ship_y - %d to the WORLD's bound %d -- not the "
          "map's 256 px -- at every sampled tick, and SCY is its low byte "
          "(y_prev:y:cam:scy %r)" % (CAM_ANCHOR, cam_max, bad[:4]))

    # ---- the two bounds, held constant -----------------------------------
    pinned_top = [c for (y, c, _) in samples if y <= CAM_ANCHOR]
    check(len(pinned_top) >= 4 and set(pinned_top) == {0},
          "before the descent starts the camera is pinned at 0 -- %d samples at "
          "or above y %d, cam values %r"
          % (len(pinned_top), CAM_ANCHOR, sorted(set(pinned_top))))

    pinned_bot = [c for (y, c, _) in samples if y - CAM_ANCHOR >= cam_max]
    check(len(pinned_bot) >= 4 and set(pinned_bot) == {cam_max},
          "and once the ship is within a screen of the pad it is pinned at %d, "
          "so the view does not scroll past the bottom of the world -- %d "
          "samples at or below y %d, cam values %r"
          % (cam_max, len(pinned_bot), cam_max + CAM_ANCHOR,
             sorted(set(pinned_bot))))

    # ---- and it TRACKS in between ----------------------------------------
    # Two things at once, and neither implies the other.  It never moves BACK
    # UP, so the view cannot judder as the ship falls; and it advances across
    # the free window by as much as the ship fell through it, so a camera that
    # held or stepped -- or one that only ever moved for a frame or two -- does
    # not pass on the bounds assertions above alone.
    free_y = [y for (y, c, _) in samples if 0 < c < cam_max]
    free_c = [c for (_, c, _) in samples if 0 < c < cam_max]
    span = max(free_y) - min(free_y)
    check(len(free_c) >= 4 and all(b >= a for a, b in zip(free_c, free_c[1:]))
          and free_c[-1] - free_c[0] >= span - 4,
          "between the bounds it tracks the ship rather than holding or "
          "stepping -- %d unclamped samples, none moving back up, and the "
          "camera advanced %d px across the %d px the ship fell (%r ... %r)"
          % (len(free_c), free_c[-1] - free_c[0], span, free_c[:3], free_c[-3:]))

    # ---- the SPRITE, which is the half that is silently wrong -------------
    # The assertion a camera kept in a variable but never taken off the draw
    # call fails: move_sprite() would be handed the ship's WORLD y, which for a
    # ship 700 px down the world is a byte that wraps into the top of the screen
    # -- so the ship would appear to jump about as the view scrolled, at a
    # position that has nothing to do with cam.
    #
    # START first: the descent above ended in a crash, and the ship is frozen.
    # 150 frames and not 60: the descent spends its first ~30 ticks with the
    # camera pinned at the top, and the ROM does not complete one tick per
    # emulated frame in this world (P9's per-tick cost, unmoved by this phase),
    # so a short window would sample almost nothing but the clamp.
    g.run(8, "S")
    g.run(1)
    y0, c0 = g.ship()["y"], g.u16("cam")
    bad = []
    seen = 0
    for _ in range(150):
        g.run(1)
        y1, c1 = g.ship()["y"], g.u16("cam")
        oy = g.oam()[0]
        if 0 < min(c0, c1) and max(c0, c1) < cam_max:
            seen += 1
            # One vblank of slack, and no more: move_sprite() writes GBDK's
            # SHADOW OAM and only the next vblank copies it, so which side of
            # the copy this sample lands on is decided by the length of the loop
            # body.  The slack is in the PHASE -- the accepted answer on either
            # side is the tick before or the tick after -- and never in the
            # value, so a ship drawn at its world y (hundreds of px out, and
            # truncated to a byte) fails on every one of them.
            want = {((y0 - c0 + OAM_DY) & 0xFF), ((y1 - c1 + OAM_DY) & 0xFF)}
            if oy not in want:
                bad.append((y0, c0, y1, c1, oy, sorted(want)))
        y0, c0 = y1, c1
    # `seen` is not decoration: every comparison above is skipped while the
    # camera is clamped, so a camera that never came off its bound would leave
    # `bad` empty and this pass trivially.  The count is what stops that, and it
    # is the same false-PASS shape the 60 ticks exist to avoid.
    check(seen >= 30 and not bad,
          "and the sprite is drawn at the CAMERA's idea of the ship's screen y "
          "-- world y minus cam, which holds it at %d -- rather than at its "
          "world y (%d of 150 ticks were free; y0:cam0:y1:cam1:oamY:want %r)"
          % (CAM_ANCHOR, seen, bad[:4]))


# ----------------------------------------------------------------- P11 -----
def p11_stream(g):
    """The map is a RING over the world: after any number of scrolled rows,
    every visible row is the profile row the CAMERA says belongs there.

    A ring is the one thing a tilemap read cannot be casual about.  The same map
    slot is right for one world row and wrong for another, and a stale row, a
    repeated row and a row from the wrong part of the world are all just tiles
    in a tilemap -- none of them is a screenshot, and none of them fails a check
    that only looks at one screen.  So every assertion below is the tile at the
    map slot the WORLD ROW owns, against the profile's own bytes, and the flight
    is long enough to cross the map's whole height (256 px) so that a modulus
    that is merely wrong -- one that scrolls correctly for a map and then
    repeats -- is caught rather than exercised.  The last third does the other
    half: it walks the camera back UP, which is the only thing that can show
    whether the ring gives back the rows the HUD covered.
    """
    print("P11 stream")
    # A symbol this phase introduces being ABSENT is an assertion failure, not a
    # harness error: that is the power gate on the P10 ROM, and it answers 1.
    # The descent below runs either way -- an older ROM has every OTHER symbol
    # this reads and fails on the CONTENT, where the whole band past the 18 rows
    # P9 blitted is blank -- so the gate holds on the behaviour as well as on
    # the name.
    have = g.need("terrain", "terrain_descent", "ship", "cam", "ring_top")

    def settled(cam, scy):
        """Is this sample past the tick's writes, so that the camera and the map
        are the same picture?

        `ring_top` is written BY the row write and by nothing else, so it is the
        exact test -- and on a ROM that has no ring (the power gate's, where the
        symbol is not in the map at all) there is nothing to compare and the
        scroll register is the next best thing: SCY is written in the same
        vblank as the map, so it is level with it whether or not the camera is.
        Reaching for a missing symbol would RAISE, and a harness error exits 2 --
        which is not what a power gate is allowed to answer."""
        if have:
            return g.var("ring_top") == cam >> 3
        return scy == (cam & 0xFF)

    g.run(150)
    g.run(4, "T")           # SELECT: the title's DESCENT half (an EDGE)
    g.run(2)                # button-free: the next press is an EDGE
    g.run(8, "S")           # START: the tall world, from the top of it
    g.run(4)                # ...and the ring's first fill, 32 rows of map

    descent = g.profile("terrain_descent")

    def band_bad(cam):
        """Every tile of the visible window against the world row the camera
        puts at that screen row, or [] if they all agree.

        BOTH halves come from `cam` and not from SCY, deliberately.  They are
        one picture -- SCY says which map rows are on the screen and the camera
        says which world rows those are -- but they are two registers written in
        one vblank, and this file samples the emulator between frames, so a
        sample can land on either side of that pair.  The pairing is checked
        separately below; what is checked HERE is the ring, and it is checked
        against the thing that wrote it.

        EVERY visible row, as of P12, and not just the ones below the HUD: the
        telemetry is the WINDOW layer's now, so the BG map holds terrain from
        row 0 down and there is no longer a strip in it for p6_hud to own."""
        top = cam >> 3
        out = []
        for r in range(VIEW_H):
            wr = top + r
            mr = wr & (MAP_TILES - 1)
            for c in range(WORLD_COLS):
                got = g.tile(c, mr)
                ok = (got in SKY_IDS if wr < descent[c] else
                      got == T_TERRAIN_TOP if wr == descent[c] else
                      got == T_TERRAIN)
                if not ok:
                    out.append((c, r, wr, mr, descent[c], got))
        return out

    # ---- the descent, sampled every tick ---------------------------------
    # THE BAND IS READ AT THE SAMPLE, not off a list of cameras afterwards.
    # The map is a ring, so a camera remembered from tick 40 says nothing about
    # the tiles that are up at tick 200 -- it says which world rows WOULD be
    # there if nothing had moved, and every one of them is a tile from the right
    # profile.  That is the shape of bug this phase is about, so the tilemap is
    # read on the same tick the camera is.
    #
    # THE BAND IS READ ONLY WHERE THE TICK'S TWO HALVES AGREE, and that is the
    # whole of the slack in this check.  A tick computes `cam` in its body and
    # writes SCY and the ring from it in the vblank after, so a sample can land
    # between those two -- and then the camera is this tick's while the map is
    # the last tick's, which is one row of difference and looks exactly like the
    # stale row this phase is about.  `ring_top` is the test for "these are one
    # picture": it is written BY the row write and by nothing else, so it is
    # level with the camera on every tick whose vblank the sample is past, and
    # a row behind it on the ticks the sample is not.  Where it holds, the
    # comparison below is exact -- no slack row, which is what matters, because
    # a slack row is precisely wide enough to hide the bug.
    samples = []
    band_fails = []
    checked = 0
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1)
        ticks += 1
        cam, scy = g.u16("cam"), g.p.memory[SCY]
        samples.append((cam, scy))
        # EVERY SECOND TICK, and it was every fourth until P13 fixed the
        # DESCENT loop's frame overrun.  This flight is measured in EMULATED
        # FRAMES and the ROM was running at about half a tick per frame when
        # the stride was chosen, so the same descent reached the ground in 292
        # frames then and 148 now -- a stride of four would compare half the
        # bands it used to.  The threshold below is unmoved and the bands
        # compared roughly double: this is a denser sample of the same claim,
        # not a smaller one.  probe.p13_descent is what asserts the loop runs
        # one tick per frame, and where that came from.
        if ticks % 2 or not settled(cam, scy):
            continue
        checked += 1
        b = band_bad(cam)
        if b:
            band_fails.append((cam, scy, b[:2]))
    check(len(samples) > 8 and g.ship()["state"] != ST_FLY,
          "the scripted descent reached the ground in %d ticks (%d samples)"
          % (ticks, len(samples)))

    # ...and the scroll register is the camera's low byte.  One tick of slack,
    # and no more: `cam` and SCY are two separate reads of the emulator's memory
    # and a sample can land between the tick that computed one and the vblank
    # that wrote the other, so the accepted answer is this tick's camera or the
    # last one's.  The slack is in the PHASE and never in the value -- a camera
    # kept in a byte, clamped at 256 px the way the map's own size would clamp
    # it, is 400 px out at the bottom of this world and fails on every sample.
    bad = []
    for k, (_c, s) in enumerate(samples):
        c0 = samples[k - 1][0] if k else _c
        if s not in (c0 & 0xFF, _c & 0xFF):
            bad.append((_c, s))
    check(not bad,
          "and SCY is the camera's own low byte on every sampled tick ("
          "cam:scy mismatches %r)" % (bad[:4],))

    check(checked >= 20 and not band_fails,
          "every visible row is the profile row the camera says belongs there, "
          "all the way down -- %d sampled bands, col:row:world-row:map-row:"
          "want:found %r" % (checked, band_fails[:3]))

    # ---- past a whole map -------------------------------------------------
    # The map is 32 rows and the world is 101, so the camera's own row crosses
    # the ring's entire height twice.  THAT is what makes the modulus a claim:
    # a band written at `wr & 15`, or at a base that does not follow the camera,
    # is right for the first 256 px of the descent and then repeats a stretch of
    # the world it has already gone past -- and every row of it is still a tile
    # from the right profile, so nothing but this number says it happened.
    tops = [c >> 3 for (c, _s) in samples]
    check(min(tops) == 0 and max(tops) - min(tops) >= MAP_TILES,
          "and the flight crossed the map's whole height -- the camera's row "
          "ran %d -> %d, %d rows of it against a %d-row map, so the wrap is "
          "crossed and not merely reached"
          % (min(tops), max(tops), max(tops) - min(tops), MAP_TILES))

    # ---- and back UP, where a stale row would hide ------------------------
    # The HUD is two rows of MAP, so the two map rows the camera is sitting on
    # hold telemetry and not terrain; walking back UP the world drags those rows
    # down out of the strip and into the terrain, where they have to be the
    # profile again.  It is the same one-tick, one-row class of bug the phase
    # exists to avoid and it has exactly one symptom -- a stale row that tracks
    # the camera -- so the climb is flown and the band is read on the way.
    #
    # Fall first, then burn: a ship that opens at the top of the world has
    # nothing above it to climb back to, so the camera can only be made to walk
    # backwards from partway down.  y = 300 puts it well clear of the ground at
    # 768 and the tank covers the reversal with room to spare.
    g.run(8, "S")                       # a fresh life, back at the top
    g.run(8)                            # ...and the ring rebuilt under it
    ticks = 0
    while g.ship()["y"] < 300 and ticks < DESCENT_LIMIT:
        g.run(1)
        ticks += 1
    top_max = g.u16("cam") >> 3
    bad = []
    checked = 0
    climbed = 0
    for k in range(DESCENT_LIMIT):
        g.run(1, "A")
        if g.ship()["state"] != ST_FLY:
            break
        top = g.u16("cam") >> 3
        if top > top_max:
            top_max = top
        climbed = top_max - top
        if climbed and settled(g.u16("cam"), g.p.memory[SCY]):
            checked += 1                       # the same agreement gate as above
            b = band_bad(top << 3)
            if b:
                bad.append((g.u16("cam"), b[:2]))
        if climbed >= 5:
            break
    check(climbed >= 5 and checked >= 8 and not bad,
          "and a ship that thrusts back UP the world is followed -- the camera "
          "walked %d rows backwards over %d sampled bands, and every visible "
          "row was the profile's again (col:row:world-row:map-row:want:found "
          "%r)" % (climbed, checked, bad[:3]))


# ----------------------------------------------------------------- P12 -----
# The status bar's STATIC cells, as framebuffer pixel slices: the label glyphs
# and the gaps around them, and NO cell that carries a number.  A bar that is
# scrolled by the world, or one that is not there at all, is exactly a bar whose
# label cells move or go blank -- so these slices are what p12_mode compares
# frame to frame and what it looks for ink in.  Written out from the layout
# main.c builds ("FUEL ddd ALT ddd" / "VX ddd VY ddd PAD Xd") rather than derived
# from the ROM, for the same reason HUD_VEL_ROW is.
#
# They all start at x >= 8 on purpose: the window is drawn from x = WX - 7 and
# WX is 7, and which side of that boundary an emulator puts the first column is
# not something this check should be deciding.
HUD_LABELS = ((HUD_BAR0, 8, 40), (HUD_BAR0, 64, 104),
              (HUD_BAR1, 8, 16), (HUD_BAR1, 48, 80), (HUD_BAR1, 104, 152))


def p12_mode(g):
    """Two modes off the title, and a status bar that stays put while the world
    scrolls under it.

    FIVE THINGS, and each of them is checked where it is observable:

    THE BOOT DEFAULT IS READ RAW -- no keypress at all.  Which mode the ROM
    opens on is a claim about ONE initialiser, and a check that pressed START
    first would be reading the hand-over, where main.c re-derives the profile and
    the world's height from `pick` and would therefore agree with any mode at
    all.  So the title's mode line, the profile `terrain` points at and the world
    `world_h` measures are all read before a button is touched, and all three
    have to name the same mode.

    START REALLY OPENS THE MODE THE TITLE NAMED.  The trap is a `pick` that
    selects the terrain pointer but not the camera's world (or the other way
    round): LANDER physics over DESCENT terrain plays perfectly plausibly and is
    wrong, so both are asserted together, and they are asserted against the
    generator's own profiles -- not against each other, which a ROM with one
    profile would pass.

    THE STATUS BAR IS AT THE BOTTOM OF THE SCREEN AND DOES NOT MOVE, and it is
    read off the FRAMEBUFFER.  `Game.tile()` addresses MAP coordinates: a HUD read
    out of the BG map at rows 0-1 is the wrong two rows of a different map, and
    the whole defect this phase fixes is the mapping between map row and screen
    row.  So the assertion is about screen pixels, and it is two-sided:

      * every sampled frame, both bar rows MIX ink and paper -- which is what a
        row of glyphs does and what neither the sky nor a solid ground tile does;
      * every sampled frame, the bar's LABEL cells hold the same pixels they held
        on the first one.  The terrain under a BG strip is dragged along by SCY,
        so a bar that lived in the world fails this on the first frame the camera
        moves, and in DESCENT the camera moves on nearly all of them.

    AND THE CAMERA CLAMPS ON WHAT IS VISIBLE.  The window always runs to the
    bottom-right corner, so the bar covers the last HUD_H rows of background: a
    clamp taken on the panel's 144 px stops the view 16 px short of the world, and
    those 16 px are the ground of a DESCENT.  The descent below is long enough to
    reach the bound, and both the clamp and the row it leaves visible are read
    back.

    THE FIELD CAN BE LEFT AGAIN, which is its own transition and not the
    hand-over run backwards.  SELECT in flight goes to the title, SCY goes with
    it, and the press must not also reach the title's mode toggle -- three
    separate claims, and the last one is the trap: both branches read the same
    edge off the same variable, so a ROM that did not consume the bit out of
    `pressed` leaves the field and flips the world in the same tick.

    No claim is made about how any of it LOOKS beyond that: "the bar is legible"
    is an eye's, and this file never had one.
    """
    print("P12 mode")
    # A symbol this phase depends on being ABSENT is an assertion failure, not a
    # harness error: on the P11 ROM `world_h` and `cam` are there but the bar is
    # two rows of BG MAP, so this answers 1 on the CONTENT -- see the framebuffer
    # half -- and the name list is here so that a genuinely older ROM exits 1
    # rather than raising.
    have = g.need("game", "pick", "terrain", "terrain_lander", "terrain_descent",
                  "world_h", "ship", "cam")

    lander = g.profile("terrain_lander")
    descent = g.profile("terrain_descent")
    lander_h = (max(lander) + 1) * 8
    descent_h = (max(descent) + 1) * 8
    check(lander != descent and descent_h > lander_h and
          len(lander) == len(descent) == WORLD_COLS,
          "the two profiles are two different worlds -- LANDER %d px deep "
          "against DESCENT %d px, over the same %d columns"
          % (lander_h, descent_h, WORLD_COLS))

    # ---- the boot default, with nothing pressed ---------------------------
    g.run(150)
    check(g.var("game") == ST_TITLE,
          "the ROM boots on the title and stays there with no hand on it "
          "(game %d)" % g.var("game"))
    check(g.var("pick") == 0 and bool(g.find_text("MODE LANDER")) and
          not g.find_text("MODE DESCENT"),
          "and the mode it boots on is the one it advertises -- LANDER (pick "
          "%d, mode line %r)" % (g.var("pick"), g.find_text("MODE LANDER")))
    if not have:
        return
    # The whole of "a single `pick` initialiser is the boot default": the mode
    # byte, the profile the renderer and sim.h's collision read, and the world
    # the camera is clamped against are one answer from the first tick and not
    # only from the hand-over.  A `pick` that were initialised to DESCENT while
    # `terrain` kept terrain.h's own initialiser fails HERE, and nowhere later --
    # which is the bug a `start()` helper would have masked.
    check(g.u16("terrain") == g.addr["terrain_lander"] and
          g.u16("world_h") == lander_h and g.u16("cam") == 0,
          "and the world the ROM is running on is that mode's, before any button "
          "is pressed -- terrain %r -> 0x%04X, world_h %d, cam %d"
          % (g.active_profile() == lander, g.u16("terrain"), g.u16("world_h"),
             g.u16("cam")))

    # ---- SELECT names the other one ---------------------------------------
    g.run(4, "T")                       # an EDGE: held, it flips once
    g.run(2)                           # button-free, so the next press is one too
    check(g.var("pick") == 1 and bool(g.find_text("MODE DESCENT")) and
          not g.find_text("MODE LANDER"),
          "SELECT moves the title to DESCENT and the mode line with it (pick %d, "
          "%r)" % (g.var("pick"), g.find_text("MODE DESCENT")))

    # ---- and START opens the mode that was named --------------------------
    g.run(8, "S")
    g.run(4)                           # ...and the ring's first fill lands
    check(g.u16("terrain") == g.addr["terrain_descent"] and
          g.active_profile() == descent,
          "START hands over the DESCENT half the title was offering -- the one "
          "`terrain` symbol now points at 0x%04X, which is terrain_descent at "
          "0x%04X (%r)"
          % (g.u16("terrain"), g.addr["terrain_descent"], g.active_profile()))
    check(g.u16("world_h") == descent_h,
          "and the camera's world went with the tiles -- world_h %d px, the "
          "deepest column of the profile the renderer is drawing, against "
          "LANDER's %d (a camera still clamped on the short world would never "
          "scroll)" % (g.u16("world_h"), lander_h))

    # ---- the status bar, off the FRAMEBUFFER ------------------------------
    # Sampled every few ticks across the whole descent, and the flight reaches
    # the ground: the first third of it has NOTHING but sky in the world the
    # camera is over, so a bar that came from there would be blank on those
    # frames and the last third has ground, which scrolls.  Both are caught.
    flat = 0                           # frames where a bar row was one colour
    moved = 0                          # frames where the labels were not home
    ref = None
    cams = set()
    ticks = 0
    while g.ship()["state"] == ST_FLY and ticks < DESCENT_LIMIT:
        g.run(1)
        ticks += 1
        cams.add(g.u16("cam"))
        if ticks % 5:
            continue
        for r in (HUD_BAR0, HUD_BAR1):
            if len(set(g.scanline(r))) < 2:
                flat += 1
        block = b"".join(g.pixels(r, x0, x1) for (r, x0, x1) in HUD_LABELS)
        if ref is None:
            ref = block
        elif block != ref:
            moved += 1
    check(g.ship()["state"] != ST_FLY and ticks > 8,
          "the scripted descent flew into the ground in %d ticks over %d camera "
          "positions, so the samples below span a scrolled world"
          % (ticks, len(cams)))
    check(len(cams) > 8,
          "and the camera really did scroll under the bar -- %d distinct cam "
          "values, %d -> %d px" % (len(cams), min(cams), max(cams)))
    check(flat == 0,
          "the status bar's two rows MIX ink and paper on every sampled frame of "
          "the descent -- glyphs and not the blank sky the camera was over (%d "
          "sampled rows were a single colour)" % flat)
    check(moved == 0 and ref is not None,
          "and the bar's label cells are the SAME PIXELS on every one of them, "
          "so the bar is not being dragged along by SCY -- a BG strip's screen y "
          "is map_row * 8 - SCY and it is home only while cam %% 8 == 0 (%d "
          "sampled frames had moved)" % moved)

    # ---- the clamp is on what is VISIBLE, not on the panel ----------------
    # The camera stops PLAY_H_PX above the world's end, 16 px past where a clamp
    # on the panel's 144 would have stopped.  The gap is the whole of the ripple
    # this phase carries: those 16 px are the ground of a descent, and a view
    # clamped on the panel scrolls them under the status bar and never shows them
    # while every frame on the way down looks like a working camera.
    cam_max = descent_h - PLAY_H_PX
    check(g.u16("cam") == cam_max and cam_max == descent_h - VIEW_H_PX + 16,
          "and the camera came to rest at %d -- the world's end less the VISIBLE "
          "band, %d px and not the panel's %d, which would have stopped the view "
          "with the ground still under the bar (cam %d)"
          % (cam_max, descent_h - PLAY_H_PX, descent_h - VIEW_H_PX,
             g.u16("cam")))

    # ---- and SELECT takes the field away again ----------------------------
    # The way BACK to the title, which the ROM did not have until this: the
    # field is ST_PLAY and the title is ST_TITLE, and one press has to be the
    # whole of the move.  Three things, and each is a way the move half-happens:
    #
    #   * the state really is the title, not the field redrawn-looking-like one;
    #   * SCY is back to 0.  This is the DESCENT cartridge and its camera is at
    #     the bottom clamp, so SCY was holding 680 % 256 = 168.  A title left
    #     scrolled by a field that is no longer under it is the specific damage
    #     of keeping the register, and nothing else here would see it -- the
    #     window is NOT scrolled by SCY, so the mode line looks right regardless;
    #   * `pick` is UNCHANGED.  The title's own SELECT is the mode toggle and it
    #     reads the same edge this branch just consumed, so a ROM that forgot to
    #     take the bit out of `pressed` leaves the field AND flips the world on
    #     arrival -- which reads as the mode line changing under the player.
    scrolled = g.p.memory[SCY]
    g.run(4, "T")                       # the same edge the title's toggle uses
    g.run(4)                            # the title is built on the tick of the press
    check(g.var("game") == ST_TITLE and g.p.memory[SCY] == 0,
          "SELECT in flight takes the field away and lands on the title -- game "
          "%d, SCY %d (it was %d under the camera's clamp)"
          % (g.var("game"), g.p.memory[SCY], scrolled))
    check(g.var("pick") == 1 and bool(g.find_text("MODE DESCENT")),
          "and the press did not carry through to the title's own mode toggle -- "
          "still DESCENT (pick %d, mode line %r)"
          % (g.var("pick"), g.find_text("MODE DESCENT")))

    # ---- the other mode, on its own cartridge -----------------------------
    # The two modes need two runs because the boot default is a claim about the
    # FIRST screen: the title hands over to the field and the field comes back,
    # but neither run below needs that round trip, and a `pick` that leaked
    # between them would show up as the wrong profile.  LANDER is the boot
    # default, which is also the mode this check opened on, but it is reached
    # HERE without a SELECT.
    g2 = Game(g.rom, g.mapfile)
    try:
        g2.run(150)
        g2.run(8, "S")
        g2.run(2)
        check(g2.u16("terrain") == g2.addr["terrain_lander"] and
              g2.u16("world_h") == lander_h and g2.u16("cam") == 0 and
              g2.var("pick") == 0,
              "and the boot default is the OTHER world -- START with no SELECT "
              "opens LANDER, the 104 px one, with the camera pinned at 0 (terrain "
              "0x%04X, world_h %d, cam %d)"
              % (g2.u16("terrain"), g2.u16("world_h"), g2.u16("cam")))

        l_flat = 0
        l_ref = None
        l_moved = 0
        for _ in range(16):
            g2.run(1)
            if g2.ship()["state"] != ST_FLY:
                break
            for r in (HUD_BAR0, HUD_BAR1):
                if len(set(g2.scanline(r))) < 2:
                    l_flat += 1
            block = b"".join(g2.pixels(r, x0, x1) for (r, x0, x1) in HUD_LABELS)
            if l_ref is None:
                l_ref = block
            elif block != l_ref:
                l_moved += 1
        # LANDER's camera never moves, so `moved` is true here for free and
        # proves nothing; the row's own ink is the half with the power.  On the
        # P11 ROM these two rows are plain background -- the ground tiles -- and
        # a solid tile row is a single colour.
        check(l_ref is not None and l_flat == 0 and l_moved == 0,
              "and LANDER's status bar is in the same place, inked, even though "
              "its world never scrolls to show it up (%d blank rows of %d "
              "sampled)" % (l_flat, 2 * 16))
    finally:
        g2.p.stop()


# ----------------------------------------------------------------- P13 -----
def p13_descent(g):
    """The DESCENT mode flown from the spawn to the PAD -- and every claim its
    two stateful halves make, exercised on a descent that ends in a landing
    instead of a crash.

    P10 checked the camera and P11 the ring, and both flew the SAME life: the
    ship falls the whole world with nobody at the controls, which is the
    cheapest scripted descent there is and all either phase needed -- the
    camera reaches its bottom clamp and the ring crosses its map.  What that
    leaves uncovered is everything about the mode's OTHER ending and the two
    things that only happen on a fall long enough to get there: the ship coming
    to rest on the descent's pad and being SCORED for it, the camera's bottom
    clamp held for a whole approach rather than a frame at the end, and the
    ring's modulus crossed a second time -- where a base that had stopped
    following the camera is wrong in a way its first crossing cannot show.

    THE PILOT IS PART OF THE CHECK, and it is not P5's.  VY_HOLD is a quarter
    of SAFE_VY_MAX and walks LANDER's 72 px of air down in ~300 ticks; the
    DESCENT world is 752 px of air over a 600 unit tank, so the same pilot
    needs ~2400 units of fuel, runs dry two thirds of the way down and falls
    the rest.  The mode's own numbers ask for the other shape -- fall hard,
    brake late, arrive under the threshold -- and a suite that only ever
    scripted the crash could not tell a descent that LANDS from one that
    cannot.  P13_BRAKE has the tuning and the reasoning; the landing below is
    asserted to arrive with fuel still in the tank, so a retune that made the
    descent unaffordable fails here rather than in a comment.

    THE HORIZONTAL WRAP IS CHECKED UNDER THIS PROFILE, in a second life: the
    ship is turned nose-first into the world and flown until it wraps.  The
    family's trap is a two-compare wrap that became an `& WORLD_MASK` -- 160 is
    not 256, so the mask puts the ship ninety-six pixels past the right edge,
    off the screen, where the seam reads as the ship flying away.  Every sample
    is asserted to be inside the world, the seam is asserted to have been
    crossed more than once, and the ground under the ship ON the seam is read
    back off the ROM's own HUD, so the column wrap in ship_col() is graded too
    and not just the x one.

    AND ONE META-ASSERTION AT THE END, which is the only one of these that is
    not about the game: every claim above is worth nothing if the situation it
    describes never happened -- a clamp asserted against no clamped samples, a
    band compared with no bands read, a seam nothing crossed.  Each claim
    reports how many times this run produced its own precondition, and the last
    check is that all of them cleared their minimum.  A check that quietly
    stopped being reached shows up there as a failure instead of a green line.
    """
    print("P13 descent")
    # A symbol this phase reads being ABSENT is an assertion failure, not a
    # harness error: that is the power gate on an older ROM and it answers 1.
    if not g.need("game", "pick", "terrain", "terrain_lander", "terrain_descent",
                  "world_h", "ship", "cam", "ring_top"):
        return

    lander = g.profile("terrain_lander")
    descent = g.profile("terrain_descent")
    descent_h = (max(descent) + 1) * 8
    cam_max = descent_h - PLAY_H_PX
    lander_h = (max(lander) + 1) * 8

    def col_of(x):
        """sim.h's ship_col(), mirrored -- the tile under the ship's CENTRE and
        its SECOND wrap: x = 159 puts the centre on pixel 163, world tile 20,
        which is tile 0 on the torus.  Written out rather than derived for the
        same reason the tile ids are: a probe that asked the ROM which column
        the ship was on could not tell a wrapped column from a clamped one."""
        c = (x + SHIP_W // 2) >> 3
        return c - WORLD_COLS if c >= WORLD_COLS else c

    def ground_under(prof, x):
        return prof[col_of(x)] * 8

    def want_cam(y):
        """sim.h's camera_for(), mirrored: the clamp of ship_y - CAM_ANCHOR to
        the WORLD's bound -- not the map's 256 px, and not the panel's 144."""
        return min(max(y - CAM_ANCHOR, 0), cam_max)

    def band_bad(cam):
        """Every tile of the visible window against the world row the camera
        puts at that screen row, or [] if they all agree.

        The map is a RING: a world row's slot is its own index modulo the map's
        height, and the whole point of the second crossing below is that a
        modulus which is merely wrong is right for the first 256 px of the
        descent.  Every visible row and not just some of them, because the
        status bar is the WINDOW layer's as of P12 and the BG map is terrain
        from row 0 down."""
        top = cam >> 3
        out = []
        for r in range(VIEW_H):
            wr = top + r
            mr = wr & (MAP_TILES - 1)
            for c in range(WORLD_COLS):
                got = g.tile(c, mr)
                ok = (got in SKY_IDS if wr < descent[c] else
                      got == T_TERRAIN_TOP if wr == descent[c] else
                      got == T_TERRAIN)
                if not ok:
                    out.append((c, r, wr, mr, descent[c], got))
        return out

    # ---- into the DESCENT half --------------------------------------------
    g.run(150)
    g.run(4, "T")               # SELECT: the tall world (an EDGE)
    g.run(2)                    # button-free: the next press is an EDGE too
    g.run(8, "S")               # START opens it
    g.run(2)
    check(g.var("pick") == 1 and g.u16("terrain") == g.addr["terrain_descent"]
          and g.u16("world_h") == descent_h,
          "the DESCENT half is the world the check is about -- pick %d, the one "
          "`terrain` symbol -> 0x%04X, world_h %d px against LANDER's %d"
          % (g.var("pick"), g.u16("terrain"), g.u16("world_h"), lander_h))

    # ---- the braking descent, sampled every tick --------------------------
    # The pilot reads the state, decides, and holds the button for ONE frame --
    # the loop below is closed-loop, so a press that lands between the ROM's
    # own joypad reads costs a tick of braking rather than the descent, and the
    # margin in P13_BRAKE is what absorbs it.
    samples = []                # (y, cam, scy)
    bands = 0                   # sampled bands that were compared
    deep_bands = 0              # ...and of those, the ones past the first wrap
    band_fails = []
    ticks = 0
    f0 = g.u16("frame")
    while g.ship()["state"] == ST_FLY and ticks < P13_LAND_LIMIT:
        s = g.ship()
        alt = ground_under(descent, s["x"]) - (s["y"] + SHIP_H)
        burn = (s["vy"] > 0 and
                alt * BRAKE_DIV <= s["vy"] * s["vy"] * P13_BRAKE)
        g.run(1, "A" if burn else "")
        ticks += 1
        cam, scy = g.u16("cam"), g.p.memory[SCY]
        samples.append((g.ship()["y"], cam, scy))
        # The band is read only where the tick's two halves AGREE -- the same
        # gate p11_stream uses, and for the same reason: a tick computes `cam`
        # in its body and writes SCY and the ring from it in the vblank after,
        # so a sample can land between them and be a genuine one-row mismatch
        # that is an ordering artefact rather than a stale row.  `ring_top` is
        # written BY the row write and by nothing else, so it is exactly the
        # test.
        if ticks % 4 == 0 and g.var("ring_top") == cam >> 3:
            bands += 1
            if cam >> 3 >= MAP_TILES:
                deep_bands += 1
            b = band_bad(cam)
            if b:
                band_fails.append((cam, b[:2]))
    landed = g.ship()
    check(len(samples) > 8 and landed["state"] != ST_FLY,
          "the brake-late pilot flew the world down -- %d frames to the ground "
          "(%d samples, state %d, vy %d, fuel %d)"
          % (ticks, len(samples), landed["state"], landed["vy"], landed["fuel"]))

    # ---- and the DESCENT loop keeps the clock -----------------------------
    # THE SAME CONTRACT p1_boot AND p6_hud HOLD LANDER TO, and the one thing
    # this mode did not have: one iteration is one tick, so a descent is 16.7 ms
    # a frame like everything else.  P10 and P11 both worked around the
    # overrun rather than fixing it -- they read the DESCENT world at whatever
    # rate it ran and allowed the ship to fall a tick or two per emulated frame
    # -- so nothing until now has said out loud whether it holds.
    #
    # It did not.  This is the assertion that fails on the P12 ROM: the status
    # bar's altitude is a THREE-digit number down a 101-row world where LANDER's
    # is two, and the HUD's decimal conversion stripped its digits by counting
    # tens off the whole value -- ~84 turns of a 16-bit loop, four fields a tick
    # -- which pushed the loop past the frame budget and made DESCENT run at
    # 337 ticks per 484 emulated frames.  A game that quietly runs slow is
    # exactly what p1_boot's tick-rate check exists for, and this is that same
    # check on the mode that had escaped it.
    #
    # ONE ITERATION OF SLACK, and no more, for the reason p10_camera gives for
    # its own: it is the seam, never the value.  The window opens and closes on
    # the EMULATOR's frame boundaries while the counter is the ROM's own, so an
    # iteration that starts before the first frame or ends after the last is
    # clipped by the edge of the measurement; and a free fall's heaviest tick --
    # the camera moving two rows and the ring writing two -- measured exactly
    # one such over 126 (see the second witness below).  What this rejects is
    # the P12 ROM, 147 ticks short over the same flight.
    check(rate_ok(ticks, g.u16("frame") - f0),
          "and the DESCENT loop runs ONE TICK PER EMULATED FRAME -- the contract "
          "p1_boot and p6_hud hold LANDER to, now over a world whose status bar "
          "carries three-digit readings and a camera that writes a map row every "
          "tick (%d emulated frames advanced the tick counter by %d)"
          % (ticks, g.u16("frame") - f0))

    # ---- the landing ------------------------------------------------------
    # On the DESCENT's own ground, and read out of the DESCENT profile: the
    # ship spawns over the x2 pad and never touches the stick's rotation, so
    # the column it lands in is the column it started on.  A ROM that landed it
    # on LANDER's surface would be resting 704 px higher and this compares the
    # underside against the profile's own row, not against the other world's.
    col = col_of(landed["x"])
    ground = ground_under(descent, landed["x"])
    check(landed["state"] == ST_LANDED and landed["verdict"] == LAND_SAFE,
          "and it lands rather than crashes -- state %d, verdict %d, column %d "
          "of %d" % (landed["state"], landed["verdict"], col, WORLD_COLS))
    check(landed["y"] + SHIP_H == ground and ground == descent[col] * 8
          and ground != lander[col] * 8 and landed["vy"] == 0,
          "resting ON the DESCENT world's own surface -- underside %d, and the "
          "profile puts column %d's ground at %d px (LANDER's would be %d), "
          "with nothing left over (vy %d)"
          % (landed["y"] + SHIP_H, col, ground, lander[col] * 8, landed["vy"]))
    # The multiplier against the ROM's OWN pad table AND against the literal 2,
    # for p5_landing's reason: a score hardcoded to whatever the table said
    # would pass the first comparison alone.  The pads' spans are shared by the
    # two worlds (terrain.h) and only their DEPTH differs, so this is the one
    # number a descent landing and a LANDER landing have in common.
    raw = g.var("pads", PAD_COUNT * 3)
    under = [raw[3 * i + 2] for i in range(PAD_COUNT)
             if raw[3 * i] <= col <= raw[3 * i + 1]]
    check(under and landed["mult"] == under[0] == 2,
          "and the descent's landing is SCORED -- x2 for the pad under the "
          "spawn (scored %d, the ROM's own pads table says %r)"
          % (landed["mult"], under))
    # THE FUEL, which is the mode's whole arithmetic: 752 px of air on a 600
    # unit tank is only affordable because a late brake spends about a quarter
    # of it (168 units, measured).  A tank or an air gap retuned past the edge of
    # that fails here.
    check(landed["fuel"] > 0,
          "and it was affordable -- %d of %d fuel left, so the descent is a "
          "descent and not a fall"
          % (landed["fuel"], FUEL_START))

    # ---- the camera, tick by tick ----------------------------------------
    # Every sample against the rule, and the rule written out here rather than
    # imported from sim.h: a probe that asked the ROM what its own answer
    # should be could not tell a camera whose anchor had drifted.
    #
    # ONE ITERATION OF SLACK, and no more -- p10_camera's allowance, for its
    # reason: main.c computes cam from ship.y inside the tick and these are two
    # separate reads of the emulator's memory.  The slack is in the PHASE (the
    # accepted answer is the rule at the altitude before or at the altitude
    # now) and never in the value.
    bad = []
    for k, (y1, c1, s1) in enumerate(samples):
        y0 = samples[k - 1][0] if k else y1
        c0 = samples[k - 1][1] if k else c1
        if c1 not in (want_cam(y0), want_cam(y1)) or s1 not in (c0 & 0xFF, c1 & 0xFF):
            bad.append((y0, y1, c1, s1))
    check(not bad,
          "cam is the clamp of ship_y - %d to the WORLD's bound %d -- not the "
          "map's 256 px and not the panel's %d -- at every sampled tick, and "
          "SCY is its low byte (y_prev:y:cam:scy %r)"
          % (CAM_ANCHOR, cam_max, VIEW_H_PX, bad[:4]))

    pinned_top = [c for (y, c, _s) in samples if y <= CAM_ANCHOR]
    check(len(pinned_top) >= 4 and set(pinned_top) == {0},
          "before the descent starts the camera is pinned at 0 -- %d samples at "
          "or above y %d, cam values %r"
          % (len(pinned_top), CAM_ANCHOR, sorted(set(pinned_top))))

    pinned_bot = [c for (y, c, _s) in samples if y - CAM_ANCHOR >= cam_max]
    check(len(pinned_bot) >= 4 and set(pinned_bot) == {cam_max},
          "and the approach is spent ON the bottom clamp at %d, so the view "
          "stops with the world's last row visible and not under the status "
          "bar -- %d samples at or below y %d, cam values %r"
          % (cam_max, len(pinned_bot), cam_max + CAM_ANCHOR,
             sorted(set(pinned_bot))))

    free_y = [y for (y, c, _s) in samples if 0 < c < cam_max]
    free_c = [c for (_y, c, _s) in samples if 0 < c < cam_max]
    check(len(free_c) >= 8 and all(b >= a for a, b in zip(free_c, free_c[1:]))
          and free_c[-1] - free_c[0] >= (max(free_y) - min(free_y)) - 4,
          "and between the two clamps it tracks the ship rather than holding or "
          "stepping -- %d unclamped samples, none moving back up, and the "
          "camera advanced %d px across the %d px the ship fell"
          % (len(free_c), free_c[-1] - free_c[0], max(free_y) - min(free_y)))

    # ---- the ring, across the map MORE THAN ONCE --------------------------
    # The map is 32 rows and this descent's camera rides the whole way from 0 to
    # the bottom clamp -- 85 rows of it -- so its own row crosses the ring's
    # whole height twice.  THAT is what makes the modulus a
    # claim: a band written with the wrong one -- or at a base that stops
    # following the camera -- is right for the first 256 px and then repeats a
    # stretch of the world it has already gone past, and every row of it is
    # still a tile from the right profile, so nothing but this number says so.
    tops = [c >> 3 for (_y, c, _s) in samples]
    check(min(tops) == 0 and max(tops) - min(tops) >= 2 * MAP_TILES,
          "and the flight crossed the map's whole height TWICE -- the camera's "
          "row ran %d -> %d, %d rows against a %d-row map, so the wrap is past "
          "its second crossing and not merely over the first"
          % (min(tops), max(tops), max(tops) - min(tops), MAP_TILES))
    check(bands >= 20 and not band_fails,
          "and every visible row on the way down is the profile row the camera "
          "says belongs there, on the far side of the ring's own wrap as well "
          "-- %d sampled bands, col:row:world-row:map-row:want:found %r"
          % (bands, band_fails[:3]))

    # ---- the horizontal wrap, under THIS profile --------------------------
    # A second life, because the first one ended on the pad.  The ship is flown
    # SIDEWAYS into the world -- holding RIGHT leans the nose over and the
    # sideways thruster pushes it -- so it is heading for the seam and falling
    # the whole way at once, because that push is horizontal and gravity is the
    # only thing on the vertical axis.  Every tick of it is on the DESCENT
    # profile: 752 px of air, and nothing in this flight brakes.
    g.run(8, "S")
    g.run(2)
    check(g.ship()["heading"] == 0 and g.ship()["fuel"] == FUEL_START,
          "the second life is upright and fully fuelled -- the flight below is "
          "the SIDEWAYS THRUSTER's, and a tank already spent would be a coast "
          "wearing the same wrap (heading %d, fuel %d)"
          % (g.ship()["heading"], g.ship()["fuel"]))

    xs = []
    crossings = 0               # ticks where x came back round the seam
    seam_reads = 0              # ticks the ship's centre was on the seam
    leant = 0                   # ticks the nose was leaning on the strafe
    alt_bad = []
    prev_x = None
    ticks = 0
    f1 = g.u16("frame")
    while g.ship()["state"] == ST_FLY and ticks < P13_WRAP_LIMIT:
        before = g.ship()
        g.run(1, "R")           # held: this is the sideways thruster, all of it
        ticks += 1
        s = g.ship()
        xs.append(s["x"])
        if s["heading"] == LEAN_STEPS:
            leant += 1
        # The only way x moves backwards is the seam: vx is positive for the
        # whole flight -- and CLIMBING, since nothing here lets go of it -- so a
        # step forward and a jump of ~160 back is a crossing and nothing else
        # can look like one.
        crossed = prev_x is not None and s["x"] + 16 < prev_x
        if crossed:
            crossings += 1
        prev_x = s["x"]
        # ON THE SEAM, and the ground read off the ROM's OWN HUD: what is under
        # the ship there is the column its CENTRE wrapped onto, which is the
        # second wrap -- the one inside ship_col() -- and the ALT the status bar
        # shows is the only thing here that goes through it.  The tick x came
        # back on counts as one: a ship accelerating sideways can step clean
        # OVER the seam window without ever landing inside it, and that tick is
        # the most seam-read of the lot.
        if crossed or s["x"] >= WORLD_W_PX - SHIP_W or s["x"] < SHIP_W:
            seam_reads += 1
            got = g.hud_num(HUD_ALT_ROW, HUD_ALT_COL, HUD_ALT_W)
            want = [ground_under(descent, s["x"]) - (s["y"] + SHIP_H),
                    ground_under(descent, before["x"]) - (before["y"] + SHIP_H)]
            # ONE ITERATION OF SLACK, and here it is a WIDTH rather than two
            # candidate values, because the two things the altitude is made of
            # move at very different speeds.  The GROUND under the ship is what
            # this is about -- it steps by a tile, and the value read back is
            # compared against the profile's own row through the wrapped column
            # -- but the same number also carries the ship's y, which at the
            # end of a free fall moves better than eight pixels a tick, and the
            # HUD is built inside the tick and read outside it.  So the
            # tolerance is exactly one tick of that motion, no more: what it
            # still rejects is the other profile (~700 px out, LANDER's ground
            # being 72 px down where this one is 776) and a column read past the
            # end of terrain[] rather than wrapped back onto column 0.
            tol = 1 + abs(s["y"] - before["y"])
            if got is None or min(abs(got - w) for w in want) > tol:
                alt_bad.append((s["x"], col_of(s["x"]), got, want))

    # ...and the same clock, on the flight with nothing under the ship's fall:
    # the braking descent spends most of its frames slowing down, and a free
    # fall drives the camera down two rows a tick at the end of it -- so this
    # is the second flight and the second witness, and it is the one that puts
    # the ring's row write under the most pressure.
    check(rate_ok(ticks, g.u16("frame") - f1),
          "and a free-falling DESCENT life keeps it too -- the other end of the "
          "camera's travel, where it moves two rows a tick and the ring writes a "
          "row with it (%d emulated frames advanced the tick counter by %d)"
          % (ticks, g.u16("frame") - f1))
    check(len(xs) > 8 and not any(x >= WORLD_W_PX for x in xs),
          "and every pixel of the sideways flight is inside the %d px world -- "
          "a wrap that masked at 256 would put the ship up to 96 px past the "
          "right edge, off the screen and past the last column (x ran %d..%d "
          "over %d frames)"
          % (WORLD_W_PX, min(xs), max(xs), len(xs)))
    check(max(xs) >= WORLD_W_PX - SHIP_W and min(xs) < SHIP_W,
          "and it really went round -- the ship reached the last column (x %d) "
          "and came back on at the first (x %d)" % (max(xs), min(xs)))
    check(crossings >= 2,
          "MORE THAN ONCE, so the seam is the world's edge and not a place the "
          "ship happened to stop -- %d crossings of the %d px seam over %d "
          "frames" % (crossings, WORLD_W_PX, len(xs)))
    check(leant == ticks,
          "and the nose was leaning on the strafe for every tick of it -- the "
          "push is the LEAN and not a turn-and-burn, and a ship that straightened "
          "up mid-flight would have stopped pushing with it (%d of %d ticks at "
          "heading %d)" % (leant, ticks, LEAN_STEPS))
    check(g.ship()["fuel"] > 0,
          "and the sideways thruster still had fuel at the end of the flight -- "
          "the wrap is the STRAFE's, so a tank that emptied partway would leave "
          "a coasting ship wearing it (%d of %d units left after %d ticks)"
          % (g.ship()["fuel"], FUEL_START, ticks))
    check(seam_reads >= 4 and not alt_bad,
          "and the ground under it ON the seam is the DESCENT profile's, read "
          "off the ROM's own ALT -- the column the centre WRAPPED onto, not the "
          "one past the end of terrain[] (%d seam ticks, x:col:alt:want %r)"
          % (seam_reads, alt_bad[:4]))

    # ---- the meta-assertion ----------------------------------------------
    # Every claim above is only as good as its own situation having actually
    # happened in this run, so each one reports a WITNESS -- how many times the
    # scripted flight produced what it describes -- and this is the one check
    # that they all cleared.  It is not decoration: a clamp assertion with
    # nothing clamped, a band comparison with no bands read and a seam nothing
    # crossed all PASS trivially, and each would do it silently.
    witnesses = [
        ("the camera pinned at the top of its travel", len(pinned_top), 4),
        ("the camera pinned on the bottom clamp", len(pinned_bot), 4),
        ("the camera free between the two", len(free_c), 8),
        ("bands compared", bands, 20),
        ("bands past the ring's first wrap", deep_bands, 8),
        ("rows the camera's own row crossed", max(tops) - min(tops), 2 * MAP_TILES),
        ("crossings of the horizontal seam", crossings, 2),
        ("ALT read on the seam", seam_reads, 4),
        ("the descent landed", 1 if landed["state"] == ST_LANDED else 0, 1),
    ]
    short = [w for w in witnesses if w[1] < w[2]]
    check(not short,
          "every claim above was individually reachable in this run -- each "
          "one reports how often the flight produced its own precondition, "
          "against the least that makes it mean anything (%s)"
          % ", ".join("%s %d/%d" % w for w in witnesses))


CHECKS = [("p1_boot", p1_boot), ("p2_terrain", p2_terrain),
          ("p3_gravity", p3_gravity), ("p4_thrust", p4_thrust),
          ("p5_landing", p5_landing), ("p6_hud", p6_hud),
          ("p7_sound", p7_sound), ("p9_window", p9_window),
          ("p10_camera", p10_camera), ("p11_stream", p11_stream),
          ("p12_mode", p12_mode), ("p13_descent", p13_descent)]


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
