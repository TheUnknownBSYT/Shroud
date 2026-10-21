# SHROUD · Training Grounds

A Python / pygame-ce action game with a handcrafted scrolling training compound,
the original ninja sprites, and Shadow Echo: dash away and let your shadow repeat an attack.
There is no profiling, recording, network code, or persistence.

## Run

From this directory:

```sh
.venv/bin/python main.py
```

First-time setup on another machine (Python 3.10+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

On Windows, use `py -m venv .venv`, then `.venv\Scripts\python` instead.
Keep both `ninjas/` and `TrainingGrounds/` next to `main.py`. The existing art, sprite organizer, and old
`ninjas/.venv` have not been changed. See [the asset notes](docs/assets.md).

## Controls

| Input | Action |
| --- | --- |
| WASD / arrows | Move |
| Space | Dash and leave an Echo |
| Mouse movement | Smoothly turn the aim arrow toward the cursor |
| Left mouse button | Hold to charge a slash; release to slash / timed deflect |
| Right mouse button | Hold to focus a shuriken; release to throw |
| J / K | Instant slash / shuriken in the facing direction |
| F1 | Debug world position, camera, collisions, spawns, FPS, combat/Echo state |
| P | Pause / resume |
| R | Restart the entire level, including encounters and statistics |
| Esc | Quit |

Mouse movement smoothly rotates the mint aim arrow, including while moving.
The player can strafe while aiming. Inside an 8-pixel circle around the player,
the aim holds steady to avoid jitter. WASD/arrows still set facing before the
mouse is first used. A moving dash follows movement; a standing dash follows aim.
Once an attack starts, its direction is locked while the arrow can keep turning
for the next attack. Keyboard J/K remain instant attacks without mouse spread.

Quick right-click releases throw with up to **±3°** random spread. Holding for
**0.45 seconds** closes the guide to a precise shot, with no random spread.
The guide marks the current shuriken range; walls can block the shot. Aim is
captured from the arrow when you release, so wait for it to settle after a flick.

Hold left-click for up to **0.75 seconds** to build a slash from normal strength
to **2× damage and 1.4× reach**. The arc and meter show its charge. A quick tap
still slashes. Charge does not parry: the deflection window opens on release
when the slash starts. This is a melee slash, with the usual timing and cooldown.
Holding either mouse button does not automatically attack or repeat. The first
held attack takes priority if both buttons are pressed. Dash, taking damage,
pause, focus loss, and reset cancel a held attack; press again to start another.
Movement continues during charging, slashes, and throws.

Dashes deal damage but do not grant invulnerability. Gold rings show a
sentry aiming its next shot; slash toward a gold bolt just before it reaches you
to reflect it. Defeated targets stay down until restart. Sentries activate only
within 620 pixels with an unobstructed view; their existing attack timings remain intact.

## Shadow Echo rules

- An accepted dash leaves one stationary Echo at its starting position. A dash
  rejected by cooldown does nothing. A new dash replaces any previous Echo,
  including one with an attack queued.
- The Echo waits for up to **3 seconds**. The next slash or throw that actually
  starts queues its repeat; rejected inputs do not consume it.
- The action and a copy of its direction are captured immediately. After
  **0.35 seconds**, the Echo attacks from its own position in that same direction.
  Moving or aiming elsewhere afterward cannot steer the queued attack.
- A slash preserves the released charge's damage and reach, forward arc, active frames, one-hit-per-target
  rule, and opening parry window as the player. Echoes can reflect enemy bolts.
- A throw launches one normal shuriken without using the player's active-star
  allowance. It has the same damage, speed, range, and collision rules.
  It captures the original throw's actual direction, including any spread;
  the Echo does not roll a second random deviation.
- The Echo plays its action, then fades over **0.18 seconds**. It repeats only
  one action. An unused Echo also fades when its waiting time runs out.
- Queuing just before expiry commits the attack: it still gets its full delay
  and animation. The Echo has no health, AI, movement, or physical collision.
- Pause (including loss of window focus) freezes all Echo timers. Reset removes
  the Echo and projectiles. Player death removes the Echo; R starts again.

Try dashing past a sentry, then aiming a slash back toward the place you left.
For a remote deflection, dash away from a bolt's path and slash early enough
that the Echo's opening parry window meets the bolt at your old position.

## Simple project structure

```text
main.py       Arguments, pygame startup, and shutdown
settings.py   All tuning values and input bindings
player.py     Commands, player states, ShadowEcho, animation clock, sprite loading
enemy.py      One stationary sentry type and its telegraphed shot
combat.py     Health, attack geometry, projectiles, shared damage and parry rules
game.py       Input handling, simulation, events, completion, main loop
level.py      Handcrafted map data, props, world collision, camera
drawing.py    Environment PNGs, sprites, HUD, effects, and debug display
TrainingGrounds/  35 original environment PNG exports (29 used)
ninjas/       Original assets and organizer (kept in place)
tests/        Gameplay, Echo, mouse, camera, route, and completion tests
docs/         Asset inspection notes
```

The source remains flat. `level.py` keeps map layout and camera/collision code
together; `drawing.py` keeps graphics calls out of the main loop.
`Sandbox` in `game.py` can run without a window, which keeps tests fast.
`Game` reads input, advances that simulation, and asks `Renderer` to draw it.
The original 120 Hz simulation / 60 FPS render loop and movement/combat values
are retained. Wall movement uses small steps; projectiles sweep their paths.

Old structure:

```text
main.py
src/shroud/
  main.py, game.py
  core/       settings.py, input.py, animation.py, events.py
  entities/   entity.py, player.py, enemy.py
  combat/     hitbox.py, damage.py, projectile.py
  world/      room.py, sandbox.py
  ui/         renderer.py, debug.py
```

The nested source tree and its empty package files were removed after migration:

| Old files | New home / reason |
| --- | --- |
| Root launcher + `shroud/main.py` | `main.py`; no path injection or second entry point |
| `game.py`, `room.py`, `sandbox.py`, input reader, `events.py` | `game.py` for orchestration; `level.py` for map/collision |
| `player.py`, `animation.py`, input command data | `player.py`; player behaviour and its art together |
| `enemy.py` | Root `enemy.py`; unchanged enemy type |
| `entity.py`, `hitbox.py`, `damage.py`, `projectile.py` | `combat.py`; shared health and combat rules together |
| `renderer.py`, `debug.py` | `drawing.py`; all presentation together |
| `settings.py` | Root `settings.py`; one obvious tuning file |

Dependencies flow from `main` to `game`; `game` uses `player`, `enemy`, `combat`,
`level`, and `drawing`. Both player and enemy use combat; drawing reads their states.
All use settings. Combat never imports the game or renderer.

## How Echo works in code

`Sandbox.step()` sees the action returned by `Player.tick()`. A dash creates
`ShadowEcho` before the player's position changes. A slash/throw asks that Echo
to queue the action and copied direction. Each simulation step advances its
small state machine:

`WAITING → ATTACK_QUEUED → ATTACKING → FADING → EXPIRED`

An unused Echo goes directly from waiting to fading. `combat.py` supplies
`make_slash`, `make_shuriken`, attack timing, melee resolution, and parry checks
to both player and Echo. Each slash has its own set of already-hit enemy IDs.
The renderer uses the original directional frames with a muted translucent tint.

The small optional event callback helper remains in `game.py`; it saves no
history. Existing game events are preserved, with `echo_parry` for an Echo
reflection. Simulation timestamps stay monotonic across reset.

## Tuning and checks

Edit `settings.py` and restart. Echo settings are `ECHO_DELAY = 0.35`,
`ECHO_LIFETIME = 3.0`, `ECHO_ALPHA = 145` (0–255), and
`ECHO_FADE_DURATION = 0.18`. Keep durations positive.

Mouse tuning: `MOUSE_AIM_RESPONSE = 24.0` controls smoothing (higher is tighter),
`MOUSE_AIM_DEADZONE = 8.0` prevents jitter near the player, and
`SHURIKEN_SPREAD = 3.0` is the maximum deviation in degrees on either side.
`SHURIKEN_FOCUS_TIME = 0.45` and `SLASH_CHARGE_TIME = 0.75` set hold durations.
`SLASH_CHARGE_DAMAGE = 2.0` and `SLASH_CHARGE_REACH = 1.4` set full-charge
multipliers. Keep response and durations positive; spread can be zero.

Existing `PLAYER_SPEED`, `ACCELERATION`, `FRICTION`, `DASH_*`, `SLASH_*`,
`PARRY_*`, `SHURIKEN_*`, enemy values, and `BINDINGS` remain there. Zero
acceleration/friction means immediate start/stop. Slash damage starts at 0.06s
and ends at 0.22s; the parry window lasts 0.12s.

```sh
.venv/bin/python -m pytest -q
.venv/bin/python main.py --headless --frames 120 --screenshot /tmp/shroud.png
```

All **61 tests pass**, including the 48 pre-existing cases. The suite covers combat and Echo rules, mouse charging/focus,
camera clamping and transforms, wall clearance, both branches, encounter gates,
local sentry activation, statistics, completion, and restart. The five-minute
deterministic simulation regression still runs with Echo enabled.

## Playing the level

The world is **6144×3840 pixels**, with a fixed 1280×800 window. Enter from the
southwest movement grounds, head east into the courtyard, and clear its five
marked targets to open the north gate. At the fork, the direct stone crossing
has three sentries; the longer garden path offers cover and an optional target.
Both meet at the eastern yard. Head north, clear the five final-yard targets,
then follow the westward walkway into the lantern-marked exit garden.

There are 17 targets total; seven are optional. Completion requires both main
encounters and reaching the exit. The summary shows active simulation time,
targets defeated, health lost, successful deflections (player or Echo), and
accepted enemy hits credited to the Echo. Pause time is excluded. R resets the
whole run. Nothing is saved to disk.

## Editing the level

Edit `TRAINING_GROUNDS` in `level.py`, then restart. Coordinates use **96-pixel
floor tiles**; `.5` is the kit's original 64-pixel grid at the runtime scale.
The PNGs are scaled to 75%, with original transparent canvases preserved.

| Field | Format / purpose |
| --- | --- |
| `size` | World width, height in tiles; camera and collision bounds |
| `spawn` | Player center `(x, y)` |
| `exit` | Completion rectangle `(x, y, width, height)` |
| `floors` | `(material, x, y, width, height)`, integer tile rectangles; earth, stone, mat, platform; later entries overwrite earlier tiles |
| `props` | `(asset, center_x, center_y, rotation)`; rotations 0/90/180/270; solids defined in `SOLID_SHAPES` |
| `decorations` | Same format, ground layer without collision |
| `enemies` | `(group, sprite, x, y, shoots)`; false makes a passive target using the same Enemy class |
| `gates` | `(group, rectangle)`; solid fence until every enemy in that group is defeated |
| `areas` | `(name, rectangle, objective)`; first matching region supplies the HUD text |
| `signs` | `(text, x, y)` for short ground directions |

Touching floor rectangles connect automatically; exposed edges receive wall
sprites and collision. Add adjoining rectangles for a new branch, and props
for cover. `SOLID_SHAPES` contains source-pixel collision rectangles independent
of each sprite's canvas. `ASSET_SIZES` supplies non-128×128 prop sizes; update
both when adding a solid asset. Gates use two post colliders with open centers;
trees block at their trunks. Grass, markings and ground shrubs do not block.
The level is loaded once; editing data is not a live level editor.

`Camera.follow` approaches a clamped target with exponential smoothing. The
visible world occupies `(0, 128, 1280, 608)` below the HUD. Drawing subtracts
camera offset and adds viewport origin; mouse aiming applies the inverse.
Physics and Echo positions never depend on the camera. Visible tiles/props
are culled, and nearby wall buckets reduce collision checks. `CAMERA_RESPONSE`
in `settings.py` controls follow speed without changing player movement.

The 2–4 minute first-play pacing is a design target awaiting human playtesting.
Automated traversal and brief native/headless render checks do not measure
combat difficulty or comfort. The game retains four-direction character art,
approximate collision shapes, a fixed window, and no audio. See
[asset dimensions, usage and collision notes](docs/assets.md).
