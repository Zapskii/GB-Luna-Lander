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
 *
 * P7 is the sound: a burn on CH1, a landing on CH2, a crash on CH4, and the
 * three APU boot writes that make any of them audible at all -- see the sound
 * section below, and the essay on the boot lines for why silence here has no
 * diagnostic.
 *
 * P9 is the second profile and the WINDOW.  terrain.h stopped being one world:
 * it is two profiles over the same twenty columns -- LANDER's, one screen
 * tall, and the DESCENT's, a hundred tiles deep -- and ONE `terrain` pointer
 * that says which is live.  A pointer and not a name per mode, because sim.h's
 * collision and tools/probe.py both read that symbol, and two names would put
 * the screen and the physics on different worlds.  What the renderer gained is
 * blit_window(): the visible 18 rows come from a world ROW OFFSET, which is
 * the only way a profile taller than the BG map can be drawn at all.  P9 calls
 * it once, at a fixed offset, before any motion exists to confuse it.
 *
 * P10 is the CAMERA.  sim.h's camera_for() says which world row the top of the
 * screen sits on, and SCY is written from it in the vblank -- so the world moves
 * under a ship that does not, and the tall DESCENT profile becomes a view you
 * travel through instead of one screen you look at.  Two things follow that are
 * easy to half-do: the sprite has to have the camera SUBTRACTED from its y, or
 * the ship slides off the top at exactly the speed the view scrolls (SCY moves
 * the background and nothing else); and the clamp has to be on the WORLD's
 * bounds and not the BG map's 256 px, or the scroll stops 600 px short of the
 * ground while every frame still looks like a working camera.  LANDER is
 * untouched by either: its world is 104 px, shorter than the screen, so its
 * camera is pinned at 0 and its view is exactly what P9 drew.
 *
 * P11 is the RING.  P10's camera says which world row the top of the screen
 * shows and SCY really does scroll, but the BG map is 32 rows -- 256 px --
 * against a DESCENT world of 808, so the tiles under the scroll are the ones
 * P9 parked there and everything past the 18th row is blank.  What the map
 * becomes is a RING over the world: map row (world_row & 31) holds that world
 * row, and the row the camera has just uncovered is written into the slot the
 * row 32 rows above it vacated, one row per vblank.  That is what makes a 101-row
 * world fit a 32-row map, and it is why the modulus is the whole of the phase:
 * a ring written with the wrong one -- or with a base that does not stay level
 * with the camera -- scrolls perfectly for 256 px and then repeats, which
 * reads as a scrolling bug and is not one.
 *
 * TWO THINGS FALL OUT OF IT.  The first is the HUD: it is two rows of BG MAP,
 * so the two map rows the camera sits on hold telemetry and not terrain, and
 * they have to be written at the rows the CAMERA puts them on rather than at
 * rows 0 and 1 -- a HUD nailed to rows 0 and 1 is right for one scroll
 * position and then tracks the camera up the screen and wraps.  The second is
 * that the ring owes those two rows back: walking back UP the world drags the
 * covered rows down into the terrain, so the row leaving the strip is redrawn
 * -- see ring_stream().  And DESCENT no longer opens on P9's hand-wound row
 * 84: a life opens at the top of a world it has to fall through, which is what
 * a descent is, and the streaming is what puts the ground under it on the way
 * down.
 *
 * P12 is the MODES and the STATUS BAR.  The title's SELECT really does choose
 * which game START starts: P9 pointed `terrain` at the profile and P10 took the
 * world's height from it, so the two modes have been genuinely different worlds
 * since then -- this is the phase that says so, derives BOTH from the one `pick`
 * byte at BOOT rather than only at the hand-over, and gives the title's DESCENT
 * half a game rather than a promise.
 *
 * The status bar is the half that had to be rebuilt.  P11's HUD was two rows of
 * the BG MAP at the camera's own rows, and that is not enough: a BG row is
 * scrolled by the SAME SCY as the terrain, so its screen position is
 * `map_row * 8 - SCY`, which is 0 only while `cam % 8 == 0`.  The rest of the
 * time the strip is clipped by up to seven pixels and, when the map row and SCY
 * disagree by a tile, carried wholly off the top -- measured on P11's ROM over
 * 300 DESCENT frames, both HUD rows were up on 197 of them and only the bottom
 * one on 99.  LANDER never showed it because its camera is pinned at 0.  NO map
 * row is the right answer; the fix is a POLICY, and the family's is the WINDOW
 * layer, which SCY does not touch.  So the telemetry is a status bar: win rows
 * 0-1 at WY = PLAY_H, and the terrain scrolls underneath it untouched.
 *
 * TWO THINGS FALL OUT OF THAT.  The first is that the window always runs to the
 * bottom-right corner, so the bar COVERS the last two rows of background: the
 * camera's bottom clamp is a bound on what is VISIBLE (sim.h's PLAY_H_PX) and
 * not on the panel, or the ground at the end of a descent scrolls under the bar
 * and never comes into view while every frame still looks like a working
 * camera.  The second is that the ring stops owing anything back -- the HUD no
 * longer occupies two map rows, so the climb case no longer redraws the row
 * leaving the strip.
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

