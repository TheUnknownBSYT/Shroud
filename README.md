# SHROUD

A Python / pygame-ce action game built from 18 handcrafted layouts. Each playthrough
samples **five distinct layouts**, and each level load independently rolls one of
four biomes: training grounds, snow, marsh or crosswind. Layouts, biomes and future
enemy rosters are separate choices. Biomes currently change floor/boundary artwork;
slippery movement, limited visibility, wind physics and four new enemy AIs are
planned in `design/`. The existing ranged enemies and practice targets are playable.

## Run

Requires Python 3.10+; run from this source checkout (maps/art are not bundled in a wheel).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

On Windows use `py -m venv .venv` and `.venv\Scripts\python`.

```sh
.venv/bin/python main.py --levels 5 --seed 42
.venv/bin/python main.py --level snow_01 --levels 3
.venv/bin/python main.py --list-levels
```

`--levels` accepts 1–18; the default is `RUN_LENGTH` in `shroud/settings.py`.
`--level` pins the first layout, with the remainder sampled without repeats.
`--seed` reproduces layout/biome choices for the same loading actions; combat
spread and visual effects have their own randomness. Biome draws may repeat.
Map IDs/names such as `snow_01` are stable layout labels, not biome restrictions.

## Controls and progression

| Input | Action |
| --- | --- |
| WASD / arrows | Move; mouse aim remains independent |
| Tap Space | Release within 0.18 s to dash and leave an Echo |
| Hold Space | Sprint after 0.18 s; release to stop; attacks disabled during sprint |
| LMB hold / release | Charge then slash; opening attack window can reflect bolts |
| RMB hold / release | Focus then throw; 0.45 s removes the initial ±3° spread |
| J / K | Immediate slash / shuriken |
| Enter | Next run level after completion; retry latest refuge after death |
| R | Reload the current run slot and roll its biome again |
| F2 | Start a new run with the selected layout first |
| Tab | Pause and show the whole map |
| P / F1 / Esc | Pause / debug overlay / quit (or close an overlay) |

Defeat the gold-marked seal groups and reach the exit. The HUD shows the run
position and current biome; completion stops after the configured number of
levels. Refuges restore health once and enable a checkpoint retry. Death retries
keep the same biome; a full R reload rolls again without adding a run slot.
F2 abandons the current run and starts a new one. Progress lives in memory only.

An accepted dash leaves one stationary Shadow Echo. Your next accepted attack
captures its direction/charge; after 0.35 s the Echo repeats once from that spot.
An unused Echo expires after 3 s. A new dash replaces it. Pause freezes timers;
death/reload removes it. Dashes deal damage without granting invulnerability.
Mouse attacks lock their direction on release; the artwork has four directions.
Shuriken travel 520 px with a forgiving 14 px radius. Sentries attack within
620 px and require clear line of sight. There is no player profiling or saved history.

## Project layout and editing

```text
main.py             Launcher and CLI
shroud/             Input, combat, player/enemy states, rendering and run loading
  settings.py       The single active tuning file
  campaign.py       Layout catalogue, fresh loading and random finite runs
  assets.py         Asset catalogue, visual palettes and four biome mappings
  level.py          World geometry, collision and camera
assets/             Character, environment and effect PNGs; measured catalog.json
  characters/new_enemies/  Four preserved enemy art families for later AI work
data/levels/        18 layouts, independent of runtime biome
design/            Future biome rules, enemy counters and 144 encounter drafts
tests/             Gameplay/run/geometry regressions; one deliberate world fixture
tools/             Optional map-gallery exporter
local/             Ignored private notes, previews, references and Git checkout
```

Edit tile-unit geometry in `data/levels/<id>.json`; floor materials are `earth`,
`stone`, `platform`, `mat`. The loader adds the selected biome at runtime.
`layout_style` preserves authored obstacle/boundary collision geometry; it does
not choose the biome. Cover props retain their authored appearance. Floor and
boundary skins vary, while routes, gate groups and collision stay consistent.
Asset collision shapes use source pixels, scaled by 0.75; tiles are 96 world px.
Reload with R/F2 to reread an edited map. The 120 Hz simulation is separate from
60 FPS rendering. All runtime paths resolve relative to source, not the shell cwd.

`design/biomes.json`, `enemies.json` and `encounters.json` describe the planned
18 × 4 = 72 map/biome cells and two rosters per cell (144 drafts). New attacks and
biome mechanics require implementation/playtesting before those drafts are enabled.
Risk appetite, adaptability and fortitude remain future design hypotheses.

## Checks and local development material

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m shroud.level_validation
.venv/bin/python main.py --headless --levels 5 --seed 42 --frames 120 --screenshot /tmp/shroud.png
.venv/bin/python -m tools.export_map_gallery
```

The exporter writes previews into ignored `local/map_gallery/`. Detailed learning
notes and the next-commit summary also live under `local/`; the game and public
tests do not require that folder. `AGENTS.md` is an ignored discovery link to the
local instructions. Virtual environments and Python caches are also ignored.
