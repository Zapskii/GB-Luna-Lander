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
 */
#include <gb/gb.h>
#include <stdint.h>

#include "gfx.h"
#include "sim.h"
#include "terrain.h"

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

/* This tick's joypad poll.  Nothing branches on it yet; P4/P6 read it (and
 * `pressed`, which is `keys & ~prev_keys`). */
static uint8_t keys;

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
 * Spawn is the top of the screen, mid-world -- LANDER's world is exactly one
 * 160 px screen wide, so world x and screen x are the same number and 80 IS
 * the middle.  From rest: no thrust, no rotation, nothing to press. */
static Ship ship = { 80, 16, 0, 0, 0, 0 };

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

/* Put the sprite where the ship is -- called at boot and once per tick, always
 * straight from the state so the offset is written down exactly once.  The
 * ship's top-left is (x, y); the OAM bytes are (x + 8, y + 16). */
static void ship_draw(void)
{
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

    set_sprite_tile(SPR_SHIP0, SPR_SHIP0);      /* heading 0: level flight */

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

        /* One iteration IS one tick.  Physics runs once here, unpaced by any
         * dt accumulator, because wait_vbl_done() below already puts the loop
         * at one iteration per ~16.7 ms frame -- adding one would run the
         * physics twice as fast as the wall clock on every machine. */
        ship_step(&ship);

        /* Drawn from the state, every tick.  A renderer that kept its own copy
         * of the position would drift from the physics and nothing on screen
         * would ever say so; the probe asserts these two agree instead. */
        ship_draw();

        frame++;
        wait_vbl_done();
    }
}
