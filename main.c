/* LUNA LANDEER -- main.c
 *
 * Hardware only: boot, the tick loop, and the drawing that has to go through
 * gb/gb.h.  Every rule (gravity, thrust, the landing verdict) belongs in sim.h
 * so tests/test_sim.c can compile it with plain gcc, and this file owns the
 * storage those rules operate on.  Nothing else in the project includes gfx.h:
 * a `static const` in a header is duplicated into every translation unit that
 * includes it.
 *
 * P1 is the toolchain probe.  The ROM boots, the generated tiles and the ship
 * sprite land in VRAM, the BG map is filled with the terrain tile, and `frame`
 * advances once per emulated frame.
 *
 * P2 blits the generated height profile over that fill: one tilemap column per
 * world column, sky above the surface and ground below it.  Still no camera,
 * no ship and no collision -- the profile and the screen are what this phase
 * has to agree about.
 *
 * P3 puts the ship on screen and lets go of it: sim.h's ship_step() applies
 * gravity once per tick and this file draws the sprite from the state's own
 * position bytes, so what the probe reads out of the state is what the PPU is
 * being told.  P3 has no camera and no wrap -- the ship falls off the bottom
 * of a 144 px screen and keeps counting, because a landing verdict is P5's and
 * collision is P4's.
 *
 * P4 hands the ship a pilot.  This file's whole share of that is the JOYPAD
 * DECODE -- held keys into sim.h's SHIP_THRUST, edges into SHIP_ROT_L/R -- and
 * one sprite tile picked from the heading byte.  The rotation, the thrust
 * vector, the burn and the gravity all live in sim.h so tests/test_sim.c can
 * run them without an emulator; what is left here is the wiring, which is
 * exactly the half that probe.p4_thrust covers and the host cannot see.
 *
 * P5 is the landing.  The rule -- where the ship stands, what the ground under
 * it is, how fast and how upright it arrived, and the pad multiplier that
 * earns -- is entirely in sim.h, where tests/test_sim.c can straddle every
 * threshold.  This file's share is three lines of wiring: a spawn that can be
 * repeated, a START that repeats it, and a step that freezes once the state
 * has stopped being ST_FLY.  Nothing here decides whether a landing was good.
 */
#include <gb/gb.h>
#include <stdint.h>

#include "gfx.h"
#include "sim.h"
#include "terrain.h"

/* Heading selects sprite tile SPR_SHIP0 + heading, and sim.h masks it to
 * 0..ROT_STEPS-1.  If the sprite bank ever held fewer tiles than there are
 * headings that index runs off the end of gfx_sprites[] into whatever follows
 * it and the ship draws as garbage; a build error beats that. */
typedef char ship_frames_fit[(ROT_STEPS <= GFX_SPRITE_COUNT) ? 1 : -1];

/* The BG tilemap.  The PPU's is 32x32 regardless of what the 20x18 window
 * shows, and P2 blanks all of it: a later scroll brings in sky, not whatever
 * was left in VRAM. */
#define MAP_W 32
#define MAP_H 32
#define VIEW_H 18

/* One loop iteration IS one tick.  wait_vbl_done() paces the loop, so there is
 * no dt accumulator and none may be added: physics runs once per iteration and
 * one iteration is one ~16.7 ms frame.  probe.p1_boot reads this out of
 * luna.map -- statics live in main.c for that reason, and `Fmain$` in the map
 * is where it finds them -- and asserts it advances by exactly one per emulated
 * frame.  That assertion is also the frame-rate check: a frame that overruns
 * the budget halves the game and shows up here as frame advancing 0, not 1. */
static uint16_t frame;

/* This tick's joypad poll, the one before it, and the edge between them.
 *
 * `pressed` is `keys & ~prev_keys`, and the split matters: START/A/B are
 * ONE-SHOTS and read `pressed`, so holding B steps the heading once instead of
 * spinning the ship a whole revolution, while thrust reads `keys` so a held
 * button keeps burning fuel.  GBDK's joypad() is a raw read of the current
 * state -- it does not do this for you -- so `prev_keys` has to be in main.c's
 * storage, next to `keys`, and nowhere else. */
static uint8_t keys, prev_keys, pressed;

/* This tick's decoded pad.  A file-scope static and NOT a local of main()'s,
 * which is the shape it wants to be and is also load-bearing:
 *
 * A local of main's lives at SP+0, and SDCC reaches it with `ldhl sp, #0` --
 * an instruction that loads HL, and therefore H.  The decode below parks
 * `pressed` in H to bit-test it, and SDCC's register allocator does not see
 * the `ldhl sp, #n` that the peephole pass inserts AFTER it: H is assumed
 * still live and the next test reads the STACK POINTER's high byte instead of
 * the pad.  On a DMG SP is ~0xDFxx, so bit 7 of that byte is SET and
 * `if (pressed & J_START)` fired on every tick that pressed had bit 5 -- the B
 * button restarted the game while the code looked obviously correct, and the
 * same clobber makes the A test read the wrong byte too.
 *
 * A static gets `ld hl, #_input` instead, an ordinary load the allocator
 * tracks, so it reloads `pressed` rather than trusting H.  If this ever
 * becomes a local again, dump `lcc -S` and check for `ldhl sp, #0` between the
 * decode and the START test. */
