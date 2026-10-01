/* Host tests for LUNA LANDEER.
 *
 * WHY THIS EXISTS: the physics lives in sim.h as pure C with no gb/gb.h in it,
 * so plain gcc can compile and run it -- no emulator, no ROM, no waiting.
 * tools/probe.py is the other half: it covers the wiring between that maths and
 * main.c, which the host cannot see.  This covers the maths, where the boundary
 * cases live.
 *
 * P1 had no sim.h yet -- it was the toolchain probe -- so the width discipline
 * every later phase is written in comes first: the values are explicit
 * uint8_t/int16_t/uint32_t and GBDK's `int` is 16-bit, so a type that silently
 * widened here would poison the arithmetic below.
 *
 * P3 is fix_step's carried remainder and the exact 8.8 trajectory gravity
 * produces from rest.  The trap of that phase -- a fraction byte in
 * ship_step()'s LOCALS instead of in the state -- is pinned from both sides,
 * because it is the one that ships looking fine.
 *
 * P4 is the vector algebra: thrust as a DIRECTION out of tables.h, the fuel
 * economy as part of the step, and the heading wrap.  The trap of that phase is
 * the table's width -- a unit vector at 8.8 is +-256 and does not fit int8_t,
 * and an int8_t table aliases the cardinals to zero and folds the diagonals
 * into the wrong quadrant, which reads as a rotation bug rather than a width
 * one.  It is asserted here, not assumed.
 *
 * P5 is the landing verdict, and this file is where it is ACTUALLY verified.
 * Every threshold is straddled from both directions -- a case at the edge and
 * a case one unit past it, so "just barely safe" and "just barely fatal" are
 * both written down, one `>` at the exact edge as Protector's human_fall_step
 * does.  That is what makes the rule unfakeable here: swap the rule for one
 * that always answers SAFE and several of these fail, instead of a game where
 * nothing can crash and nothing on screen saying so.  The verdict has to come
 * out of sim.h -- a check that read the screen would prove the renderer, which
 * is three lines of wiring in main.c.
 *
 * P10 is the camera, and it is swept HERE rather than sampled in the probe: the
 * phase is a pure function of the ship's altitude, so the honest check is every
 * altitude from above the world to below it, against both of the ROM's worlds.
 * What the probe can add is only that main.c WRITES the answer it computed and
 * subtracts it from the sprite, neither of which is visible from a host.
 *
 *     make test
 */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>

#include "../sim.h"

static int checks, failed;

static void check(int cond, const char *fmt, ...)
{
    va_list ap;

    checks++;
    if (cond)
        return;
    failed++;
    printf("FAIL  ");
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
}

/* A ship exactly as main.c spawns it: rest, nose up, full tank, FLYING.  Every
 * case below starts from here rather than from whatever the last one left
 * behind -- and the state byte is part of "exactly", because ship_step() is a
 * no-op on a ship that is not ST_FLY and a test that forgot it would pass
 * every assertion by never running the step at all. */
static Ship spawn(void)
{
    Ship s;

    s.x = 108;
    s.y = 16;
    s.xf = 0;
    s.yf = 0;
    s.vx = 0;
    s.vy = 0;
    s.heading = 0;
    s.fuel = FUEL_START;
    s.state = ST_FLY;
    s.verdict = LAND_SAFE;
    s.mult = 0;
    return s;
}

/* A ship ARRIVING at its landing: the spawn, but with the speeds and attitude
 * the verdict is actually about.  classify_landing() reads only these three
 * and the column under the ship, so this is its whole input -- which is what
 * makes the threshold table below straddle each edge with no arithmetic in
 * between that could round it off. */
static Ship arriving(int16_t vx, int16_t vy, uint8_t heading)
{
    Ship s = spawn();

    s.vx = vx;
    s.vy = vy;
    s.heading = heading;
    return s;
}