/* The background's shape: 20x18 tiles, and the ONLY stride in this file.  The
 * 20x18 at (0,0) is the whole of what this file writes into the BG map; the
 * camera below slides the view down it as of P10, and P11's ring is what puts
 * tiles under the scroll.  As of P12 the last two of those rows are UNDER the
 * status bar -- see PLAY_H. */
#define VIEW_W 20
#define VIEW_H 18

/* THE STATUS BAR, and the visible height it costs the world.
 *
 * The telemetry is the WINDOW layer's as of P12 -- WY_REG = PLAY_H -- and a
 * window is not scrolled by SCY, which is the whole reason the family keeps its
 * HUD there: a BG strip's screen position is `map_row * 8 - SCY`, so it is
 * exactly at the top of the screen only while `cam % 8 == 0` and clipped or
 * carried off the top the rest of the time.  HUD_ROWS is how many window rows
 * the bar owns; PLAY_H is what is left of the screen for the world.
 *
 * PLAY_H IS NOT VIEW_H, and the difference is not cosmetic.  The window always
 * runs to the bottom-right corner, so its two rows COVER the last two rows of
 * background: a camera clamped on VIEW_H scrolls two rows of world under the
 * bar and the ground at the bottom of a descent never comes into view.  VIEW_H
 * stays the BUFFER's height (what a 20x18 blit writes, and what the ring's own
 * comments mean by the screen); PLAY_H is the VISIBLE height and is the one
 * sim.h's camera clamps on.  The tripwire below holds the two in step. */
#define HUD_ROWS 2
#define PLAY_H   (VIEW_H - HUD_ROWS)
typedef char play_h_matches[(PLAY_H * 8 == PLAY_H_PX) ? 1 : -1];

/* The BG map is 32 rows of 32 tiles, and it is the RING the tall world is
 * wound through: 32 rows is 256 px of scroll against a DESCENT world of 808,
 * so the row a world row belongs in is its own index modulo this.  A power of
 * two, so the modulus is an AND -- and the ONLY modulus in the project that is
 * allowed to be one, because here it is the map's size and not the world's
 * (sim.h's world wrap is two compares for exactly that reason). */
#define MAP_ROWS 32

/* sim.h has its own copy of the screen height -- it carries the camera and has
 * no gb/gb.h to ask -- and this is the line that keeps the two in step.  A
 * mismatch moves the camera's bottom clamp off the world's end while the scroll
 * still looks perfectly reasonable, which is the kind of thing only a build
 * error catches. */
typedef char screen_h_matches[(VIEW_H * 8 == SCREEN_H_PX) ? 1 : -1];

/* P9 wound the DESCENT's opening screen to a fixed profile row BY HAND, because
 * there was no camera to wind it for it.  P10's camera answers that question
 * instead -- the window's top row IS the camera's row -- and P11 is what makes
 * the map agree with it, so the constant is gone rather than kept as a second
 * answer to a question the camera already answers.  A DESCENT life opens at the
 * top of its world now, with the ground 96 rows below it, which is what a
 * descent looks like before any of it has been flown. */

/* Which screen this iteration builds.  ST_TITLE and ST_PLAY are this file's;
 * the other two states the game has are sim.h's ST_CRASH and ST_LANDED, and
 * they are reused rather than shadowed here because once the life is over the
 * SHIP's state IS the screen's: a second pair of constants saying the same
 * thing is a pair that can disagree with the first, and only one of them would
 * be telling the truth. */
#define ST_TITLE 0
#define ST_PLAY  1

/* The two modes the title offers.  This byte was INERT when P6 wrote the title
 * -- SELECT flipped it and the title said so and nothing else read it -- and it
 * has not been since P9: START opens the field with field_open(), which points
 * `terrain` at the profile this byte names, and P10 takes the world's height
 * from that profile.  Both modes are the same game over two worlds, and the
 * selection is the only thing that picks between them. */
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

/* P7's two bytes of sound state, statics for the same reason `input` is (a
 * local of main's lives on the stack, and that is the shape P6's comment above
 * is about) and because both have to survive a tick.
 *
 * `burning` is the pad AND the tank as they stood BEFORE ship_step(), because
 * ship_step is what spends the fuel: a reading taken after the step cuts the
 * engine a tick early on the tick the tank runs dry, which is the kind of
 * thing that only shows up as "the sound stops a hair before the ship does".
 *
 * `sfx_state` is the state the LAST tick's step left behind, and the change in
 * it is the whole of what makes a landing or a crash an event: both are sticky
 * (ship_step is a no-op once either has been reached), so without the edge a
 * tick loop would re-fire the crash every frame for the rest of the life. */
static uint8_t burning;
static uint8_t sfx_state = ST_FLY;

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

/* Which world the title's SELECT has chosen.  THE BOOT DEFAULT and the ONLY
 * mode byte there is: main() writes it once, build_title() reads it for the mode
 * line, and build_field() reads it for the profile `terrain` points at and the
 * height the camera clamps against.  See the boot comment in main().
 *
 * `pick` and not `mode`: gb/gb.h declares a mode() of its own (the display-mode
 * request), and the linker sees one symbol, not one per translation unit. */