static uint8_t input;

/* The family's VRAM lock, as a value tools/probe.py can read back.
 *
 * The PPU locks VRAM while the display is on, so every tile write has to happen
 * with it off -- load the data first, DISPLAY_ON last.  PyBoy does NOT model
 * that lock, which means a DISPLAY_ON placed too early renders identically
 * under the emulator and nothing about the finished screen can tell the two
 * orders apart.  Sampling LCDC at the last VRAM write is what makes the order
 * observable: this IS the order, not a proxy for it.  probe.p1_boot asserts bit
 * 7 is clear here. */
static uint8_t lcdc_at_load;

/* The ship.  THE FRACTION BYTES (xf/yf) LIVE IN HERE AND NOT IN ship_step()'s
 * locals: fix_step() carries the sub-pixel remainder between ticks, and a
 * local would reset it every tick, quantising the motion to whole pixels.  The
 * probe reads y and yf straight out of luna.map, so where this struct lives is
 * part of P3's contract, not an implementation detail.
 *
 * main.c owns the storage; ship_init() below is the only thing that ever
 * writes a fresh one, so the spawn exists in exactly one place. */
static Ship ship;

/* Where a life starts: high above the x2 pad, at rest, nose up, full tank.
 *
 * DIRECTLY over a pad, and over the x2 one, both on purpose.  P5's deliverable
 * is "a hard drop crashes, a soft landing on a pad succeeds" -- that is a
 * DESCENT, not a flight -- so the ship starts where the landing is rather than
 * somewhere it would first have to be flown to, and the whole of the skill is
 * arriving slowly.  The x2 pad and not the x1 one so the multiplier a good
 * landing scores is 2: a score that was hardcoded instead of read out of
 * terrain.h's pads[] could not fake it.
 *
 * x = 108 puts the ship's CENTRE -- what sim.h's ship_col() tests, x + SHIP_W/2
 * -- on column 14, inside PAD_HIGH's 13..14, with eight whole pixels of slack
 * either side.  y = 16 puts the ship's UNDERSIDE 48 px above that pad's
 * surface, which from rest arrives at about 620/256 px/frame: nearly five
 * times SAFE_VY_MAX, so a drop with no hand on the stick is a crash rather
 * than a coin toss. */
#define SPAWN_X 108
#define SPAWN_Y 16

static void ship_init(void)
{
    ship.x = SPAWN_X;
    ship.y = SPAWN_Y;
    ship.xf = 0;
    ship.yf = 0;
    ship.vx = 0;
    ship.vy = 0;
    ship.heading = 0;
    ship.fuel = FUEL_START;
    ship.state = ST_FLY;
    /* Nothing has touched down yet, and SAFE is 0 rather than a claim: the
     * state byte is what says whether this means anything. */
    ship.verdict = LAND_SAFE;
    ship.mult = 0;
}

/* Blit the level surface into the BG tilemap: one tilemap column per world
 * column.  There is no camera yet, so world column N IS screen column N and the
 * whole 160 px world is on screen at once.
 *
 * terrain[col] is a TILE row, not a pixel row -- the 8 px tile mkgfx.py draws
 * the art in -- so there is no `<< 3` anywhere here.  A `<< 3` is the classic
 * "heights are pixels" slip and it would drop the ground eight rows and push
 * the bottom of it off the screen, which still LOOKS like terrain.
 */
static void draw_terrain(void)
{
    uint8_t col, top;

    /* Sky first, the whole 32x32 map: T_BLANK is tile 0, so this leaves the
     * paper behind everything the surface does not cover. */
    fill_bkg_rect(0, 0, MAP_W, MAP_H, T_BLANK);

    for (col = 0; col < WORLD_COLS; col++) {
        top = terrain[col];                     /* surface row, tile units */

        fill_bkg_rect(col, top, 1, 1, T_TERRAIN_TOP);

        /* Guarded: a surface on the last view row leaves no body to draw, and
         * a zero-height fill_bkg_rect is a map address walked for nothing. */
        if (top + 1 < VIEW_H)
            fill_bkg_rect(col, top + 1, 1, VIEW_H - 1 - top, T_TERRAIN);
    }
}

