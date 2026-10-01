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

/* A ship exactly as main.c spawns it: rest, nose up, full tank.  Every case
 * below starts from here rather than from whatever the last one left behind. */
static Ship spawn(void)
{
    Ship s;

    s.x = 80;
    s.y = 16;
    s.xf = 0;
    s.yf = 0;
    s.vx = 0;
    s.vy = 0;
    s.heading = 0;
    s.fuel = FUEL_START;
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
        s = spawn();
        for (i = 1; i <= 60; i++) {
            uint32_t pos;
            ship_step(&s, 0);
            pos = ((uint32_t)(s.y - 16) << 8) + s.yf;
            if (s.vy != (int16_t)(GRAV * i) ||
                pos != (uint32_t)GRAV * i * (i + 1) / 2)
                break;
        }
        check(i == 61 && s.y > 16,
              "sixty ticks of gravity are exactly the 8.8 integral of the "
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

    if (failed) {
        printf("FAILED: %d of %d checks\n", failed, checks);
        return 1;
    }
    printf("OK: %d checks passed\n", checks);
    return 0;
}