static uint8_t pick;

/* The visible screen, 20x18 tile ids.  ONE buffer for both screens,
 * deliberately: the title is a 20x18 field of tiles and so is the play field,
 * and the only thing a second buffer buys is a way for the two to be filled in
 * the wrong order.
 *
 * The TITLE fills all 20x18 and blits it whole, at boot and before DISPLAY_ON,
 * because "the tiles go up with the display off" is about every byte of the
 * first frame and not just the bank: a map written after the display came on
 * would leave the first frame showing whatever the PPU found in VRAM.
 *
 * The PLAY FIELD fills only the top HUD_ROWS rows of it -- build_hud() -- and as
 * of P12 those two rows are blitted into the WINDOW map as the status bar while
 * P11's ring owns the BG map's rows entirely.  So `bg` is the title's screen and
 * the play field's status bar, and the terrain is no longer in it at all.  The
 * buffer is still rewritten in place each tick and the VRAM write still happens
 * after wait_vbl_done() -- the sibling's ordering, where the map write lands in
 * the vblank window rather than being dropped by the PPU mid-scanline. */
static uint8_t bg[VIEW_W * VIEW_H];

/* The camera: the world row, in PIXELS, that the top of the screen shows -- the
 * value SCY gets and the value the ship's own draw position is measured
 * against.  A uint16_t and NOT a byte, which is the whole of "the clamp is on
 * the world and not on the map": the DESCENT world is ~800 px tall, so the
 * camera really does reach 664, and SCY is written from its LOW BYTE because
 * one byte is what the register is.  That wrap is the hardware's, and it is
 * exactly what P11's circular map exists to make seamless -- a camera held in a
 * byte instead would clamp the descent at 256 px, and the view would stop with
 * 600 px of world still below it while every frame looked like a working
 * camera.
 *
 * A file-scope static so probe.p10_camera can read it out of luna.map, the same
 * way `frame` and `game` are read. */
static uint16_t cam;

/* The ACTIVE world's height in px, taken from the profile being drawn -- see
 * world_extent().  main() builds the default field's before the display goes on,
 * so it is never 0 in play; on the title it describes the mode the title is
 * offering, which is the same world START would hand over. */
static uint16_t world_h;

/* One world row of terrain, staged for the map write in ring_stream().
 *
 * TWENTY BYTES AND NOT A ROW OF `bg`.  The HUD's two rows live in bg[0..39] and
 * are sent from there in the same vblank, so a row_blit() that staged into bg
 * would destroy the HUD's first row on the way past -- and the ordering that
 * would fix that (HUD first, rows after) is the one that lets the ring's own
 * write at the top of the screen land ON the HUD.  A separate 20 bytes makes
 * the two writes independent, which is the only reason it is here.
 *
 * A file-scope static rather than a local of ring_stream()'s for the usual
 * reason in this file: it has to survive the call, and luna.map is where the
 * probe reads main.c's storage. */
static uint8_t rowbuf[VIEW_W];

/* The RING's base: the world row the map's row 0 holds.  Every map row m holds
 * world row ring_top + m, and the camera's own row is what it tracks -- so the
 * two are equal except for the ticks between the camera moving and the row
 * being written, which is exactly the slack the map's 32 rows give over the
 * screen's 18.
 *
 * A uint8_t, and it has to hold 101: the DESCENT world's rows run to 100, which
 * is the same reason terrain.h's heights are TERRAIN_MAX_TILES wide and why a
 * byte counted in PIXELS would have to be the wrong type again.
 *
 * A file-scope static so probe.p11_stream can read it out of luna.map. */
static uint8_t ring_top;

/* Set when the ring describes a different part of the world than the camera
 * does, and cleared by the fill that fixes it.  A new LIFE is the only thing
 * that sets it: the camera opens at the top of the world, and a life that ended
 * at the bottom leaves the ring wound eighty rows down, which is more than the
 * 32 rows the map holds and so cannot be walked back a row at a time.
 *
 * Cleared AFTER the fill rather than before, so the flag is a claim about the
 * map and not about the code: a probe that reads it set knows the band it is
 * looking at is mid-rebuild. */
static uint8_t ring_stale;

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

    /* ...and the ring, which a new life invalidates and nothing else does.  The
     * spawn is at the TOP of the world, so the camera is about to be at row 0 --
     * and the ring is wherever the LAST life left it, up to eighty rows down,
     * which is more than the 32 rows the map has and so is not something the
     * one-row-at-a-time path can walk back.  Set here rather than in the tick
     * loop because "a life starts" is the whole of the condition, and this is
     * the one function that means that. */
    ring_stale = 1;
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