/* Put the sprite where the ship is and at the heading it is pointing -- called
 * at boot and once per tick, always straight from the state so the offset is
 * written down exactly once.  The ship's top-left is (x, y); the OAM bytes are
 * (x + 8, y + 16).
 *
 * The FRAME comes out of the same heading byte the thrust VECTOR does, so the
 * nose on screen is always the direction the physics is accelerating: a
 * renderer that tracked its own frame would look right while thrusting
 * sideways, and nothing on screen would say so. */
static void ship_draw(void)
{
    set_sprite_tile(SPR_SHIP0, (uint8_t)(SPR_SHIP0 + ship.heading));
    move_sprite(SPR_SHIP0, (uint8_t)(ship.x + 8), (uint8_t)(ship.y + 16));
}

void main(void)
{
    DISPLAY_OFF;

    /* set_bkg_data/set_sprite_data take a tile COUNT, not a last id: passing 0
     * loads all 256. */
    set_bkg_data(0, GFX_TILE_COUNT, gfx_tiles);
    set_sprite_data(0, GFX_SPRITE_COUNT, gfx_sprites);

    /* 0xE4: colour 0 is the paper and colour 3 the ink, the ramp mkgfx.py draws
     * against.  OBJ has its own register, and powering up leaves it to crt0. */
    BGP_REG = 0xE4;
    OBP0_REG = 0xE4;

    draw_terrain();

    /* The LAST VRAM write, so this one sample covers all of them: if the
     * display went on at any point before this line, bit 7 is set here.  It has
     * to come after draw_terrain(), which is the last thing that touches VRAM. */
    lcdc_at_load = LCDC_REG;

    /* The ship, before the display goes on.  ship_init() rather than a brace
     * initialiser on the declaration, because START has to reach exactly this
     * state from inside the tick loop and two copies of the spawn would drift
     * -- and the one that drifted would be the one nobody restarts from. */
    ship_init();

    /* OAM is not screen space: the PPU draws an 8x8 sprite with its top-left at
     * (OAM_x - 8, OAM_y - 16).  move_sprite() writes the raw bytes and does NOT
     * add it, so the +8/+16 is the caller's job -- leave it out and the ship
     * flies eight pixels left and sixteen above where the physics says it is,
     * which is a plausible-looking bug with no other symptom. */
    ship_draw();

    SHOW_BKG;
    SHOW_SPRITES;

    /* GBDK does NOT copy the shadow OAM to 0xFE00 unless a VBL handler is
     * running, and crt0 leaves IE masked -- so without this the sprite exists
     * only in WRAM and move_sprite() is a write to nowhere.  The standard VBL
     * handler does the copy; wait_vbl_done() is the same one-tick-per-
     * iteration wait either way (it polls LY when interrupts are masked and
     * halts when they are not), so the tick invariant in p1_boot is untouched.
     * Everything above is VRAM/OAM data and this is the last line before the
     * display goes on. */
    set_interrupts(VBL_IFLAG);
    DISPLAY_ON;

    while (1) {
        keys = joypad();

        /* The edge, taken here and stored: `pressed` is what is down now that
         * was not down last tick.  Recomputing it anywhere else -- or keeping
         * it in a local -- would lose it across the wait_vbl_done() below. */
        pressed = (uint8_t)(keys & ~prev_keys);
        prev_keys = keys;

        /* Decode the pad into sim.h's flags.  UP is thrust (held: `keys`), A
         * and B are the two rotation steps (one-shot: `pressed`) -- A turns
         * the nose one step anticlockwise and B clockwise, so they undo each
         * other exactly.  This is the whole of main.c's share of P4; sim.h
         * does everything that follows from it. */
        input = 0;
        if (keys & J_UP)    input |= SHIP_THRUST;
        if (pressed & J_A)  input |= SHIP_ROT_L;
        if (pressed & J_B)  input |= SHIP_ROT_R;

        /* START restarts the life -- after a crash, after a landing, or
         * mid-flight if the player simply wants another go.  An EDGE and not a
         * level, like A and B: read `keys` here and holding START would reset
         * the ship on every tick, so it would never fall at all and the game
         * would look frozen rather than restarted. */
        if (pressed & J_START)
            ship_init();

        /* One iteration IS one tick.  Physics runs once here, unpaced by any
         * dt accumulator, because wait_vbl_done() below already puts the loop
         * at one iteration per ~16.7 ms frame -- adding one would run the
         * physics twice as fast as the wall clock on every machine, and would
         * burn the tank twice as fast with it. */
        ship_step(&ship, input);

        /* Drawn from the state, every tick.  A renderer that kept its own copy
         * of the position would drift from the physics and nothing on screen
         * would ever say so; the probe asserts these two agree instead. */
        ship_draw();

        frame++;
        wait_vbl_done();
    }
}
