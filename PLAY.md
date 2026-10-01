# How to play LUNA LANDER

A lunar lander for the Game Boy — bring the ship down on a pad, in one piece,
without much fuel to spare. Twelve levels to a mode, and a landing takes you to
the next one.

Load it in an emulator, or flash it to a cartridge, and it runs on an original
Game Boy, a Game Boy Color, or any emulator. On the title screen, START begins
the level the title names.

There is a single-page version of this guide — the same material, plus a chart
of the safe landing envelope and a review of the game — in
[luna-lander-field-guide.html](luna-lander-field-guide.html). Open it in a
browser.

## Controls

| Button | What it does |
|--------|--------------|
| d-pad LEFT / RIGHT | push the ship that way. **Hold one** to keep pushing — the ship leans into it and picks up speed, and it straightens up again the moment you let go |
| A or B | thrust. **Hold one** to keep burning — the engine runs as long as you hold, and the tank empties the whole time |
| START | after a **landing**, go on to the next level; after a **crash**, try the same level again; while flying, start the level over; on the title, begin |
| SELECT | back to the title screen — in flight, or after a landing or a crash. On the title it switches between the two modes, and **your level is kept** |

LEFT and RIGHT are held, like the engine, and not one step per press: the ship
leans over and its speed sideways builds for as long as the direction is down.
Let go and it stands upright again immediately, and the drift dies away on its
own over the next moment. Pushing sideways burns fuel at the same rate as
thrusting does.

On the title screen, SELECT picks between **LANDER** and **DESCENT**, and START
plays whichever one the title names — at **the level number on that line**, not
from the beginning. SELECT in flight goes back there, so a mode you did not mean
to be in is one press away from the one you did, and leaving does not cost you
your place. They are the same ship, the same landing rule and the same tank;
what differs is the world.

- **LANDER** — the short world. One 160-pixel screen, wrapping left to right.
  The ground sits low on it and the ship opens with most of a screen of air
  underneath, so there is something to fall through. It is what the game starts
  on. Twelve levels.
- **DESCENT** — the tall one. The ship opens at the top, up to a hundred tile
  rows above the pad, and the view scrolls down after it. Twelve levels.

## The levels

Each mode is a **chain of twelve levels**, and they are the same twelve every
time you play them. Level 3 of LANDER is one fixed piece of ground, on this
cartridge and on the next one; nothing about a level is decided as you play it.
The only thing that changes between them is the shape of the ground, where the
pads are and where the ship starts — gravity, the engine and the three landing
rules are identical on all twenty-four.

- **Land well and you move on.** The page after a landing says so, and START
  takes you to the next level.
- **Crash and you get the same level back.** Nothing is lost but the time it
  took to fall.
- **Finishing the twelfth ends the chain**, with a page of its own. START there
  plays the twelve again from level 1 — **on a smaller tank.** That is the whole
  of the difficulty curve: the layouts never get harder, but the fuel gets
  tighter, one step a lap, until it settles at half of what you started with.
- **Your place is remembered.** SELECT back to the title and the mode line still
  says which level you are on; START picks it up from there.

The two modes keep their own places, so switching to DESCENT and back to LANDER
returns you to whichever level of LANDER you had reached.

## Flying the ship

Gravity is always pulling the ship down, and the engine is the only thing that
beats it. The engine pushes along the nose, and the nose only ever points
straight up or leans into a sideways push — so controlling the descent is the
engine's job, and the d-pad is for moving it across.

A sideways push does not last: let go of the direction and the nose comes back
upright, and the drift runs out by itself. Cancel a drift by pushing the other
way and then letting go, rather than by steering the nose round at it.

The ship's world wraps around. Fly off the left edge and you arrive at the
right one; the terrain is built so the join is invisible.

**Fuel is the whole clock.** A full tank is about ten seconds of held thrust
spent all at once, and nothing puts a drop of it back while you are flying.
Every landing is a bet about how much of that you can afford to spend getting
down — the HUD's FUEL reading is a running countdown, and thrust does nothing at
all once it reaches zero.

The tank is filled again at the start of every level, so a level that took more
than it should have does not follow you into the next one — but **each lap round
the twelve gives you less**, and after five of them you are flying on half a
tank.

## Landing

Put the ship down on a **pad** — a flat, marked platform. A pad is a bright, lit
stretch of ground; everything else on the ground is unmarked and fatal.
Coming to rest anywhere but a pad is a crash, however gently you did it.

Three more things have to be true at the moment you touch down:

- **Come down slowly.** A hard descent is a crash even on a pad.
- **Don't drift sideways.** The ship has to be moving sideways hardly at all
  when it lands, so cancel your sideways speed before you arrive.
- **Keep the nose up.** The ship must be close to vertical — within about
  22.5° of straight up. Letting go of the d-pad stands it up, so this one is
  about not still pushing when you arrive.

You do not have to be perfectly upright-vertical or exactly motionless; there is
a little room in all three. The margins are small enough that the way to land
well is to arrive already under control rather than to correct at the last
instant.

The ship starts every level in the air above the higher-value pad with gravity
already pulling it down, so a life with nobody at the controls is a crash. In
LANDER that is a moment later. In DESCENT it is several seconds of falling — a
long fall builds speed, and speed is the thing the landing rule punishes, so the
descent has to be flown rather than merely fallen. That is by design: the game
begins at the point where the landing does.