/* Put the sprite where the ship is on SCREEN and at the heading it is pointing
 * -- called once per tick in play, always straight from the state so the offset
 * is written down exactly once.  The ship's top-left is (x, y); the OAM bytes
 * are (x + 8, y + 16).
 *
 * THE CAMERA IS SUBTRACTED FROM Y, and this is the one place it can be
 * forgotten.  SCY scrolls the BACKGROUND ONLY -- the PPU does not move a sprite
 * for it -- so a ship drawn at its world y would slide off the top of the
 * screen at exactly the speed the view scrolled beneath it, while the scroll
 * itself looked perfectly correct.  Taking cam off is what pins the ship to the
 * upper third and lets the world go past.  x is untouched: there is no
 * horizontal camera, the world still wraps in 160 px.
 *
 * The subtraction cannot underflow: camera_for() never returns more than
 * ship_y, so the difference is the ship's distance below the top of the screen
 * and is at most the screen's height.
 *
 * The FRAME comes out of the same heading byte the thrust VECTOR does, so the
 * nose on screen is always the direction the physics is accelerating: a
 * renderer that tracked its own frame would look right while thrusting
 * sideways, and nothing on screen would say so. */
static void ship_draw(void)
{
    set_sprite_tile(SPR_SHIP0, (uint8_t)(SPR_SHIP0 + ship.heading));
    move_sprite(SPR_SHIP0, (uint8_t)(ship.x + 8),
                (uint8_t)(ship.y - cam + 16));
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

/* FUEL, ALT, the two velocities and the target pad, in the window's first two
 * rows -- the status bar main() puts at the bottom of the screen.
 *
 * THE TWO ROWS OF `bg` IT WRITES ARE THE WHOLE OF WHAT THE WORLD LOSES to the
 * bar, so it is also the reason the camera clamps on PLAY_H_PX and not on the
 * panel -- see the constants at the top of the file.
 *
 * This, and NOT the whole screen, is what the tick loop rebuilds.  A tilemap
 * write costs the PPU window it has to wait for -- the display is on, so
 * set_win_tiles can only put its bytes down in the blanking interval -- and a
 * 20x18 blit measures at about three frames on this machine.  The terrain does
 * not move, so it is written once per row by P11's ring and the 40 tiles that DO
 * change are written every tick, which fits the frame with room to spare.  The
 * tick loop's own frame-rate assertion in probe.p6_hud is what holds that: P6 is
 * the phase that made the loop draw, so P6 is the phase that has to keep one
 * iteration equal to one tick.
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
 * touches down, on a pad or in a crater alike.
 *
 * The TARGET PAD is the one indicator that is about the WORLD rather than about
 * the ship, and it is here because the two modes have to be told apart by more
 * than which profile got drawn: it is the multiplier sim.h's own pad_mult()
 * gives the column under the ship's centre, so what it names is the pad the ship
 * will land on if it keeps falling where it is -- the x1 or x2 pad, or 0 for
 * ground that is not a landing site at all.  Read through sim.h's rule and not
 * through a second copy of the pad table here, so the score a landing earns and
 * the score the bar advertises cannot disagree. */
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
     * readings are not the same length -- "CRASHED" is seven tiles and
     * "LANDED X2" nine, against the velocity row's twenty -- so a life that
     * ends and is restarted would leave the tail of the longer string sticking
     * out behind the shorter one.  Row 0 is one fixed layout sixteen tiles wide
     * and has nothing to clear. */
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
        /* Five tiles of label, then a ONE-WIDE digit: dec()'s width is the
         * whole field, and pad_mult() only ever answers 0, 1 or 2, so one
         * column is exact for it and a two-wide field would print a leading
         * blank that the layout below has no room for. */
        text(bg, 14, 1, "PAD X");
        dec(&bg[VIEW_W + 19], 1, (int16_t)pad_mult(col));
    } else if (ship.state == ST_LANDED) {
        text(bg, 0, 1, "LANDED X");
        dec(&bg[VIEW_W + 8], 1, (int16_t)ship.mult);
    } else {
        text(bg, 0, 1, "CRASHED");
    }
}

/* ONE world row of the ACTIVE profile, into the map slot that row OWNS.
 *
 * P9's blit_window() did the whole visible window at once and P11 replaced it
 * with this, because the ring cannot write a window: the row a world row goes
 * in depends only on the world row, and the map is a ring over the world rather
 * than a window on it.  Filling the window is now MAP_ROWS calls to this, which
 * is what ring_fill() is.
 *
 * Every cell is written -- sky above the surface, the surface tile on it, body
 * below -- so a row is never left holding the row that was there 32 rows ago.
 *
 * terrain[col] is a TILE row, not a pixel row -- the 8 px tile mkgfx.py draws
 * the art in -- so there is no `<< 3` anywhere here.  A `<< 3` is the classic
 * "heights are pixels" slip and it would drop the ground eight rows and push
 * the bottom of it off the screen, which still LOOKS like terrain.
 *
 * World COLUMN N is screen column N: there is still no horizontal camera, and
 * the world wraps in 160 px at the same seam it always did.  Only the ROWS are
 * wound through the map. */
