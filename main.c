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
 * world column, sky above the surface and ground below it.
 *
 * P3 puts the ship on screen and lets go of it: sim.h's ship_step() applies
 * gravity once per tick and this file draws the sprite from the state's own
 * position bytes, so what the probe reads out of the state is what the PPU is
 * being told.
 *
 * P4 hands the ship a pilot: the JOYPAD DECODE -- held keys into sim.h's
 * SHIP_THRUST, edges into SHIP_ROT_L/R -- and one sprite tile picked from the
 * heading byte.  The rotation, the thrust vector, the burn and the gravity all
 * live in sim.h; what is left here is the wiring.
 *
 * P5 is the landing: a spawn that can be repeated, a START that repeats it, and
 * a step that freezes once the state has stopped being ST_FLY.
 *
 * P6 is the TITLE, the HUD and the state machine.  The screen stopped being one
 * thing: it is a title screen, or the play field with live telemetry over it,
 * and which one is built is the whole of what `game` decides.  Two things move
 * as a result.  The first is that the screen is now built in a BUFFER and
 * blitted whole -- the title and the play field are the same 20x18 shape and
 * one buffer serves both, so there is no second surface for them to disagree
 * on (the sibling's text() hard-coded one buffer and its text_v() another).
 * The second is that NOTHING is drawn once any more: the HUD counts down every
 * frame, so the screen changes every frame, and the sibling's screen_stale()
 * dirty gate -- which exists to skip a rebuild that would write the same bytes
 * again -- would never once fire here.
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

/* The visible window: 20x18 tiles, and the ONLY stride in this file.  The PPU's
 * map is 32 wide, but there is no scroll yet, so the 20x18 at (0,0) is the
 * whole of what a player can see and the whole of what this file writes. */
#define VIEW_W 20
#define VIEW_H 18

/* Which screen this iteration builds.  ST_TITLE and ST_PLAY are this file's;
 * the other two states the game has are sim.h's ST_CRASH and ST_LANDED, and
 * they are reused rather than shadowed here because once the life is over the
 * SHIP's state IS the screen's: a second pair of constants saying the same
 * thing is a pair that can disagree with the first, and only one of them would
 * be telling the truth. */
#define ST_TITLE 0
#define ST_PLAY  1

/* The two modes the title offers.  The DESCENT half is INERT in P6: SELECT
 * flips this byte and the title says so, and nothing else reads it -- M2 is
 * where START starts reading it and the second game exists.  Wiring it here
 * would mean shipping a mode line that promised a game that is not there. */
#define MODE_LANDER  0
#define MODE_DESCENT 1

/* The title row the mode line sits on, named because it is also the ONE row a
 * SELECT press re-sends -- see the loop: re-blasting the whole title for a line
 * that changed would be a 20x18 map write for 20 tiles. */
#define MODE_ROW 7

/* One loop iteration IS one tick.  wait_vbl_done() paces the loop, so there is
 * no dt accumulator and none may be added: physics runs once per iteration and
 * one iteration is one ~16.7 ms frame.  probe.p1_boot reads this out of
 * luna.map -- statics live in main.c for that reason, and `Fmain$` in the map
 * is where it finds them -- and asserts it advances by exactly one per emulated
 * frame. */
static uint16_t frame;

/* This tick's joypad poll, the one before it, and the edge between them.
 *
 * `pressed` is `keys & ~prev_keys`, and the split matters: START/A/B/SELECT are
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
 * 7 is clear here, and the write that sample covers is now the first screen's
 * blit below -- which is the point: every VRAM byte the first frame shows is
 * behind it. */
static uint8_t lcdc_at_load;

/* Which screen is being built.  See ST_TITLE / ST_PLAY above.  probe.p6_hud
 * reads this byte out of the map: "the title is up" and "the title is cleared"
 * are claims about a value, not about a picture. */
static uint8_t game;

/* The title's mode selection.  INERT until M2 -- see MODE_* above.
 *
 * `pick` and not `mode`: gb/gb.h declares a mode() of its own (the display-mode
 * request), and the linker sees one symbol, not one per translation unit. */
static uint8_t pick;

/* The visible screen, 20x18 tile ids, rebuilt from scratch EVERY frame and
 * blitted whole.  ONE buffer for both screens, deliberately: the title is a
 * 20x18 field of tiles and so is the play field, and the only thing a second
 * buffer buys is a way for the two to be filled in the wrong order.
 *
 * The title is built here at boot and blitted before DISPLAY_ON, because "the
 * tiles go up with the display off" is about every byte of the first frame, not
 * just the bank: a map written after the display came on would leave the first
 * frame showing whatever the PPU found in VRAM.  After that the buffer is
 * rewritten in place each tick and the VRAM write happens after wait_vbl_done()
 * -- the sibling's ordering, where the map write lands in the vblank window
 * rather than being dropped by the PPU mid-scanline. */
static uint8_t bg[VIEW_W * VIEW_H];

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
 * than a coin toss.  It is also below the HUD strip's two rows (16 px), so the
 * telemetry does not sit on top of the ship it is reporting on. */
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

/* ------------------------------------------------------------------ text */

/* One character -> one BG tile id.  Anything outside A-Z and 0-9 is BLANK,
 * which is what a space should be and is also the failure mode to watch: a
 * lowercase literal, or a '-' in a string, draws NOTHING, so the row is short
 * by however many characters went missing and it reads as a layout bug rather
 * than as a character the font does not have.  gfx.h's T_MINUS and the signed
 * numbers below are the one place that matters; a new punctuation character in
 * a literal needs a tile here first. */
static uint8_t glyph(char c)
{
    if (c >= 'A' && c <= 'Z') return (uint8_t)(T_LETTER0 + (c - 'A'));
    if (c >= '0' && c <= '9') return (uint8_t)(T_DIGIT0 + (c - '0'));
    if (c == '-')             return T_MINUS;
    return T_BLANK;
}

/* A string into the screen buffer at (col,row), one tile per character.
 *
 * The BUFFER is a parameter.  The sibling hard-coded its board buffer in text()
 * and its HUD buffer in text_v(); a third surface in this project is what that
 * costs, so the buffer is passed and the stride is the one this file has
 * (VIEW_W).  There is no vertical twin either: the HUD is a two-row strip of
 * the same 20-wide buffer, and a text_v() that walked a column would be a
 * second function no caller in this file ever wants. */
static void text(uint8_t *buf, uint8_t col, uint8_t row, const char *s)
{
    uint8_t *p = &buf[(uint16_t)row * VIEW_W + col];

    while (*s)
        *p++ = glyph(*s++);
}

/* `v` as `w` digits, right-aligned in the buffer at p, blank-padded; a negative
 * v spends none of the width on its sign, it just replaces the leftmost blank.
 *
 * REPEATED SUBTRACTION, never `v / 10`.  Ten is not a power of two, so SDCC
 * turns that divide into a call to __divuint -- the same trap GRAV and THRUST
 * are shaped around -- and the values here are at most three digits, so the
 * loop is at worst sixty turns of a byte compare.  It runs at most four times a
 * tick.
 *
 * `w` is the whole of the field, so it also CAPS what is shown: a one-wide
 * field prints the last digit and nothing above it, which is right for the
 * pad's multiplier (terrain.h's pads are x1 and x2) and wrong for anything a
 * value could grow past -- widen the field before letting one.  `w` is never 0,
 * or the digit loop would write one tile left of the field. */
static void dec(uint8_t *p, uint8_t w, int16_t v)
{
    uint8_t i = w, neg = 0;

    if (v < 0) {
        neg = 1;
        v = (int16_t)(-v);
    }
    while (i)
        p[--i] = T_BLANK;
    i = w;
    for (;;) {
        uint8_t q = 0;

        while (v >= 10) { v = (int16_t)(v - 10); q++; }
        p[--i] = (uint8_t)(T_DIGIT0 + (uint8_t)v);
        if (i == 0)
            break;
        v = q;
    }
    if (neg)
        p[0] = T_MINUS;
}

/* 8.8 px/frame -> whole px/frame, truncating toward zero.  NOT `v >> 8`, which
 * on SDCC is an arithmetic shift and therefore FLOORS: -100 (four tenths of a
 * pixel a frame, upward) would read -1 and the HUD would say the ship is
 * climbing while it is coming down.  The magnitudes here are a few thousand, so
 * negating one cannot overflow int16_t. */
static int16_t px_per_frame(int16_t v)
{
    return (int16_t)(v < 0 ? -(int16_t)(-v >> 8) : (int16_t)(v >> 8));
}

/* ---------------------------------------------------------------- drawing */

/* Put the sprite where the ship is and at the heading it is pointing -- called
 * once per tick in play, always straight from the state so the offset is
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

/* Off the screen, for the title.  OAM y = 0 is one of the two rows the DMG
 * never draws (the other is 160), so this hides the sprite rather than parking
 * it at a corner: the ship has no position on the title -- it is not falling
 * behind it -- and a sprite left where the spawn put it would sit on top of the
 * title text. */
static void ship_hide(void)
{
    move_sprite(SPR_SHIP0, 0, 0);
}

/* Blank every cell of the buffer.  T_BLANK is the paper tile, so this is also
 * what puts the sky back. */
static void bg_clear(void)
{
    uint16_t i;

    for (i = 0; i < VIEW_W * VIEW_H; i++)
        bg[i] = T_BLANK;
}

/* FUEL, ALT and the two velocities, over the top two rows of the play field.
 * Those rows are sky in every column -- terrain.h's highest surface is row 9 --
 * so the HUD never covers the ground it is reporting on and nothing under it
 * has to be redrawn.
 *
 * This, and NOT the whole screen, is what the tick loop rebuilds.  A tilemap
 * write costs the PPU window it has to wait for -- the display is on, so
 * set_bkg_tiles can only put its bytes down in the blanking interval -- and a
 * 20x18 blit measures at about three frames on this machine.  The terrain does
 * not move, so it is written once (build_field(), blitted when the title is
 * cleared) and the 40 tiles that DO change are written every tick, which fits
 * the frame with room to spare.  The tick loop's own frame-rate assertion in
 * probe.p6_hud is what holds that: this is the phase that made the loop draw,
 * so it is the phase that has to keep one iteration equal to one tick.
 *
 * Every number here is read out of the ship struct the same tick it is drawn --
 * never latched, never a counter of this file's own -- which is why the screen
 * and probe.p6_hud's reading of the STATE have to agree: a HUD fed by a copy
 * would drift from the physics with nothing on screen saying so.
 *
 * ALT is the gap between the ship's UNDERSIDE and the surface under it, in px:
 * the same two quantities sim.h's contact test subtracts, in the same units (so
 * the one `<< 3` out of terrain[]'s tile rows is here, and everywhere else in
 * this file heights stay in the units terrain.h stores them in).  A live
 * altitude, then, and not a depth fallen -- it reads 0 the tick the ship
 * touches down, on a pad or in a crater alike. */
static void build_hud(void)
{
    uint8_t i;
    uint8_t col = ship_col(ship.x);
    int16_t alt = (int16_t)((int16_t)(terrain[col] << 3) -
                            (int16_t)(ship.y + SHIP_H));

    text(bg, 0, 0, "FUEL ");
    dec(&bg[5], 3, (int16_t)ship.fuel);
    text(bg, 9, 0, "ALT ");
    dec(&bg[13], 3, alt);

    /* The second row is CLEARED before it is written, and it has to be: its
     * three readings are not the same length -- "CRASHED" is seven tiles and
     * "LANDED X2" nine, against the velocity row's thirteen -- so a life that
     * ends and is restarted would leave the tail of the longer string sticking
     * out behind the shorter one.  Row 0 is one fixed layout thirteen tiles
     * wide and has nothing to clear. */
    for (i = 0; i < VIEW_W; i++)
        bg[VIEW_W + i] = T_BLANK;

    /* The row's offsets are VIEW_W into the buffer: same layout, one row down.
     * Velocities are whole px/frame, so vx/vy read 0 until the ship is moving a
     * whole pixel a tick -- a tenth of a pixel is under the resolution of a
     * two-digit field, and 8.8's raw units would not fit one. */
    if (ship.state == ST_FLY) {
        text(bg, 0, 1, "VX ");
        dec(&bg[VIEW_W + 3], 3, px_per_frame(ship.vx));
        text(bg, 7, 1, "VY ");
        dec(&bg[VIEW_W + 10], 3, px_per_frame(ship.vy));
    } else if (ship.state == ST_LANDED) {
        text(bg, 0, 1, "LANDED X");
        dec(&bg[VIEW_W + 8], 1, (int16_t)ship.mult);
    } else {
        text(bg, 0, 1, "CRASHED");
    }
}

/* The play field's STATIC half: sky, and the height profile out of terrain.h.
 *
 * terrain[col] is a TILE row, not a pixel row -- the 8 px tile mkgfx.py draws
 * the art in -- so there is no `<< 3` anywhere here.  A `<< 3` is the classic
 * "heights are pixels" slip and it would drop the ground eight rows and push
 * the bottom of it off the screen, which still LOOKS like terrain.
 *
 * There is no camera yet, so world column N IS screen column N and the whole
 * 160 px world is on screen at once.
 *
 * The buffer is walked with an index that STEPS by the stride rather than one
 * recomputed per cell: VIEW_W is 20, which is not a power of two, and `r *
 * VIEW_W` inside this loop is a multiply per tile.  A stride this file cannot
 * shift is a stride to add, not to multiply by.
 *
 * Called ONCE, when the title is cleared -- see the write below -- because this
 * is the half of the screen that does not move. */
static void build_field(void)
{
    uint8_t col, top, r;
    uint16_t i;

    bg_clear();

    for (col = 0; col < WORLD_COLS; col++) {
        top = terrain[col];                 /* surface row, tile units */

        /* A surface below the view has no tile to put on screen.  M1's profile
         * never reaches this; M2's DESCENT does. */
        if (top >= VIEW_H)
            continue;

        i = (uint16_t)(top * VIEW_W + col);
        bg[i] = T_TERRAIN_TOP;
        for (r = (uint8_t)(top + 1); r < VIEW_H; r++) {
            i = (uint16_t)(i + VIEW_W);
            bg[i] = T_TERRAIN;
        }
    }
}

/* The title: the name, the mode it is offering, and how to start.
 *
 * The strings are centred by hand (11 or 12 tiles in a 20-wide field, so they
 * start at column 4) because the font has no proportional widths and a centring
 * routine for four fixed strings would be three more lines of arithmetic than
 * the four literals it replaces. */
static void build_title(void)
{
    bg_clear();
    text(bg, 4, 4, "LUNA LANDEER");
    text(bg, 4, MODE_ROW, pick == MODE_LANDER ? "MODE LANDER" : "MODE DESCENT");
    text(bg, 4, 10, "SELECT MODE");
    text(bg, 4, 12, "PRESS START");
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

    /* The screen machine starts on the title, on the one mode that exists. */
    game = ST_TITLE;
    pick = MODE_LANDER;

    /* The ship, before the display goes on.  ship_init() rather than a brace
     * initialiser on the declaration, because START has to reach exactly this
     * state from inside the tick loop and two copies of the spawn would drift
     * -- and the one that drifted would be the one nobody restarts from. */
    ship_init();

    /* The FIRST frame, built and blitted with the display still off.  The last
     * VRAM write in the boot is this blit, so the LCDC sample below covers the
     * tile banks and the map alike -- see lcdc_at_load. */
    build_title();
    set_bkg_tiles(0, 0, VIEW_W, VIEW_H, bg);

    lcdc_at_load = LCDC_REG;

    /* OAM is not screen space: the PPU draws an 8x8 sprite with its top-left at
     * (OAM_x - 8, OAM_y - 16).  move_sprite() writes the raw bytes and does NOT
     * add it, so the +8/+16 is the caller's job in ship_draw() -- leave it out
     * and the ship flies eight pixels left and sixteen above where the physics
     * says it is, which is a plausible-looking bug with no other symptom. */
    ship_hide();

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

        /* The title.  SELECT is the mode toggle and this is the only place it
         * exists: a game never swaps underneath the player once it is running.
         * An EDGE, so holding it does not flip the mode every tick.
         *
         * A press re-sends the ONE row that changed rather than the screen: the
         * title is otherwise still, and a 20x18 map write is a three-frame
         * stall -- worth paying once, at boot and at the hand-over to the field,
         * and not worth paying because somebody tapped SELECT. */
        if (game == ST_TITLE) {
            if (pressed & J_SELECT) {
                pick = (uint8_t)(pick ^ 1);
                build_title();
                set_bkg_tiles(0, MODE_ROW, VIEW_W, 1, &bg[MODE_ROW * VIEW_W]);
            }
            /* START clears the title.  The play branch below runs on the SAME
             * tick, and its own `pressed & J_START` is what calls ship_init()
             * -- so the spawn still exists in exactly one place, and the ship
             * starts falling on the tick the title goes away rather than one
             * later. */
            if (pressed & J_START) {
                game = ST_PLAY;
                /* The field, written whole and ONCE: it does not move, and this
                 * is the only tick it has to reach the PPU on.  The buffer is
                 * built here and the map write happens after it, so the
                 * hand-over frame shows the field with the HUD already on it
                 * rather than a frame of bare terrain. */
                build_field();
                set_bkg_tiles(0, 0, VIEW_W, VIEW_H, bg);
            }
        }

        if (game == ST_PLAY) {
            /* Decode the pad into sim.h's flags.  UP is thrust (held: `keys`),
             * A and B are the two rotation steps (one-shot: `pressed`) -- A
             * turns the nose one step anticlockwise and B clockwise, so they
             * undo each other exactly. */
            input = 0;
            if (keys & J_UP)    input |= SHIP_THRUST;
            if (pressed & J_A)  input |= SHIP_ROT_L;
            if (pressed & J_B)  input |= SHIP_ROT_R;

            /* START restarts the life -- after a crash, after a landing, or
             * mid-flight if the player simply wants another go.  An EDGE and
             * not a level, like A and B: read `keys` here and holding START
             * would reset the ship on every tick, so it would never fall at all
             * and the game would look frozen rather than restarted.  It is
             * also what seats a fresh ship on the tick the title is cleared. */
            if (pressed & J_START)
                ship_init();

            /* One iteration IS one tick.  Physics runs once here, unpaced by
             * any dt accumulator, because wait_vbl_done() below already puts
             * the loop at one iteration per ~16.7 ms frame. */
            ship_step(&ship, input);

            /* The HUD, and only the HUD -- the terrain underneath it was
             * written when the field was handed over and has not moved since.
             * There is no dirty flag anywhere in this file: the strip is built
             * from the state and sent on EVERY tick, because the numbers in it
             * change on every tick, and a gate that had to notice that would be
             * a gate that is always open. */
            build_hud();

            /* Drawn from the state, every tick.  A renderer that kept its own
             * copy of the position would drift from the physics and nothing on
             * screen would ever say so; probe.p3_gravity asserts the sprite's
             * OAM bytes and the state's own agree instead. */
            ship_draw();
        }

        frame++;
        wait_vbl_done();

        if (game == ST_PLAY) {
            /* Two rows of twenty tiles, one wait each for the PPU's blanking
             * window.  The tilemap this lands in is the one the NEXT frame's
             * reads see, which is the same one-vblank relationship the shadow
             * OAM has had since P3 -- and the reason probe.p6_hud allows the
             * screen's numbers to be one tick behind the state's. */
            set_bkg_tiles(0, 0, VIEW_W, 2, bg);
        }
    }
}
