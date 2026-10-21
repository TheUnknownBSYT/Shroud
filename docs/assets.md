# Existing asset inspection

The initial checkout contained `ninjas/organize_sprites.py`, a pre-existing
`ninjas/.venv`, and 95 PNGs. There was no existing gameplay code.

All PNG canvases are 320×320 RGBA. They are individual frames, not sprite
sheets, under `ninjas/{direction}/{action}/`.

| Direction | Idle | Run | Dash | Slash | Throw |
| --- | ---: | ---: | ---: | ---: | ---: |
| East | 4 | 6 | 4 | 5 | 5 |
| West | 4 | 5 | 4 | 5 | 5 |
| North | 4 | 6 | 4 | 5 | 5 |
| South | 4 | 5 | 4 | 5 | 5 |

The remaining image is `ninjas/ninja_shuriken.png`.

Naming is `ninja_{direction}_{action}_{frame:02}.png`; the south run's first
frame has a ` (1)` suffix. The loader sorts by numeric frame index and handles
that suffix without renaming it. Every direction has original art, so no
horizontal flip or synthesized directional animation is needed.

Visual inspection of all 94 animation frames confirms a consistent shared
canvas for the body, sword motion, and floor shadow. The loader preserves that
canvas at 120×120; independently cropping each action would shift the body and
cause visible jitter. The idle east body occupies approximately x=84–244,
y=92–254 including its shadow. Sword frames can reach the image edge.

The PNG exports contain a faint four-pixel top/left border (alpha 26).
The loader clears only faint pixels within those four edge rows/columns before
scaling, leaving opaque sword pixels and the intentional shadow intact. This
prevents visible box outlines on the arena floor. The shuriken is then cropped
to its remaining alpha bounds and scaled to 23×23. All preprocessing happens
in memory; original images are untouched.

## Training Grounds inspection and usage

All 35 actual exports in `TrainingGrounds/` were inspected before integration.
They are individual RGBA PNGs. Floor earth/stone, mat and platform canvases are
opaque; all other exports have transparent pixels. Original files are unchanged.
The table lists original dimensions; runtime scales both axes by 0.75. A
128×128 floor becomes 96×96; a 64-pixel authoring-grid step becomes 48 pixels.
This fits the ninja's unchanged 120×120 canvas and roughly 60-pixel visible body.

| Actual filename | Source pixels | Used | Purpose |
| --- | --- | --- | --- |
| `env_training_banner_01.png` | 128×128 | Yes | Entrance/yard landmarks; decorative |
| `env_training_crate_01.png` | 128×128 | Yes | Solid cover |
| `env_training_dojo_wall_01.png` | 128×64 | No | Alternate wall; reserved |
| `env_training_fence_01.png` | 128×64 | Yes | Encounter barriers |
| `env_training_fence_corner_01.png` | 128×128 | No | Alternate corner; reserved |
| `env_training_floor_earth_01.png` | 128×128 | Yes | Tiled earth floor |
| `env_training_floor_earth_02.png` | 128×128 | Yes | Tiled earth floor |
| `env_training_floor_stone_01.png` | 128×128 | Yes | Tiled stone floor |
| `env_training_floor_stone_02.png` | 128×128 | Yes | Tiled stone floor |
| `env_training_gate_01.png` | 256×128 | Yes | Entrance, passages, exit; two solid posts |
| `env_training_grass_01.png` | 128×128 | Yes | Ground decoration |
| `env_training_hanging_target_01.png` | 128×128 | No | Alternate target; reserved |
| `env_training_lantern_01.png` | 64×64 | Yes | Route/exit landmark; decorative |
| `env_training_leaf_scatter_01.png` | 128×128 | Yes | Ground detail |
| `env_training_low_wall_01.png` | 128×64 | Yes | Solid cover |
| `env_training_mat_01.png` | 128×128 | Yes | Practice floor |
| `env_training_pillar_01.png` | 64×64 | Yes | Solid cover |
| `env_training_platform_01.png` | 128×128 | Yes | Wooden floor/walkway |
| `env_training_platform_edge_01.png` | 128×64 | No | Alternate wooden edge; reserved |
| `env_training_post_01.png` | 64×64 | Yes | Small solid obstacle |
| `env_training_practice_mark_01.png` | 128×128 | Yes | Ground target markings |
| `env_training_rock_01.png` | 128×128 | Yes | Solid rock base |
| `env_training_rock_02.png` | 128×128 | Yes | Solid rock base |
| `env_training_rope_01.png` | 128×128 | Yes | Ground detail |
| `env_training_sentry_01.png` | 128×128 | Yes | Shooting enemy art |
| `env_training_shrub_01.png` | 128×128 | Yes | Nonblocking ground foliage |
| `env_training_stationary_target_01.png` | 128×128 | Yes | Optional passive target |
| `env_training_straw_dummy_01.png` | 128×128 | Yes | Passive courtyard target |
| `env_training_sword_dummy_01.png` | 128×128 | Yes | Passive final target |
| `env_training_target_01.png` | 128×128 | Yes | Passive practice target |
| `env_training_tree_01.png` | 128×128 | Yes | Solid trunk; fading canopy |
| `env_training_wall_01.png` | 128×64 | Yes | Automatic solid perimeter |
| `env_training_wall_corner_01.png` | 128×128 | No | Alternate corner; reserved |
| `env_training_wall_end_01.png` | 64×64 | No | Alternate end cap; reserved |
| `env_training_weapon_rack_01.png` | 128×128 | Yes | Solid rack base / yard detail |

29 PNG types are used. Floors alternate the two earth/stone variants deterministically;
no random layout or art generation is involved. Source canvases stay intact,
including transparent padding. Tile positions use a single rounded camera
origin to prevent subpixel gaps between adjacent tiles. Unwalkable ground uses
a darkened copy of the earth export beyond the solid perimeter.

Colliders are local source-pixel rectangles in `level.SOLID_SHAPES`, scaled and
rotated around each prop center with its image. Tree collision is only an
18×28 source-pixel trunk (13.5×21 runtime), not its 128×128 canopy canvas.
Crates, rocks, pillars, walls, posts and racks use their solid base areas. A
gate has two post rectangles and a walkable center. Closed encounter fences
have explicit map rectangles, removed together when their enemy group clears.
Decorations have no collision even if their image overlaps a path.

Ground and markings draw first. Props and characters sort by base/foot Y, then
projectiles and impacts draw above them. A tree overlapping the player's center
is faded to alpha 105 so its canopy cannot completely conceal the player. HUD
and completion/pause text draw in fixed screen coordinates. Dead training
targets use the same PNG rotated and faded; no additional enemy animation kit
or new combat class was introduced.
