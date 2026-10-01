# How to play LUNA LANDEER

A lunar lander for the Game Boy — bring the ship down on a pad, in one piece,
without much fuel to spare.

Load it in an emulator, or flash it to a cartridge, and it runs on an original
Game Boy, a Game Boy Color, or any emulator. On the title screen, START begins
a life.

## Controls

| Button | What it does |
|--------|--------------|
| d-pad UP | thrust. **Hold it** to keep burning — the engine runs as long as you hold, and the tank empties the whole time |
| A | turn the nose one step to the left (anticlockwise) |
| B | turn the nose one step to the right (clockwise) |
| START | start a new life — while flying, or after a landing or a crash |
| SELECT | on the title screen, switch between the two modes |

A and B are one step per press: holding one down turns the ship once, not
continuously. There are sixteen steps in a full turn.

On the title screen, SELECT picks between **LANDER** and **DESCENT**. LANDER is
what the game starts on. DESCENT is not playable yet — starting a game gives you
LANDER whichever one the title names.

## Flying the ship

Gravity is always pulling the ship down, and the engine is the only thing that
beats it. The nose points the way the engine pushes, so you steer by rotating
and then thrusting: turn to face the direction opposite your drift, burn briefly,
then straighten up again.

The ship's world wraps around. Fly off the left edge and you arrive at the
right one; the terrain is built so the join is invisible.

**Fuel is the whole clock.** A full tank is about ten seconds of held thrust
spent all at once, and there is no refill. Every landing is a bet about how much
of that you can afford to spend getting down — the HUD's FUEL reading is a
running countdown, and thrust does nothing at all once it reaches zero.

## Landing

Put the ship down on a **pad** — a flat, marked platform. Coming to rest
anywhere else is a crash, however gently you did it.

Three more things have to be true at the moment you touch down:

- **Come down slowly.** A hard descent is a crash even on a pad.
- **Don't drift sideways.** The ship has to be moving sideways hardly at all
  when it lands, so cancel your sideways speed before you arrive.
- **Keep the nose up.** The ship must be close to vertical — within about
  22.5° of straight up.

You do not have to be perfectly upright-vertical or exactly motionless; there is
a little room in all three. The margins are small enough that the way to land
well is to arrive already under control rather than to correct at the last
instant.

The ship starts every life in the air above the higher-value pad with gravity
already pulling it down, so a life with nobody at the controls is a crash a
moment later. That is by design: the game begins at the point where the landing
does.

## The pads

| Pad | Where | Score |
|-----|-------|-------|
| LOW | left of centre | ×1 |
| HIGH | right of centre | ×2 |

The higher-value pad is the smaller one. Both are flat, and the HUD names the
multiplier when you land on one.

## What you're looking at

The top two rows of the screen are the instrument panel, and they never cover
the ground:

- **FUEL** — the tank, in three digits. It starts at 600 and counts down while
  the engine is running. At zero, thrust does nothing.
- **ALT** — your height, in pixels, above the ground directly underneath the
  ship. It counts down to 0 as you touch down, and it is the number that tells
  you whether you have room to correct.
- **VX** — sideways speed, in pixels per frame. Positive is to the right.
- **VY** — descent speed, in pixels per frame. Positive is downwards, and this
  is the one to watch before you land: it has to be small when you arrive.
- **LANDED X2** — you made it, and that is the pad's multiplier.
- **CRASHED** — that life is over. START begins a new one.

VX and VY read 0 until the ship is moving at least a whole pixel a frame, so
early in a life they may still say 0 while the ship is drifting down slowly.

The ship itself is the little craft in the middle of the sky; the terrain below
it scrolls past as the ship moves, and the whole 160-pixel world wraps around at
the edges.

## If you keep crashing

- **Landing hard on a pad?** Watch VY. It needs to be small by the time ALT
  reaches 0 — start slowing down while there is still height to do it in.
- **Sliding off sideways?** Watch VX. Thrust briefly against your drift and
  level out before you touch down; do not try to fix it in the last few pixels.
- **Crashed onto flat-looking ground?** Check it is actually a pad. Only the two
  marked platforms count, and the terrain between them is as fatal as a cliff.
- **Out of fuel?** You spent too much holding the engine on. Short bursts cost
  far less than a long burn, and gravity is free.