## The pads

Every level has **one or two pads**, and they are not in the same place from one
level to the next — finding them is part of reading a new piece of ground.

| Pad | Score |
|-----|-------|
| the **smaller** pad | ×2 |
| the **larger** pad | ×1 |

The higher-value pad is always the smaller one. Both are flat and both are drawn
as a lit deck, so where they are is something you can see rather than something
you have to read off the bar — and the bar still names the multiplier of the pad
you are over **while flying**. Which one you actually landed on is the ending
page's job to say.

You always start above the ×2 pad, so the tempting one is the one you are
already lined up on.

## The end of a life

Every ending takes over the whole screen with a page of its own.

**LANDED** comes up the moment the ship settles on a pad, and says two things:
the pad's multiplier — **X1** or **X2** — and **FUEL LEFT**, how much of the tank
was still in it when you touched down. That number is the story of the level: a
landing that spent 500 of its 600 units got down, but it got down by burning.

**CRASHED** comes up once the ship has blown apart. The explosion plays out over
the wreck first — that is the ship being destroyed, and it is worth watching —
and then the page says why, in the game's own words:

| It says | Because |
|---|---|
| **NO PAD** | you came down somewhere that is not a landing pad |
| **TOO FAST** | you were still falling too quickly when you arrived |
| **DRIFTING** | you were still moving sideways when you arrived |
| **TILTED** | the nose was too far off vertical when you arrived |

Only one is ever printed, and they are checked in that order — so a touchdown on
ordinary ground reads **NO PAD** whatever else the arrival looked like.

**MISSION COMPLETE** comes up instead of LANDED when you put the ship down on
the twelfth and last level of a chain. It names the lap you just finished and
the tank the next one starts on — which is **smaller** than the one you had.

From any of these pages, **SELECT** goes back to the title (and keeps your
place). **START** is the one that depends on how the life ended:

| The page | What START does |
|---|---|
| **LANDED** | on to the next level |
| **CRASHED** | the same level again |
| **MISSION COMPLETE** | the twelve again from level 1, on a smaller tank |

While you are still flying, START restarts the level you are on.

## What you're looking at

The **bottom** two rows of the screen are the instrument panel. It sits over the
ground rather than beside it: the world you can see is the 128 pixels above those
two rows, and everything below them is hidden:

- **FUEL** — the tank, in three digits. It starts at 600 and counts down while
  the engine is running — and it starts **lower on every lap round the twelve**,
  down to 300. At zero, thrust does nothing.
- **ALT** — your height, in pixels, above the ground directly underneath the
  ship. It counts down to 0 as you touch down, and it is the number that tells
  you whether you have room to correct.
- **VX** — sideways speed, in pixels per frame. Positive is to the right.
- **VY** — descent speed, in pixels per frame. Positive is downwards, and this
  is the one to watch before you land: it has to be small when you arrive.
- **PAD X2** — the multiplier of the pad under you *right now*, while you are
  still flying. X2 over the small pad, X1 over the big one, and **X0 when there
  is no pad under you at all** — which is the spot you do not want to land on.
- **CRASHED** — the ship has blown apart. It is on the bar only while the
  explosion lasts; then a page takes over the screen — see **The end of a
  life**.

VX and VY read 0 until the ship is moving at least a whole pixel a frame, so
early in a life they may still say 0 while the ship is drifting down slowly.

An ending page clears the whole panel away along with the world: it is reading
out a flight, and the flight is over.

The ship itself is the little craft above the middle of the screen. In **LANDER**
the view is fixed and the ship moves across it. In **DESCENT** the ship holds
that line on the screen and the world scrolls up past it, so the panel is reading
out a descent you are watching happen. Either way the view does not scroll
sideways: the whole 160-pixel world wraps around at the edges, so flying off the
left takes you to the right.

The sky is not empty. A field of stars fills everything above the ground, and it
is there to be **read**. High up, the ground is off the screen entirely and the
ship is the only other thing moving, so a descent at a steady few pixels a frame
looks like hovering — the ground arrives by surprise. The stars are fixed to the
world, so how fast they travel past you is your speed: in **LANDER** they stand
still and the ship crosses them, in **DESCENT** they scroll up with the ground.

On a **Super Game Boy** there is one more thing: the screen is framed by a small
scene — a rocket standing either side of it on the lunar surface, and a porthole
rim around the window, as if the view is out of the ship. Nothing about it
changes how the game plays, and on anything else — a Game Boy, a Game Boy Color,
an emulator that is not emulating a Super Game Boy — it is simply not there.

## If you keep crashing

The crashed page names the one that got you. These are what to do about it:

- **Landing hard on a pad?** Watch VY. It needs to be small by the time ALT
  reaches 0 — start slowing down while there is still height to do it in.
- **Sliding off sideways?** Watch VX. Push the other way to take it off, then let
  go and let the drift run out before you touch down; do not try to fix it in the
  last few pixels.
- **Crashed onto flat-looking ground?** If PAD read X0 you were not on a pad at
  all. Only the marked platforms count, and the terrain beside them is as fatal
  as a cliff. Look for the lit deck before you commit to a column.
- **Out of fuel?** You spent too much holding the engine on. Short bursts cost
  far less than a long burn, and gravity is free.