int main(void)
{
    check(sizeof(uint8_t) == 1 && sizeof(uint16_t) == 2 &&
          sizeof(int16_t) == 2 && sizeof(uint32_t) == 4,
          "the fixed-width types are the widths the physics is written in");

    /* ------------------------------------------------------------ P3 ---- */

    {
        uint8_t frac = 0;
        int16_t moved = 0;
        uint8_t i;

        /* fix_step carries the remainder it is POINTED AT: sixteen ticks of
         * GRAV (16/256 px each) are exactly one whole pixel, and the byte is
         * back where it started. */
        for (i = 0; i < 16; i++)
            moved += fix_step(&frac, GRAV);
        check(moved == 1 && frac == 0,
              "sixteen GRAV ticks carry one whole pixel and leave no remainder");

        /* The same sixteen ticks with the fraction in a LOCAL -- the trap.  A
         * fresh zero every call means every remainder is discarded, so the
         * ship does not move at all here.  If this ever stops failing to move,
         * fix_step has changed what its first argument means. */
        moved = 0;
        for (i = 0; i < 16; i++) {
            uint8_t local = 0;
            moved += fix_step(&local, GRAV);
        }
        check(moved == 0,
              "a fraction byte in a local throws the remainder away");
    }

    {
        Ship s;
        uint8_t i;

        /* P3's whole target in one condition: from rest the ship spends WHOLE
         * TICKS not moving a single pixel while the state's fraction byte
         * builds up the remainder.  Written against GRAV rather than against
         * 16, so retuning the knob in P5 moves the numbers, not the check. */
        s = spawn();
        for (i = 0; i < 5 && s.y == 16; i++)
            ship_step(&s, 0);
        check(i >= 2 && s.yf != 0,
              "from rest the whole-pixel y holds for whole ticks while the "
              "fraction byte accumulates the sub-pixel motion");

        /* ... and the position is the EXACT integral of the velocity ramp on
         * every tick: y*256 + yf == sum of GRAV*i for i = 1..n.  A fraction
         * byte in a local produces a sum of v >> 8 instead, which falls behind
         * this by a pixel in the first second and never catches up. */
        /* The count is bounded by the GROUND, not by arithmetic: the spawn is
         * 48 px above the pad and free fall reaches it after about 39 ticks,
         * after which the ship is landing and no longer a free-falling body.
         * 32 leaves margin, and the state assertion below says so out loud --
         * a run that reached the ground would otherwise fail here as though
         * fix_step had broken. */
        s = spawn();
        for (i = 1; i <= 32; i++) {
            uint32_t pos;
            ship_step(&s, 0);
            pos = ((uint32_t)(s.y - 16) << 8) + s.yf;
            if (s.vy != (int16_t)(GRAV * i) ||
                pos != (uint32_t)GRAV * i * (i + 1) / 2)
                break;
        }
        check(i == 33 && s.y > 16 && s.state == ST_FLY,
              "32 ticks of gravity are exactly the 8.8 integral of the "
              "velocity ramp, tick by tick");
    }

    /* ------------------------------------------------------------ P4 ---- */

    {
        /* The WIDTH, which is the trap of the phase.  A unit vector at 8.8 is
         * +-256, which does not fit int8_t -- and an int8_t table does not fail
         * loudly, it folds the cardinals to zero and the diagonals into the
         * wrong quadrant.  On screen that looks like the rotation going the
         * wrong way round, which is a bug hunt in the wrong file. */
        check(sizeof(thrust_dx[0]) == 2 && sizeof(thrust_dy[0]) == 2 &&
              thrust_dx[0] == 0 && thrust_dy[0] == -256,
              "the direction table is int16_t at 8.8 and index 0 is straight "
              "up, dy = -256 -- a byte could not hold that");

        check(thrust_dx[ROT_STEPS / 4] == 256 && thrust_dy[ROT_STEPS / 4] == 0 &&
              thrust_dx[ROT_STEPS / 2] == 0 &&
              thrust_dy[ROT_STEPS / 2] == 256 &&
              thrust_dx[3 * ROT_STEPS / 4] == -256 &&
              thrust_dy[3 * ROT_STEPS / 4] == 0,
              "index 4 is right, 8 is down, 12 is left -- clockwise from up, "
              "the same order mkgfx.py renders the sprite frames in");

        /* ROT_STEPS is a power of two, which is the whole reason sim.h can
         * wrap the heading with a mask: through SDCC a modulo is __divsint. */
        check((ROT_STEPS & (ROT_STEPS - 1)) == 0 && ROT_STEPS > 1,
              "the heading count is a power of two, so the wrap is a mask");
    }

    {
        Ship s;
        int16_t vx0, vy0;
        uint8_t i;

        /* THE TARGET, with the nose up: thrust beats gravity and the net
         * vertical acceleration REVERSES -- vy falls instead of rising.  Held
         * against GRAV and THRUST rather than against 16 and 32, so P5's
         * retuning moves the numbers and not the claim. */
        s = spawn();
        vy0 = s.vy;
        for (i = 0; i < 8; i++)
            ship_step(&s, SHIP_THRUST);
        check(s.vy - vy0 == 8 * (GRAV - THRUST) && s.vy < vy0,
              "nose up, held thrust REVERSES the vertical acceleration: vy "
              "%d -> %d over 8 ticks (want -%d)", vy0, s.vy, 8 * (THRUST - GRAV));
        check(s.fuel == FUEL_START - 8 * FUEL_BURN,
              "and it burned %d fuel units doing it (%d left)",
              8 * FUEL_BURN, s.fuel);

        /* Released, the previous descent resumes EXACTLY -- no leftover thrust
         * applied for a tick or two, no damping: vy gains GRAV per tick. */
        vy0 = s.vy;
        for (i = 0; i < 8; i++)
            ship_step(&s, 0);
        check(s.vy - vy0 == 8 * GRAV,
              "on release the descent resumes at exactly GRAV per tick");
        check(s.fuel == FUEL_START - 8 * FUEL_BURN,
              "and nothing burns while the button is up (%d left)", s.fuel);

        /* The VECTOR, not the magnitude.  Nose right: thrust drives vx and
         * leaves vy to gravity ALONE, which an "upward kick regardless of
         * heading" implementation cannot do. */
        s = spawn();
        s.heading = ROT_STEPS / 4;              /* 90 deg clockwise: nose right */
        vx0 = s.vx;
        vy0 = s.vy;
        for (i = 0; i < 8; i++)
            ship_step(&s, SHIP_THRUST);
        check(s.vx - vx0 == 8 * ((THRUST * thrust_dx[ROT_STEPS / 4]) >> 8) &&
              s.vy - vy0 == 8 * GRAV && s.vx > vx0,
              "nose right, thrust drives vx and leaves vy to gravity alone "
              "(vx %d -> %d, vy %d -> %d)", vx0, s.vx, vy0, s.vy);

        /* ... and a diagonal splits across both axes, the vertical part being
         * the table's dy rather than -THRUST -- the difference between a real
         * rotation and one that only swaps the sprite. */
        s = spawn();
        s.heading = ROT_STEPS / 8;              /* 45 deg: up and to the right */
        vx0 = s.vx;
        vy0 = s.vy;
        for (i = 0; i < 8; i++)
            ship_step(&s, SHIP_THRUST);
        check(s.vx - vx0 == 8 * ((THRUST * thrust_dx[ROT_STEPS / 8]) >> 8) &&
              s.vy - vy0 ==
                  8 * (GRAV + ((THRUST * thrust_dy[ROT_STEPS / 8]) >> 8)) &&
              s.vx > 0 && s.vy < vy0,
              "a diagonal thrust splits across both axes and still climbs "
              "(vx %d -> %d, vy %d -> %d)", vx0, s.vx, vy0, s.vy);
    }

    {
        Ship s;
        int16_t vx0, vy0;
        uint8_t i;
        uint16_t k;

        /* The burn is in the STEP, so this counts steps and not frames: a
         * renderer that burned the tank would come out of here with fuel left
         * over, and the tank would last longer on a slow machine. */
        s = spawn();
        for (k = 0; s.fuel && k < 4 * FUEL_START; k++)
            ship_step(&s, SHIP_THRUST);
        check(s.fuel == 0 && k == FUEL_START / FUEL_BURN,
              "held thrust empties the tank in exactly %d ticks (%d left after "
              "%u)", FUEL_START / FUEL_BURN, s.fuel, k);

        /* THE OTHER HALF OF THE TARGET: an empty tank is not weak thrust, it is
         * NO thrust.  Holding the button changes the trajectory by nothing at
         * all -- vy falls by gravity alone and vx does not move. */
        vx0 = s.vx;
        vy0 = s.vy;
        for (i = 0; i < 8; i++)
            ship_step(&s, SHIP_THRUST);
        check(s.vy - vy0 == 8 * GRAV && s.vx == vx0 && s.fuel == 0,
              "with the tank dry, 8 ticks of held thrust change nothing: vy "
              "falls by GRAV alone and vx stays at %d (vy %d -> %d)",
              s.vx, vy0, s.vy);

        /* Rotation is not fuel: an empty ship can still point itself at the
         * ground, so the failure is in the tank and not in the stick. */
        vx0 = s.heading;
        ship_step(&s, SHIP_ROT_R);
        check(s.heading == (uint8_t)((vx0 + 1) & (ROT_STEPS - 1)),
              "the heading still turns with an empty tank (%d -> %d)",
              vx0, s.heading);
    }

    {
        Ship s;
        uint8_t i;

        /* A/B are one step each and undo each other, so the wrap is a mask and
         * not a modulo that could land a step out.  Both directions, both ends. */
        s = spawn();
        ship_step(&s, SHIP_ROT_R);
        check(s.heading == 1, "B steps the nose one heading clockwise");
        ship_step(&s, SHIP_ROT_L);
        check(s.heading == 0, "and A steps it back, so the two undo each other");

        ship_step(&s, SHIP_ROT_L);
        check(s.heading == ROT_STEPS - 1,
              "A from heading 0 wraps to the last heading, not below zero");
        ship_step(&s, SHIP_ROT_R);
        check(s.heading == 0, "and B wraps back to 0 rather than past the end");

        ship_step(&s, SHIP_ROT_L | SHIP_ROT_R);
        check(s.heading == 0, "A and B in the same tick cancel out");

        /* ... and that a full turn is exactly ROT_STEPS steps, so the table and
         * the sprite bank line up on the same sixteen. */
        for (i = 0; i < ROT_STEPS; i++)
            ship_step(&s, SHIP_ROT_R);
        check(s.heading == 0 && i == ROT_STEPS,
              "ROT_STEPS steps clockwise is a whole turn, back to nose up");

        /* Rotating is free: it is not a burn, and it must not be possible to
         * run the tank down by wiggling the stick. */
        check(s.fuel == FUEL_START,
              "rotation costs no fuel (%d of %d left)", s.fuel, FUEL_START);
    }

    /* ------------------------------------------------------------ P5 ---- */

    {
        /* THE THRESHOLD TABLE, straddled from both sides.  Each edge is
         * pinned by two cases one unit apart, so "just barely safe" and "just
         * barely fatal" are both written down: a `>=` where sim.h has a `>`
         * moves every one of these, and nothing on screen would say so.
         *
         * This block is also the reason a classify_landing() that always
         * answered SAFE could not ship: the TOO_FAST case below it fails, so
         * the landing system is verified rather than assumed.  The verdict has
         * to come out of sim.h -- a check that read the screen would prove the
         * renderer, which is three lines of wiring in main.c. */
        uint8_t pad = pads[PAD_HIGH].col0;
        uint8_t pad1 = pads[PAD_HIGH].col1;
        uint8_t gap = 0;                /* no pad covers column 0 */
        Ship s;

        check(pad_mult(pad) == pads[PAD_HIGH].mult &&
              pad_mult(pads[PAD_LOW].col0) == pads[PAD_LOW].mult &&
              pad_mult(gap) == 0,
              "the pad lookup reads terrain.h's own table: column %d is x%d, "
              "column %d is x%d, column %d is bare", pad,
              pads[PAD_HIGH].mult, pads[PAD_LOW].col0, pads[PAD_LOW].mult, gap);

        /* ---- how fast it arrived (downwards) ---- */
        s = arriving(0, SAFE_VY_MAX, 0);
        check(classify_landing(&s, pad) == LAND_SAFE,
              "arriving at exactly SAFE_VY_MAX (%d) still lands", SAFE_VY_MAX);
        s = arriving(0, (int16_t)(SAFE_VY_MAX + 1), 0);
        check(classify_landing(&s, pad) == LAND_TOO_FAST,
              "and one 1/256 px/frame faster does not -- TOO_FAST");
        s = arriving(0, (int16_t)(-SAFE_VY_MAX), 0);
        check(classify_landing(&s, pad) == LAND_SAFE,
              "a ship still climbing at contact is not arriving too fast "
              "either");

        /* ---- how far sideways ---- */
        s = arriving(SAFE_VX_MAX, 0, 0);
        check(classify_landing(&s, pad) == LAND_SAFE,
              "drifting at exactly SAFE_VX_MAX (%d) lands", SAFE_VX_MAX);
        s = arriving((int16_t)(-SAFE_VX_MAX), 0, 0);
        check(classify_landing(&s, pad) == LAND_SAFE,
              "and the same speed the other way is the same speed");
        s = arriving((int16_t)(SAFE_VX_MAX + 1), 0, 0);
        check(classify_landing(&s, pad) == LAND_DRIFTING,
              "one 1/256 px/frame more is DRIFTING");
        s = arriving((int16_t)(-(SAFE_VX_MAX + 1)), 0, 0);
        check(classify_landing(&s, pad) == LAND_DRIFTING,
              "on both sides -- a one-sided threshold would let the ship slide "
              "left to a landing");

        /* ---- how far off nose-up ---- */
        s = arriving(0, 0, SAFE_TILT);
        check(classify_landing(&s, pad) == LAND_SAFE,
              "a tilt of exactly SAFE_TILT step(s) lands");
        s = arriving(0, 0, (uint8_t)(ROT_STEPS - SAFE_TILT));
        check(classify_landing(&s, pad) == LAND_SAFE,
              "...and so is the same tilt the other way round the circle, "
              "which is where a one-sided test would go wrong");
        s = arriving(0, 0, (uint8_t)(SAFE_TILT + 1));
        check(classify_landing(&s, pad) == LAND_TILTED,
              "one step further round is TILTED");
        s = arriving(0, 0, (uint8_t)(ROT_STEPS - SAFE_TILT - 1));
        check(classify_landing(&s, pad) == LAND_TILTED,
              "on both sides");

        /* ---- and where it arrived ---- */
        s = arriving(0, 0, 0);
        check(classify_landing(&s, pad) == LAND_SAFE &&
              classify_landing(&s, pad1) == LAND_SAFE,
              "the pad's span is exactly its two columns (cols %d..%d)",
              pad, pad1);
        check(classify_landing(&s, (uint8_t)(pad - 1)) == LAND_CRASH &&
              classify_landing(&s, (uint8_t)(pad1 + 1)) == LAND_CRASH,
              "and the columns either side of it are CRASH -- a perfect "
              "landing on ground that is not a pad is still a crash");

        /* The ORDER, pinned.  Which failure a landing that failed several
         * reports is a choice sim.h makes; this is the assertion that stops
         * someone reordering the ifs from changing it silently. */
        s = arriving((int16_t)(SAFE_VX_MAX + 1), (int16_t)(SAFE_VY_MAX + 1),
                     (uint8_t)(SAFE_TILT + 1));
        check(classify_landing(&s, pad) == LAND_TOO_FAST,
              "a landing that fails every test reports the first one sim.h "
              "checks -- TOO_FAST");
        check(classify_landing(&s, gap) == LAND_CRASH,
              "and ground that is not a pad outranks all of them");
    }

    {
        /* The world is 160 px, and every x in it has to name a real column:
         * a ship at the right edge has its CENTRE four px past the end, where
         * terrain[] would be read one byte off. */
        uint16_t x;
        uint8_t off = 0;

        for (x = 0; x < WORLD_W; x++)
            if (ship_col(x) >= WORLD_COLS)
                off++;
        check(off == 0,
              "every x the ship can hold names a column of terrain[] (%d of "
              "%d are off the end)", off, WORLD_W);
    }

    {
        /* The same rule, driven through the step -- which is where the state
         * machine, the resting position and the score live. */
        Ship s, before;
        uint8_t i;
        uint8_t pad = pads[PAD_HIGH].col0;
        uint16_t ground = (uint16_t)((uint16_t)terrain[pad] << 3);
        uint16_t gx = (uint16_t)(pad * 8);      /* ship_col(gx) == pad */

        /* Touching down, not falling into it: already on the surface, and
         * this tick's gravity is the speed it arrives with. */
        s = spawn();
        s.x = gx;
        s.y = (uint16_t)(ground - SHIP_H);
        ship_step(&s, 0);
        check(s.state == ST_LANDED && s.verdict == LAND_SAFE &&
              s.y + SHIP_H == ground && s.mult == pads[PAD_HIGH].mult,
              "a gentle contact sets ST_LANDED, rests it ON the surface and "
              "scores the pad's x%d", pads[PAD_HIGH].mult);

        /* Two px of free fall lands and three does not.  The threshold table
         * above is exact; this is the same edge with the real step bolted on,
         * so a rule that were right in isolation but wired up wrong still
         * fails here. */
        s = spawn();
        s.x = gx;
        s.y = (uint16_t)(ground - SHIP_H - 2);
        for (i = 0; i < 40 && s.state == ST_FLY; i++)
            ship_step(&s, 0);
        check(s.state == ST_LANDED && s.y + SHIP_H == ground,
              "two px of free fall arrives inside SAFE_VY_MAX and lands "
              "(state %d, underside %d of %d)", s.state, s.y + SHIP_H, ground);

        s = spawn();
        s.x = gx;
        s.y = (uint16_t)(ground - SHIP_H - 3);
        for (i = 0; i < 40 && s.state == ST_FLY; i++)
            ship_step(&s, 0);
        check(s.state == ST_CRASH && s.verdict == LAND_TOO_FAST && s.mult == 0,
              "three px of free fall does not -- ST_CRASH, TOO_FAST, nothing "
              "scored (state %d, verdict %d, mult %d)",
              s.state, s.verdict, s.mult);

        /* And a stopped ship STAYS stopped.  Without the state gate at the top
         * of ship_step, the next tick's gravity would carry it through the
         * surface, rewrite the verdict and burn fuel on a ship that is already
         * down. */
        before = s;
        for (i = 0; i < 16; i++)
            ship_step(&s, SHIP_THRUST);
        check(s.y == before.y && s.vy == before.vy && s.vx == before.vx &&
              s.fuel == before.fuel && s.state == before.state &&
              s.verdict == before.verdict && s.mult == before.mult,
              "a crashed ship is frozen: 16 ticks of held thrust move it, "
              "burn it and reclassify it by nothing at all");

        /* The ceiling.  y is a uint16_t, so a climbing ship underflows past
         * zero to about 65000 -- which is "far below the surface" to the
         * contact test, and turns a ship that flew off the top into one that
         * crashed into the ground. */
        s = spawn();
        for (i = 0; i < 60; i++)
            ship_step(&s, SHIP_THRUST);
        check(s.y == 0 && s.state == ST_FLY,
              "a ship thrusting off the top is held at y 0 instead of "
              "underflowing to 65000 and reading as a crash (y %d, state %d)",
              s.y, s.state);

        /* The wrap.  160 is not 256, and these two are the family's named
         * trap: with an `& WORLD_MASK` the first case leaves the ship at
         * x 255, off the right edge of a 160 px world, where it reads as
         * flying away rather than coming round. */
        s = spawn();
        s.y = 0;
        s.x = 0;
        s.vx = -256;
        ship_step(&s, 0);
        check(s.x == WORLD_W - 1,
              "leaving the LEFT edge arrives at x %d, not at 255 (x %d)",
              WORLD_W - 1, s.x);

        s = spawn();
        s.y = 0;
        s.x = (uint16_t)(WORLD_W - 1);
        s.vx = 256;
        ship_step(&s, 0);
        check(s.x == 0,
              "and leaving the RIGHT edge arrives at x 0 (x %d)", s.x);
    }

    /* ----------------------------------------------------------- P10 ---- */

    {
        /* THE SWEEP, and it is a sweep rather than a few samples because the
         * camera's whole behaviour IS this one function: the tracking is exact
         * (the ship is pinned at CAM_ANCHOR on screen) and the two clamps are
         * the only places it stops.  Every altitude from above the world to
         * well below it, so a camera that clamps at the wrong bound -- the BG
         * map's 256 px, which is this phase's named trap -- disagrees with the
         * sweep in the middle and nowhere near its ends.
         *
         * The two worlds are the ROM's own: DESCENT's is three screens tall and
         * is the only one with anywhere to scroll, and LANDER's is under one
         * screen and must therefore never scroll at all.  `bottom` is the
         * world's bound, 680 px -- the map's 256 would be 112, and the two
         * differ by the six hundred px of ground a map-clamped view never
         * reaches.
         *
         * It is the VISIBLE band's bound and not the panel's: P12's status bar
         * covers the last two rows of the screen, so the camera clamps on
         * PLAY_H_PX (128) and not on SCREEN_H_PX (144), and a bound taken on the
         * panel would leave the world's last two rows scrolled under the bar and
         * never seen.  The two differ by 16 px here and would differ by a whole
         * bottom row of world there. */
        const uint16_t tall = 808;      /* DESCENT: deepest row 100, +1 tile  */
        const uint16_t flat = 104;      /* LANDER:  deepest row 12,  +1 tile  */
        const uint16_t bottom = tall - PLAY_H_PX;
        uint16_t y, cam, want, prev = 0;
        uint16_t off = 0, back = 0, third = 0, top = 0, bot = 0;

        for (y = 0; y <= 1100; y++) {
            cam = camera_for(y, tall);
            want = (y > CAM_ANCHOR) ? (uint16_t)(y - CAM_ANCHOR) : 0;
            if (want > bottom)
                want = bottom;
            if (cam != want)
                off++;
            if (cam < prev)
                back++;
            prev = cam;
            /* While the camera is FREE the ship is held at or above the third
             * line.  Once it is pinned at the bottom bound the ship is allowed
             * to sink further, and it must: the last of the world is arriving
             * under it, and a camera that refused to let go would show the ship
             * sliding up the screen as it fell. */
            if (cam < bottom && (uint16_t)(y - cam) > CAM_ANCHOR)
                third++;
            if (y <= CAM_ANCHOR && cam == 0)
                top++;
            if (y >= bottom + CAM_ANCHOR && cam == bottom)
                bot++;
        }

        check(off == 0,
              "the camera is the clamp of ship_y - %d to the WORLD's bounds "
              "[0, %d] -- not the map's 256 px -- at every altitude (%u of 1101 "
              "disagree)", CAM_ANCHOR, bottom, off);
        check(third == 0,
              "and while it is free the ship's on-screen y never drops below "
              "the third line %d (%u altitudes did)", CAM_ANCHOR, third);
        check(back == 0,
              "the camera never moves back UP as the ship descends, so the view "
              "cannot judder (%u altitudes)", back);
        check(top == CAM_ANCHOR + 1,
              "it is pinned at 0 for every altitude at or above the anchor %d, "
              "so the view does not hang off the TOP of the world (%u of %d)",
              CAM_ANCHOR, top, CAM_ANCHOR + 1);
        check(bot == 1101 - (bottom + CAM_ANCHOR),
              "and pinned at the world bound %d once the ship is within a "
              "screen of the ground (%u altitudes), which is where the map's "
              "256 px would stop the view instead", bottom, bot);

        /* The other trap the bound hides: a world with nowhere to scroll.  The
         * bottom bound is `world_h - SCREEN_H_PX` and world_h is a uint16_t, so
         * an unguarded subtraction here wraps to ~65000 and the camera would
         * slam to the bottom of a world that has no bottom -- LANDER's view
         * would be yanked off its ground on the first tick of a life. */
        off = 0;
        for (y = 0; y <= 1100; y++)
            if (camera_for(y, flat) != 0)
                off++;
        check(off == 0,
              "a world shorter than the screen (%d px against %d) never scrolls "
              "-- the bottom bound is 0, not a wrap (%u altitudes)",
              flat, SCREEN_H_PX, off);

        /* ...and the same underflow from the top: a ship at the very top of a
         * tall world has a negative offset, which as an unsigned uint16_t is
         * ~65000 and reads to the min above as "the camera is at the bottom". */
        check(camera_for(0, tall) == 0 && camera_for(CAM_ANCHOR, tall) == 0 &&
              camera_for((uint16_t)(CAM_ANCHOR + 1), tall) == 1,
              "and a ship at the top of the world is camera 0, not 65000 "
              "(y 0 -> %u, y %d -> %u)", camera_for(0, tall), CAM_ANCHOR,
              camera_for(CAM_ANCHOR, tall));

        /* The screen height is a hardware constant that sim.h and main.c each
         * carry a copy of -- main.c's is a build error if the two drift, and
         * this is what says the number itself is the panel's. */
        check(SCREEN_H_PX == 144 && CAM_ANCHOR == 48 && CAM_ANCHOR * 3 == SCREEN_H_PX,
              "the screen is the DMG's 144 px and the anchor is a third of it "
              "(%d, %d)", SCREEN_H_PX, CAM_ANCHOR);
    }

    /* ----------------------------------------------------------- P12 ---- */

    {
        /* THE BOTTOM BOUND IS ON WHAT IS VISIBLE, not on the panel.  P12's
         * telemetry is a WINDOW at the bottom of the screen, and a window always
         * runs to the bottom-right corner -- so the last rows of background are
         * COVERED and the camera has no business scrolling world into them.
         *
         * The failure this pins is silent.  A clamp two rows too generous leaves
         * the world's last rows under the status bar, so the ground at the end of
         * a descent never comes into view while every frame on the way down still
         * looks like a working camera.  `tall` is the ROM's own DESCENT world,
         * whose deepest surface row is 100, so the rows the bar would hide are
         * exactly rows 100 and 101 -- the ground. */
        const uint16_t tall = 808;                  /* DESCENT, as in P10 */
        const uint16_t vis_bound = tall - PLAY_H_PX;
        const uint16_t panel_bound = tall - SCREEN_H_PX;

        check(PLAY_H_PX < SCREEN_H_PX && (SCREEN_H_PX - PLAY_H_PX) % 8 == 0 &&
              CAM_ANCHOR < PLAY_H_PX,
              "the visible band is the panel minus whole status-bar rows and the "
              "ship still rides in the upper part of it (%d px of %d, %d rows "
              "less; anchor %d)",
              PLAY_H_PX, SCREEN_H_PX, (SCREEN_H_PX - PLAY_H_PX) / 8, CAM_ANCHOR);

        /* At the bound, the world's LAST row is the last row the player can
         * see.  One px short of the world's end so the camera is unambiguously
         * past its free window and onto the clamp. */
        check(camera_for((uint16_t)(tall - 1), tall) == vis_bound &&
              vis_bound + PLAY_H_PX == tall,
              "at the bottom bound the world's last row is the last VISIBLE row "
              "(cam %u, world %d px, visible to %u)",
              camera_for((uint16_t)(tall - 1), tall), tall,
              vis_bound + PLAY_H_PX);

        /* ...and the rows the PANEL's bound would hide are the ground.  Stated
         * as "the world's end is under the bar" rather than as an offset, because
         * that is what the bug is: at 664 the band stops 16 px short of the
         * world, and those 16 px are the last two tile rows of DESCENT. */
        check(panel_bound + PLAY_H_PX < tall && vis_bound + PLAY_H_PX >= tall,
              "the panel's bound %u would leave the world's last 16 px (%d px) "
              "scrolled under the bar, where the visible bound %u does not "
              "(visible to px %u against %u)",
              panel_bound, tall, vis_bound, vis_bound + PLAY_H_PX,
              panel_bound + PLAY_H_PX);

        /* A world no taller than the visible band still has nowhere to scroll --
         * LANDER's is 104 px -- so the `>` that guards the subtraction has to
         * hold at the NEW bound too and not only at the old one. */
        check(camera_for(120, 104) == 0 && camera_for(120, PLAY_H_PX) == 0 &&
              camera_for(PLAY_H_PX, PLAY_H_PX) == 0,
              "a world no taller than the visible band never scrolls, and the "
              "bound is 0 rather than a ~65000 wrap");
    }

    if (failed) {
        printf("FAILED: %d of %d checks\n", failed, checks);
        return 1;
    }
    printf("OK: %d checks passed\n", checks);
    return 0;
}
