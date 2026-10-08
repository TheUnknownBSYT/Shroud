"""Gameplay values use pixels and seconds. Tune here, then restart."""
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parent / "ninjas"
WIDTH, HEIGHT = 1280, 800
FPS = 60
SIMULATION_STEP = 1 / 120
MAX_FRAME_TIME = 0.1  # Avoid catching up seconds of simulation after a stall.

PLAYER_SPEED = 300.0
ACCELERATION = 0.0  # Zero means immediate response; positive values are pixels/s².
FRICTION = 0.0      # Zero means immediate stop.
PLAYER_HEALTH = 5
PLAYER_RADIUS = 16.0
HIT_STUN = 0.16
HIT_INVULNERABILITY = 0.8
SPRITE_SIZE = 120

DASH_SPEED = 1000.0
DASH_DURATION = 0.15
DASH_COOLDOWN = 0.65
DASH_DAMAGE = 35

SLASH_DURATION = 0.30
SLASH_COOLDOWN = 0.34
SLASH_ACTIVE_START = 0.06
SLASH_ACTIVE_END = 0.22
SLASH_REACH = 68.0
SLASH_DAMAGE = 30
PARRY_WINDOW = 0.12
PARRY_REACH = 72.0
INPUT_BUFFER = 0.11

THROW_DURATION = 0.22
SHURIKEN_SPEED = 720.0
SHURIKEN_DAMAGE = 20
SHURIKEN_COOLDOWN = 0.28
SHURIKEN_RANGE = 220.0
MAX_SHURIKEN = 5

MOUSE_AIM_RESPONSE = 24.0  # Higher values track the cursor more tightly.
MOUSE_AIM_DEADZONE = 8.0
SHURIKEN_SPREAD = 3.0  # Degrees either side of aim for a quick mouse throw.
SHURIKEN_FOCUS_TIME = 0.45
SLASH_CHARGE_TIME = 0.75
SLASH_CHARGE_DAMAGE = 2.0
SLASH_CHARGE_REACH = 1.4

ENEMY_HEALTH = 90
ENEMY_RADIUS = 23.0
ENEMY_TELEGRAPH = 0.65
ENEMY_COOLDOWN = 2.4
ENEMY_RESPAWN = 2.8
ENEMY_PROJECTILE_SPEED = 800.0
REFLECTED_DAMAGE = 60

ECHO_DELAY = 0.35
ECHO_LIFETIME = 3.0  # Time to choose an attack; a queued attack is allowed to finish.
ECHO_ALPHA = 145
ECHO_FADE_DURATION = 0.18

BINDINGS = {
    "up": ("w", "up"), "down": ("s", "down"),
    "left": ("a", "left"), "right": ("d", "right"),
    "dash": ("space",), "slash": ("j",), "throw": ("k",),
    "debug": ("f1",), "reset": ("r",), "pause": ("p",),
    "quit": ("escape",),
}
MOUSE_BINDINGS = {1: "slash", 3: "throw"}
