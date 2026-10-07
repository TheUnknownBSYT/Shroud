"""Player input, action states, and the original ninja animations."""
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
import re
import pygame
from pygame import Vector2
import settings as S
from combat import Entity, Attack, make_slash, slash_active, parry_active


def direction_name(facing):
    if abs(facing.x) >= abs(facing.y):
        return "east" if facing.x >= 0 else "west"
    return "south" if facing.y >= 0 else "north"

@dataclass
class Command:
    action: str
    aim: Vector2 | None = None


@dataclass
class InputFrame:
    movement: Vector2 = field(default_factory=Vector2)
    commands: list[Command] = field(default_factory=list)


class PlayerState(Enum):
    IDLE = auto()
    MOVING = auto()
    DASHING = auto()
    ATTACKING = auto()
    THROWING = auto()
    STUNNED = auto()
    DEAD = auto()


class Player(Entity):
    def __init__(self, position: Vector2) -> None:
        super().__init__(0, position, S.PLAYER_RADIUS, S.PLAYER_HEALTH)
        self.state = PlayerState.IDLE
        self.velocity = Vector2()
        self.facing = Vector2(1, 0)
        self.state_time = 0.0
        self.invulnerability = 0.0
        self.cooldowns = {"dash": 0.0, "slash": 0.0, "throw": 0.0}
        self.attack: Attack | None = None
        self.buffered: Command | None = None
        self.buffer_time = 0.0
        self.action_serial = 0

    @property
    def direction_name(self) -> str:
        return direction_name(self.facing)

    @property
    def animation_name(self) -> str:
        action = {PlayerState.DASHING: "dash", PlayerState.ATTACKING: "slash",
                  PlayerState.THROWING: "throw", PlayerState.MOVING: "run"}.get(self.state, "idle")
        return f"{self.direction_name}/{action}"

    @property
    def parry_active(self) -> bool:
        return self.state == PlayerState.ATTACKING and parry_active(self.state_time)

    @property
    def damage_active(self) -> bool:
        return self.state == PlayerState.DASHING or (
            self.state == PlayerState.ATTACKING and slash_active(self.state_time))

    def queue(self, command: Command) -> None:
        if self.alive and command.action in self.cooldowns:
            self.buffered, self.buffer_time = command, S.INPUT_BUFFER

    def tick(self, dt: float, movement: Vector2) -> str | None:
        """Advance state and return a newly started action for the world to observe."""
        for name in self.cooldowns:
            self.cooldowns[name] = max(0.0, self.cooldowns[name] - dt)
        self.invulnerability = max(0.0, self.invulnerability - dt)
        self.flash = max(0.0, self.flash - dt)
        self.state_time += dt
        durations = {PlayerState.DASHING: S.DASH_DURATION, PlayerState.ATTACKING: S.SLASH_DURATION,
                     PlayerState.THROWING: S.THROW_DURATION, PlayerState.STUNNED: S.HIT_STUN}
        if self.state in durations and self.state_time + 1e-8 >= durations[self.state]:
            self.state, self.state_time, self.attack = PlayerState.IDLE, 0.0, None
        free = self.state in (PlayerState.IDLE, PlayerState.MOVING)
        if free and movement.length_squared():
            self.facing = movement.normalize()
        started = None
        if free and self.buffered and self.cooldowns[self.buffered.action] <= 1e-8:
            command = self.buffered
            if command.aim is not None and command.aim.length_squared():
                self.facing = command.aim.normalize()
            self._start_action(command.action)
            started = command.action
            self.buffered = None
        self.buffer_time -= dt
        if self.buffer_time <= 0:
            self.buffered = None
        direction = movement.normalize() if movement.length_squared() > 1 else movement
        if self.state == PlayerState.DASHING:
            self.velocity = self.facing * S.DASH_SPEED
        elif self.state in (PlayerState.DEAD, PlayerState.STUNNED):
            self.velocity = Vector2()
        else:
            target = direction * S.PLAYER_SPEED
            rate = S.ACCELERATION if direction.length_squared() else S.FRICTION
            if rate > 0:
                self.velocity = self.velocity.move_towards(target, rate * dt)
            else:
                self.velocity = target
            if self.state in (PlayerState.IDLE, PlayerState.MOVING):
                self.state = PlayerState.MOVING if self.velocity.length_squared() else PlayerState.IDLE
        return started

    def _start_action(self, action: str) -> None:
        self.state = {"dash": PlayerState.DASHING, "slash": PlayerState.ATTACKING,
                      "throw": PlayerState.THROWING}[action]
        self.state_time = 0.0
        self.action_serial += 1
        self.cooldowns[action] = {"dash": S.DASH_COOLDOWN, "slash": S.SLASH_COOLDOWN,
                                  "throw": S.SHURIKEN_COOLDOWN}[action]
        self.attack = None
        if action == "slash":
            self.attack = make_slash(self.facing)
        elif action == "dash":
            self.attack = Attack("dash", S.DASH_DAMAGE, self.facing.copy())

    def receive_damage(self, amount: int) -> bool:
        # The dash is an offensive tool, not an invulnerability ability.
        if self.invulnerability > 0 or not super().receive_damage(amount):
            return False
        self.invulnerability = S.HIT_INVULNERABILITY
        self.state = PlayerState.STUNNED if self.alive else PlayerState.DEAD
        self.state_time = 0.0
        self.attack, self.buffered = None, None
        self.velocity = Vector2()
        return True


class EchoState(Enum):
    WAITING = auto()
    ATTACK_QUEUED = auto()
    ATTACKING = auto()
    FADING = auto()
    EXPIRED = auto()