static void row_blit(uint8_t wr)
{
    uint8_t col;

    for (col = 0; col < WORLD_COLS; col++) {
        uint8_t surface = terrain[col];     /* surface row, tile units */

        rowbuf[col] = (wr < surface) ? T_BLANK
                    : (wr == surface) ? T_TERRAIN_TOP : T_TERRAIN;
    }

    /* `wr & (MAP_ROWS - 1)` and NOT a plain `wr`: the world is 101 rows and the
     * map is 32, so the row a world row goes in is its own index taken modulo
     * the map -- which is what makes the map a ring rather than a window, and
     * what makes the scroll seamless past 256 px instead of repeating.  An AND
     * and not a `%`, because MAP_ROWS is a power of two and SDCC turns the
     * modulo into a call to __divuint (231 bytes) for a wrap that costs one
     * instruction.  `MAP_ROWS - 1` rather than a literal 31, so the day the map
     * is not 32 rows this line is still the right one. */
    set_bkg_tiles(0, (uint8_t)(wr & (MAP_ROWS - 1)), VIEW_W, 1, rowbuf);
}

/* The ring, filled whole: the 32 world rows from `top` down, one map row each,
 * which is the state streaming then keeps by writing one row a tick.
 *
 * THE WHOLE 32 AND NOT JUST THE 18 THE SCREEN SHOWS, because the map is a ring
 * and the screen is a window on it: a band of only 18 rows would leave the
 * slots the camera is about to uncover holding whatever the last 256 px left
 * there, and the row that is 14 rows below the screen is written now precisely
 * so that it is already right when the camera arrives.
 *
 * 32 map writes and not one 20x32 blit, because the map's rows are the ring's
 * and the band can start at any of the 32 of them: a single rectangular write
 * would have to be two, wrapping at the map's end, and it would need a 640-byte
 * staging buffer to hold a band this file otherwise only ever holds a row of.
 * A row at a time costs nothing here -- this runs once per LIFE, not per tick. */
static void ring_fill(uint8_t top)
{
    uint8_t m;

    for (m = 0; m < MAP_ROWS; m++)
        row_blit((uint8_t)(top + m));
    ring_top = top;
}

/* One tick of the ring, in the vblank with the SCY write above it.
 *
 * The band that is live is [ring_top, ring_top + MAP_ROWS - 1] and the window
 * is [cam_row, cam_row + VIEW_H - 1], so the two are one row apart in the
 * steady state and the camera reveals exactly one row a tick.  What is written
 * is the row at the far END of the band -- 31 rows below the top of the screen
 * -- and not the row at the bottom of the screen, which was written 14 ticks
 * ago: that is the slack the ring's 32 rows buy over the screen's 18, and it is
 * what makes the reveal land a frame and a half before it is ever looked at.
 *
 * Writing ONE ROW PER VBLANK is the whole point of the phase.  A blit of the
 * window would have to run with the display off to fit, and a visible blank
 * band -- or a flash -- per row is the failure this exists to avoid: twenty
 * tiles plus the HUD's two rows and the SCY write fit one blanking window,
 * which is why the reveal is a row and never a frame of nothing.
 *
 * (What the whole TICK costs is another question and a P9 one: the descent does
 * not complete one tick per emulated frame and did not before this phase --
 * probe.p10_camera says so where it has to allow for it.)
 *
 * CLIMBING WRITES ONE ROW TOO, and P11 it was two.  The band is always 32 rows
 * and a climb shifts it UP by one: the row at the top is the one that joins and
 * the one at the bottom leaves, and they share a map slot, so writing the row
 * that joins is the whole of it.  P11's second write was the HUD's fault -- the
 * strip overwrote two slots in the middle of the band, and walking back up
 * dragged the lower of them out into terrain at screen row 2 -- and as of P12
 * the telemetry is in the WINDOW layer and no longer touches the BG map at all,
 * so the band is simply terrain the whole way down and that write is gone with
 * the bug it existed for. */
static void ring_stream(void)
{
    uint8_t top = (uint8_t)(cam >> 3);

    /* ring_top MOVES AFTER the write and not before, so that it always means
     * "the band as it stands in the map" rather than "the band this tick is
     * aiming at".  The difference only shows to a reader sampling between the
     * two -- a row write costs a blanking window, so there is a whole frame in
     * which the band is half moved -- and it is what lets probe.p11_stream use
     * this byte as its gate: on any tick that is past the writes the two agree
     * and the tiles below are exact, and on a tick that is not, they disagree
     * and the sample is skipped rather than graded against a band that is
     * mid-flight. */
    while (ring_top < top) {
        row_blit((uint8_t)(ring_top + MAP_ROWS));   /* the row the band gains */
        ring_top++;
    }
    while (ring_top > top) {
        row_blit((uint8_t)(ring_top - 1));          /* ...and climbing */
        ring_top--;
    }
}

