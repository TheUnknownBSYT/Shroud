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