class ShadowEcho:
    """One stationary attack, captured when the player actually starts it."""
    def __init__(self, position, facing):
        self.position = position.copy()
        self.facing = facing.copy()
        self.state = EchoState.WAITING
        self.timer = S.ECHO_LIFETIME
        self.state_time = 0.0
        self.action = None
        self.attack = None

    def queue(self, action, direction):
        if self.state != EchoState.WAITING or action not in ("slash", "throw"):
            return
        self.action = action
        # Store a copy: later movement or mouse input must not steer this attack.
        self.facing = direction.copy()
        self.state = EchoState.ATTACK_QUEUED
        self.timer = S.ECHO_DELAY
        self.state_time = 0.0

    def tick(self, dt):
        self.state_time += dt
        remaining = self.timer - dt
        self.timer = max(0.0, remaining)
        if self.timer > 1e-8:
            return None
        # Carry leftover step time across states so the delay and fade do not drift.
        overshoot = max(0.0, -remaining)
        if self.state == EchoState.ATTACK_QUEUED:
            self.state = EchoState.ATTACKING
            self.state_time = overshoot
            duration = S.SLASH_DURATION if self.action == "slash" else S.THROW_DURATION
            self.timer = duration - overshoot
            if self.action == "slash":
                self.attack = make_slash(self.facing)
            return self.action
        if self.state in (EchoState.WAITING, EchoState.ATTACKING):
            self.state = EchoState.FADING
            self.timer = S.ECHO_FADE_DURATION - overshoot
            self.attack = None
        elif self.state == EchoState.FADING:
            self.state = EchoState.EXPIRED
        return None

    @property
    def damage_active(self):
        return self.attack is not None and slash_active(self.state_time)

    @property
    def parry_active(self):
        return self.attack is not None and parry_active(self.state_time)

    @property
    def animation_name(self):
        action = "idle"
        if self.action and self.state in (EchoState.ATTACKING, EchoState.FADING):
            action = self.action
        return f"{direction_name(self.facing)}/{action}"

    @property
    def alpha(self):
        if self.state == EchoState.FADING:
            return int(S.ECHO_ALPHA * self.timer / S.ECHO_FADE_DURATION)
        return S.ECHO_ALPHA


@dataclass(frozen=True)
class Animation:
    frame_count: int
    frame_duration: float
    looping: bool = True

    def __post_init__(self) -> None:
        if self.frame_count < 1 or self.frame_duration <= 0:
            raise ValueError("Animation needs frames and a positive frame duration")


class AnimationController:
    def __init__(self, animations: dict[str, Animation]) -> None:
        self.animations = animations
        self.name = next(iter(animations))
        self.elapsed = 0.0

    def play(self, name: str, *, restart: bool = False) -> None:
        if name not in self.animations:
            raise KeyError(f"Unknown animation: {name}")
        if name != self.name or restart:
            self.name, self.elapsed = name, 0.0

    def update(self, dt: float) -> None:
        self.elapsed += max(0.0, dt)

    @property
    def frame_index(self) -> int:
        animation = self.animations[self.name]
        index = int((self.elapsed + 1e-9) / animation.frame_duration)
        return index % animation.frame_count if animation.looping else min(index, animation.frame_count - 1)

    @property
    def finished(self) -> bool:
        animation = self.animations[self.name]
        return not animation.looping and self.elapsed >= animation.frame_count * animation.frame_duration - 1e-9


class SpriteLibrary:
    """Keep full frame canvases: per-frame cropping would cause animation jitter."""
    def __init__(self, root: Path = S.ASSET_ROOT) -> None:
        self.frames: dict[str, list[pygame.Surface]] = {}
        self.animations: dict[str, Animation] = {}
        for direction in ("north", "south", "east", "west"):
            for action in ("idle", "run", "dash", "slash", "throw"):
                paths = sorted((root / direction / action).glob("*.png"), key=self._frame_number)
                if not paths:
                    raise FileNotFoundError(f"Missing {direction}/{action} sprites in {root}")
                key = f"{direction}/{action}"
                self.frames[key] = []
                for path in paths:
                    image = self._load_clean(path)
                    frame = pygame.transform.smoothscale(image, (S.SPRITE_SIZE, S.SPRITE_SIZE))
                    self.frames[key].append(frame)
                duration = {"idle": 0.52, "run": 0.40, "dash": S.DASH_DURATION,
                            "slash": S.SLASH_DURATION, "throw": S.THROW_DURATION}[action]
                self.animations[key] = Animation(len(paths), duration / len(paths), action in ("idle", "run"))
        star = self._load_clean(root / "ninja_shuriken.png")
        self.shuriken = pygame.transform.smoothscale(star.subsurface(star.get_bounding_rect()), (23, 23))

    @staticmethod
    def _load_clean(path: Path) -> pygame.Surface:
        surface = pygame.image.load(path).convert_alpha()
        # The supplied exports have a four-pixel, alpha-26 top/left canvas outline.
        # Remove only those edge pixels, retaining artwork and the soft floor shadow.
        width, height = surface.get_size()
        for y in range(height):
            columns = range(width) if y < 4 else range(min(4, width))
            for x in columns:
                if surface.get_at((x, y)).a <= 26:
                    surface.set_at((x, y), (0, 0, 0, 0))
        return surface

    @staticmethod
    def _frame_number(path: Path) -> int:
        match = re.search(r"_(\d+)(?: \(\d+\))?\.png$", path.name)
        if match is None:
            raise ValueError(f"Unrecognized sprite filename: {path}")
        return int(match.group(1))