/* Which world the play field opens on.  It is the ONLY place `terrain` is ever
 * assigned.
 *
 * `terrain` is ONE symbol.  sim.h's ship_step() reads terrain[col] to find the
 * ground and tools/probe.py reads it out of the linker map, so the two profiles
 * are two arrays and this is the pointer that says which is live.  A second
 * array called terrain per mode, or a renderer that read a different table from
 * the one the collision reads, is the trap: the screen would draw one world and
 * the ship would land in the other, and that reads as a physics bug.
 *
 * LANDER is the world it has always been -- 160 px wide and one screen tall --
 * and its camera is pinned at 0, so its ring sits at row 0 and the whole of
 * P11's machinery is the identity there.  That is deliberate: it is what keeps
 * the rendered screen identical to P6's, so P2's and P5's checks are still
 * checks on the game and not on a rewrite.  DESCENT is deeper than a BG map, so
 * it is the one the ring exists for.
 *
 * It no longer returns a window offset, because there is no longer one place to
 * put it: P9 could blit the descent's opening screen at a hand-picked row and
 * say so once, and the camera means the offset is a different number every tick
 * -- so the row is the camera's business now and not this function's.
 *
 * P12 CALLS IT AT BOOT as well as at the hand-over, which is the whole of "a
 * single `pick` initialiser is the boot default": the mode line on the title,
 * the profile the renderer and sim.h's collision read, and the world the camera
 * clamps against are then all derived from one byte from the first tick, rather
 * than agreeing at the hand-over and nowhere before it.  A probe that pressed
 * START before looking could not tell those two apart -- which is exactly why
 * probe.p12_mode boots raw. */
static void field_open(void)
{
    terrain = (pick == MODE_DESCENT) ? terrain_descent : terrain_lander;
}

/* How tall the ACTIVE world is, in px: the bottom of the deepest column, one
 * tile below its surface row.
 *
 * Read out of the profile the level generator committed rather than written
 * down here, so a regenerated terrain.h cannot leave the camera clamping at a
 * bound the world no longer has -- the two profiles are 104 px and 808 px tall
 * and the difference is the whole of what the clamp does.
 *
 * terrain[col] is a TILE row (terrain.h), so the `<< 3` is the one place the
 * units meet here -- the same conversion sim.h's contact test does, and the
 * same slip to watch for: a `>> 3` would make the world eight times too short
 * and the camera would clamp almost at once, which still looks like a camera.
 * The `+ 1` is the tile of ground BENEATH the surface row: a column whose
 * surface is row 100 has its ground at px 768 and its world runs to 808, which
 * is what puts the bottom of the world on the last row the player can SEE --
 * sim.h's PLAY_H_PX above the status bar, not the panel's 144. */
static uint16_t world_extent(void)
{
    uint8_t col, deepest = 0;

    for (col = 0; col < WORLD_COLS; col++)
        if (terrain[col] > deepest)
            deepest = terrain[col];
    return (uint16_t)(((uint16_t)deepest + 1) << 3);
}

/* The play field, opened: which profile is live, and how tall it is.
 *
 * It no longer fills anything.  P9 built the whole screen here and blitted it
 * in one write, because the screen was one fixed window; what the map holds now
 * is a ring around the CAMERA, and the camera is not a thing this function
 * knows -- ship_init() marks the ring stale and the play branch fills it from
 * the camera it has just computed, so there is still exactly one place a band
 * is written from and it is not here.
 *
 * world_h is taken with the profile it describes, so the camera's bound and the
 * tiles on the map can never be about two different worlds. */
