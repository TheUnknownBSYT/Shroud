# SHROUD

SHROUD is a top-down action game built with Python and pygame-ce. Fight through
handcrafted maps using slashes, shuriken, dashes and a Shadow Echo that repeats
your next attack from the spot you left behind.

Each run contains **five different layouts** sampled from a collection of 18.
Every level independently receives a training grounds, snow, marsh, crosswind or bamboo
biome. Clear the required enemy groups, open the seals and reach the exit.

## Install and play

Requires **Python 3.10 or newer**.

```sh
git clone https://github.com/TheUnknownBSYT/Shroud.git
cd Shroud
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

On Windows, create and activate the environment with:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Run the game from the cloned source tree so the map data and artwork are available.

## Controls

| Input | Action |
| --- | --- |
| WASD / arrow keys | Move |
| Mouse | Aim independently while moving |
| Tap Space | Dash on release and leave a Shadow Echo |
| Hold Space | Sprint; release to stop |
| Hold / release left mouse | Charge and release a slash |
| Hold / release right mouse | Focus and throw a shuriken |
| J / K | Immediate slash / shuriken |
| Enter | Continue after completion or retry after death |
| R | Restart the current level with a newly rolled biome |
| F2 | Choose the first layout and biome for a new run |
| B (in F2 menu) | Cycle Random / Grounds / Snow / Marsh / Wind / Bamboo |
| Tab | Pause and show the full map |
| P | Pause / resume |
| F1 | Toggle collision and combat debugging |
| Esc | Close an overlay, or quit |

Space held for 0.18 seconds starts sprinting; a shorter press dashes on release.
Sprinting blocks attacks. Slashing toward an incoming bolt during the opening
attack window can reflect it. Dashes deal damage but do not grant invulnerability.

## Shadow Echo and progression

A dash leaves one stationary Echo. Your next accepted slash or throw queues its
repeat after **0.35 seconds**, preserving the attack direction and slash charge.
An unused Echo expires after **3 seconds**; another dash replaces it.

Gold markers identify enemies required to open a seal. Other encounters can be
left unfinished. After opening all seals, reach the exit and press Enter to
continue. The run ends after its configured number of levels.

Refuges restore health once and unlock a checkpoint retry. Enter after death
retries that checkpoint with the same biome. R restarts the entire current level
and rolls its biome again. F2 starts a fresh run. Progress is held in memory and
is lost when the game closes.

## Run options

```sh
python main.py --levels 3                   # Choose a run length from 1 to 18
python main.py --level rooftop_03           # Choose the first layout
python main.py --levels 5 --seed 42         # Reproduce layout and biome draws
python main.py --list-levels                # List all available layouts
python main.py --level temple_01 --biome bamboo --levels 1  # Try breakable cover
```

Layouts do not repeat within a run; biome draws can repeat. A seed reproduces
layout/biome choices for the same sequence of level loads. Combat spread and
visual effects have their own randomness. Map names and IDs such as `snow_01`
identify geometry and do not restrict the selected biome. `--biome` pins a biome
for the run and restarts; omit it for random selection. In F2, press B to choose
any biome or return to Random, then Enter to start. Random gives each biome a 20%
chance per load, so a five-level run need not contain every biome. The selector
shows layout dimensions separately from the biome choice.

## Biomes

Every layout supports all five gameplay conditions:

| Biome | What changes |
| --- | --- |
| Training grounds | Immediate movement and full visibility |
| Snow | Accelerate into movement and slide when braking; sprint needs more stopping room |
| Marsh | Distant scenery and enemies fade into mist; enemies attack only inside the clear radius. Incoming shots remain visible, and Tab keeps landmarks but hides distant enemies |
| Crosswind | Three seconds calm, one-second directional warning, then an eight-second gust. Wind bends all shots, including Echo and reflected shots |
| Bamboo | Authored solid walls on every map; cut a shortcut or take a clear route around them |

Bamboo clusters absorb three friendly or hostile shots, including the breaking
shot. One player/Echo slash cuts a cluster immediately. Pale notches show damage.
Walking and dashing stop at intact walls. Cutting opens movement and firing lanes
for both sides. Restart/checkpoint retry restores all bamboo.

Snow, mist and wind strength/direction are tuned per layout. Retry starts with
zero movement momentum and a calm wind cycle. Wind affects projectiles in the
shown world direction; it never pushes the player.

## Current development status

- All 18 layouts support five playable biomes, including authored bamboo walls.
- Ranged enemies and practice targets are playable. Four additional enemy art
  families are included for future behaviors.
- Biome rules, planned enemy counterplay and 180 future encounter drafts are described in
  [design/biomes.json](design/biomes.json), [design/enemies.json](design/enemies.json)
  and [design/encounters.json](design/encounters.json).
- Player profiling, behavioral scoring and saved progression are not implemented.

## Development

Tune gameplay in [shroud/settings.py](shroud/settings.py). Edit layouts in
`data/levels/`; positions use tile units, with 96 world pixels per tile. Floor
materials are `earth`, `stone`, `platform` and `mat`. Runtime biome selection
changes their appearance and gameplay rules. Static geometry stays fixed; bamboo
adds destructible walls with validated bypasses. Each JSON has `biome_settings`
for snow acceleration/braking, marsh radii and wind direction/strength, plus
`bamboo_walls` start/end segments. Shared defaults live in `BIOME_SETTINGS` in
settings.py; `shroud/biomes.py` merges and validates per-room values.
Reload with R or F2 after editing a layout.

```sh
python -m pytest -q
python -m shroud.level_validation
python main.py --headless --levels 5 --seed 42 --frames 120 --screenshot /tmp/shroud.png
python -m tools.export_map_gallery
```

The tests cover combat, Echo timing, input, run progression and route clearance
across all 90 layout–biome combinations. The gallery exporter writes map and
biome previews to the ignored `local/map_gallery/` directory.