static void build_field(void)
{
    /* field_open() FIRST, and not on style: it is what assigns `terrain`, and
     * world_extent() reads through that pointer.  Taking the height first would
     * measure the PREVIOUS world -- LANDER, the boot default -- so the DESCENT
     * would be drawn with the camera clamped to a 104 px world and the view
     * would never move, which looks exactly like a camera that was never wired
     * up. */
    field_open();
    world_h = world_extent();
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

/* ------------------------------------------------------------------ sound
 * Three sounds, written where the sound is made.  No audio module for three
 * register sets: the whole of the sound is the writes below.
 *
 * A burn rasps on CH1, a landing thumps on CH2, a crash hisses on CH4.  Every
 * envelope is DECREASING -- NRx2 bit 3 is clear in all of them -- so each
 * sound decays to silence on its own, and the two that are EVENTS are nothing
 * but that decay: no code path here switches a channel off.
 *
 * The thrust is the one LEVEL, and a level needs a stop.  It is re-triggered
 * on every tick the burn lasts, which is what turns one click into an engine,
 * and the tick it stops writes NR12 = 0x08 -- volume 0 with the direction bit
 * set, so the DAC stays ON and the channel is SILENCED rather than switched
 * off, and the next press is an ordinary trigger.  NR12 = 0x00 would clear the
 * DAC bit instead, and that is the switch-off this design avoids.
 *
 * The high frequency register's TOP BIT is the trigger; writing it restarts
 * the channel from the first byte of its envelope.  Without it a second hit
 * would only rewrite the registers of a channel that was already running, and
 * the second sound would be inaudible -- a repeat that is silent with nothing
 * on screen to say so.
 *
 * These are called from the tick loop's play branch, all three of them, and
 * from NOWHERE else -- not from ship_draw(), not from the input decode above
 * it.  A call in the draw path would fire on frames where nothing happened (a
 * crash sound on every frame of a crashed life, since the state is sticky),
 * and a call in the input decode would announce a thrust the empty tank
 * refused, before the step that decides it. */
static void play_thrust(void)
{
    NR11_REG = 0x80;                /* 50% duty, no length counter */
    NR12_REG = 0x93;                /* volume 9, decreasing, period 3 */
    NR13_REG = 0x00;                /* freq 0x300 -> 73 Hz: a low rasp */
    NR14_REG = 0x83;                /* trigger + freq high bits */
}

/* CH2 has no hardware sweep -- that is NR10, which only CH1 has -- so "a
 * sweep" here has to be an envelope that falls away fast over a low note,
 * which is what a landing sounds like. */
static void play_land(void)
{
    NR21_REG = 0x80;                /* 50% duty, no length counter */
    NR22_REG = 0x81;                /* volume 8, decreasing, period 1: a thud */
    NR23_REG = 0x00;                /* freq 0x400 -> 128 Hz */
    NR24_REG = 0x84;                /* trigger + freq high bits */
}

static void play_crash(void)
{
    NR42_REG = 0xD3;                /* volume 13, decreasing, period 3 */
    NR43_REG = 0x26;                /* 15-bit noise, shift 2, divisor 6 */
    NR44_REG = 0x80;                /* trigger */
}

/* ------------------------------------------------------------------ main */
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

    /* The APU, on -- without this every play_* below is silence and nothing
     * anywhere says so.  This ROM arrives here with NR52 bit 7 CLEAR: the boot
     * ROM powers the APU up and GBDK's crt0 powers it back down, and while
     * that bit is clear the sound registers cannot be written and read as
     * zero, so every play_thrust/play_land/play_crash write would vanish.
     * NR50 and NR51 go WITH it and not later: powering the APU on resets the
     * routing, and a channel routed nowhere is the same silence by another
     * route.  probe.p7_sound reads all three back. */
    NR52_REG = 0x80;                /* APU on */
    NR50_REG = 0x77;                /* both outputs, full volume */
    NR51_REG = 0xFF;                /* all four channels to both outputs */

    /* The screen machine starts on the title, on the mode it offers.  THE
     * BOOT DEFAULT IS THIS ONE WRITE, and nothing else anywhere names a mode:
     * build_title() below reads `pick` for the mode line, and build_field()
     * reads it for the profile the world and the camera are taken from -- so the
     * title, the terrain and the clamp cannot come out of three different
     * answers.  probe.p12_mode looks at all three BEFORE pressing anything,
     * which is the only way a wrong initialiser here is visible at all: a check
     * that pressed START first would be looking at the hand-over, where
     * build_field() re-derives the lot. */
    game = ST_TITLE;
    pick = MODE_LANDER;
    build_field();

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

    /* ...and the WINDOW, which is where the telemetry lives as of P12.
     *
     * WY is where the window STARTS and it always runs to the bottom-right
     * corner from there, so the bar is at the BOTTOM of the screen and not the
     * top: rows PLAY_H..17, which is why the play area is PLAY_H tall and why
     * sim.h's camera clamps on PLAY_H_PX and not on the panel.  WX = 7 is the
     * family's value and not a fudge -- a window is drawn from x = WX - 7, so 7
     * is the widest it can be, and 0 would show none of it.
     *
     * THE WINDOW IS NOT SCROLLED BY SCY, and that is the entire reason it is
     * here rather than in the BG map P11 used: a BG strip's screen y is
     * `map_row * 8 - SCY`, so it sits at the top of the screen only while
     * `cam % 8 == 0` and is clipped or lost off the top the rest of the time.
     *
     * SHOW_WIN rather than HIDE_WIN/SHOW_WIN around the title: the window map is
     * zeroed at power-up and tile 0 is T_BLANK, which is the paper the title is
     * already drawn on, so the bar's two rows are invisible over the title and
     * there is no state here to get wrong.  GBDK's crt0 already leaves LCDC bit 6
     * set -- the window's own 0x9C00 map, which is what set_win_tiles writes --
     * so nothing here has to say so. */
    WX_REG = 7;
    WY_REG = PLAY_H * 8;
    SHOW_WIN;

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
                /* Which world, and how tall.  There is no map write here any
                 * more: the tiles are a ring around the CAMERA as of P11, and
                 * the camera is computed from the ship the play branch below is
                 * about to spawn -- so the fill happens there, on this same
                 * tick, from the camera rather than from a row picked here. */
                build_field();
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

            /* Does this tick burn?  The pad AND the tank, read here because
             * ship_step() below is what spends the fuel -- and the state,
             * because UP held over a crashed ship is not a burn either. */
            burning = (uint8_t)((ship.state == ST_FLY &&
                                 (input & SHIP_THRUST) && ship.fuel) ? 1 : 0);

            /* One iteration IS one tick.  Physics runs once here, unpaced by
             * any dt accumulator, because wait_vbl_done() below already puts
             * the loop at one iteration per ~16.7 ms frame. */
            ship_step(&ship, input);

            /* The camera for THIS tick, from the ship the step above just
             * moved.  A pure function of the state and the world, recomputed
             * rather than accumulated, so nothing here can drift, a restart
             * cannot leave the view wound down the world, and there is no
             * smoothing constant to tune.  cam is what ship_draw() subtracts
             * and what the tick loop below hands SCY.
             *
             * IMMEDIATELY after the step, and not down with the other drawing,
             * and that is a test's problem rather than a renderer's.  The
             * descent does not complete one emulated frame of this machine, so
             * tools/probe.py samples the loop at a fixed point INSIDE it --
             * and any code between the step and this line is a window in which
             * the ship has moved and the camera has not.  p10_camera reads the
             * two and holds the camera against the ship's own altitude, so a
             * sample in that window is a camera that looks one tick late.
             * Nothing here depends on cam, and everything below does. */
            cam = camera_for(ship.y, world_h);

            /* ...and the ring, from THAT camera and not from the one the last
             * tick ended on.  A life starts at the top of the world and the
             * ring is wherever the previous one left it -- up to eighty rows
             * down, which is more than the map can hold, so a restart REBUILDS
             * the band instead of walking it.  ship_init() is what raises the
             * flag; this is the one place it is lowered, and it is lowered from
             * the camera the tick will actually be drawn at. */
            if (ring_stale) {
                ring_fill((uint8_t)(cam >> 3));
                ring_stale = 0;
            }

            /* ---- sound.  The ONE place any of the play_* functions is called
             * from -- see the essay above them for why the draw path and the
             * decode above are both wrong places for one.  All three read what
             * the step JUST did, so the two event sounds cannot announce a
             * landing the physics has not classified yet. */
            if (burning)
                play_thrust();
            else
                NR12_REG = 0x08;    /* volume 0, DAC on: silent, not switched off */
            if (ship.state != sfx_state) {
                if (ship.state == ST_LANDED)
                    play_land();
                else if (ship.state == ST_CRASH)
                    play_crash();
            }
            sfx_state = ship.state;

            /* The HUD, and only the HUD.  The terrain is the ring's business
             * now (see the vblank below), but the strip is still built here and
             * sent on EVERY tick: the numbers in it change on every tick, and a
             * gate that had to notice that would be a gate that is always open. */
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
            /* SCY goes FIRST, and WHERE it goes is this phase's named trap: the
             * PPU reads the scroll registers as it draws, so a write outside
             * the blanking window tears the frame -- the top of the picture
             * showing the old scroll and the bottom the new one.  It belongs
             * HERE, after the wait above, and NOT in the play branch, which
             * runs before the wait and would write mid-frame.  Nothing about
             * the finished screen can tell the two orders apart under an
             * emulator, so this line's position is the only expression of it.
             *
             * The LOW BYTE only.  cam is a uint16_t world offset (see its
             * declaration) and SCY is one byte, so the scroll wraps at 256 px
             * and repeats -- which is the hardware's limit and precisely the
             * wrap P11's circular map is built to make seamless.  Writing the
             * byte is not a compromise here; it is the reason the map has to
             * become a ring. */
            SCY_REG = (uint8_t)cam;

            /* THEN the ring, in the SAME blanking window as the scroll above it
             * -- and the pairing is the whole of the phase's ordering.  SCY and
             * the row the scroll has just uncovered are two halves of one
             * picture: write the scroll this vblank and the row the next one and
             * the bottom line of the screen shows a row of the world that has
             * not been drawn yet, for exactly one frame, every frame.  It reads
             * as a stale row that tracks the camera -- a scrolling bug -- and it
             * is an ordering bug.  The family has measured the same split from
             * the other side: a BG map write ripens a frame after a shadow-OAM
             * write made in the same vblank (Checkers' glide), so a row written
             * anywhere but here would land against the wrong scroll.
             *
             * ring_stale is the restart: a full band, 32 rows, once per life. */
            if (ring_stale) {
                ring_fill((uint8_t)(cam >> 3));
                ring_stale = 0;
            } else {
                ring_stream();
            }

            /* ...and the HUD, into the WINDOW map and nowhere near the scroll.
             *
             * P11 wrote these two rows into the BG map at the rows the CAMERA
             * puts them on, and that is the thing this phase exists to undo: a
             * BG row is scrolled by the same SCY as the terrain, so its screen
             * position is `map_row * 8 - SCY` and it is at the top of the
             * picture only while `cam % 8 == 0`.  Rows 0 and 1 of the WINDOW map
             * are screen rows PLAY_H and PLAY_H + 1 whatever SCY says -- the
             * window is not scrolled at all -- which is the whole of the fix,
             * and the reason no offset into the BG map was ever going to be
             * one.
             *
             * LAST, and it can be now: two writes into a map the ring never
             * touches cannot race it, and there is no `cam_row + 1` wrapping to
             * map row 0 across the ring's seam either, because the window map
             * has no seam.  The tilemap this lands in is the one the NEXT frame's
             * reads see, which is the same one-vblank relationship the shadow
             * OAM has had since P3 -- and the reason probe.p6_hud allows the
             * screen's numbers to be one tick behind the state's. */
            set_win_tiles(0, 0, VIEW_W, 1, bg);
            set_win_tiles(0, 1, VIEW_W, 1, &bg[VIEW_W]);
        }
    }
}
