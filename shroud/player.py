"""Player input, action states, and the original ninja animations."""
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from pathlib import Path
import re
from math import exp
from shroud.rewards import RunRewards, action_timing
import random
import pygame
from pygame import Vector2
from shroud import settings as S
from shroud.combat import Entity, Attack, make_slash, make_shuriken, slash_active, parry_active
from shroud.biomes import BiomeRules


def direction_name(facing):
    if abs(facing.x) >= abs(facing.y):
        return "east" if facing.x >= 0 else "west"
    return "south" if facing.y >= 0 else "north"

@dataclass
class Command:
    action: str
    aim: Vector2 | None = None
    charge: float = 0.0
    spread: float = 0.0


@dataclass
class InputFrame:
    movement: Vector2 = field(default_factory=Vector2)
    commands: list[Command] = field(default_factory=list)
    aim_target: Vector2 | None = None
    sprint: bool = False


class PlayerState(Enum):
    IDLE = auto()
    MOVING = auto()
    DASHING = auto()
    ATTACKING = auto()
    THROWING = auto()
    STUNNED = auto()
    DEAD = auto()


class Player(Entity):
    def __init__(self, position: Vector2, motion=None, rewards=None) -> None:
        super().__init__(0, position, S.PLAYER_RADIUS, S.PLAYER_HEALTH)
        self.motion = motion if motion is not None else BiomeRules()
        self.rewards = rewards if rewards is not None else RunRewards()
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
        self.aim_direction = self.facing.copy()
        self.mouse_aiming = False
        self.sprint_requested = False
        self.held_action = None
        self.hold_time = 0.0
        self.action_charge = 0.0
        self.rng = random.Random()
        self.timing = self.rewards.effective().slash_timing
        self.cooldown_totals = dict(dash=S.DASH_COOLDOWN, slash=S.SLASH_COOLDOWN, throw=S.SHURIKEN_COOLDOWN)
        self.projectile = None
        self.flow_transition = None

    @property
    def hold_progress(self):
        duration = self.rewards.effective().charge_time if self.held_action == "slash" else S.SHURIKEN_FOCUS_TIME
        return min(1.0, self.hold_time / duration) if self.held_action else 0.0

    def cancel_hold(self):
        self.held_action, self.hold_time = None, 0.0

    def update_aim(self, dt, target):
        self.mouse_aiming = target is not None
        if target is None:
            self.aim_direction = self.facing.copy()
            return
        offset = target - self.position
        if offset.length_squared() <= S.MOUSE_AIM_DEADZONE ** 2:
            return
        angle = (self.aim_direction.angle_to(offset) + 180) % 360 - 180
        self.aim_direction.rotate_ip(angle * (1 - exp(-S.MOUSE_AIM_RESPONSE * dt)))
        self.aim_direction.normalize_ip()

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
        return self.state == PlayerState.ATTACKING and parry_active(self.state_time, self.timing.parry_window)

    @property
    def damage_active(self) -> bool:
        return self.state == PlayerState.DASHING or (
            self.state == PlayerState.ATTACKING and slash_active(self.state_time))

    def set_sprint(self, requested: bool) -> None:
        """Apply held intent before commands; canceled attacks never fire on release."""
        self.sprint_requested = requested
        if requested:
            self.cancel_hold()
            self.buffered = None
            self.buffer_time = 0.0

    @property
    def sprinting(self) -> bool:
        return self.sprint_requested and self.state in (PlayerState.IDLE, PlayerState.MOVING)

    def queue(self, command: Command) -> None:
        if self.sprint_requested:
            return
        if command.action.startswith("hold_"):
            action = command.action[5:]
            if (self.alive and self.state in (PlayerState.IDLE, PlayerState.MOVING)
                    and action in ("slash", "throw") and self.held_action is None):
                self.held_action, self.hold_time = action, 0.0
            return
        if command.action.startswith("release_"):
            action = command.action[8:]
            if self.held_action != action:
                return
            progress = self.hold_progress
            self.cancel_hold()
            command = Command(action, self.aim_direction.copy(),
                              progress if action == "slash" else 0.0,
                              S.SHURIKEN_SPREAD * (1 - progress) if action == "throw" else 0.0)
        if self.alive and command.action in self.cooldowns:
            self.buffered, self.buffer_time = command, S.INPUT_BUFFER

    def tick(self, dt: float, movement: Vector2) -> str | None:
        """Advance state and return a newly started action for the world to observe."""
        for name in self.cooldowns:
            self.cooldowns[name] = max(0.0, self.cooldowns[name] - dt)
        self.invulnerability = max(0.0, self.invulnerability - dt)
        self.flash = max(0.0, self.flash - dt)
        self.state_time += dt
        durations = {PlayerState.DASHING: S.DASH_DURATION, PlayerState.ATTACKING: self.timing.duration,
                     PlayerState.THROWING: self.timing.duration, PlayerState.STUNNED: S.HIT_STUN}
        if self.state in durations and self.state_time + 1e-8 >= durations[self.state]:
            if self.state == PlayerState.DASHING:
                # Ice must not carry dash speed into several seconds of sliding.
                self.velocity = self.velocity.clamp_magnitude(self.rewards.effective().move_speed)
            self.state, self.state_time, self.attack = PlayerState.IDLE, 0.0, None
        free = self.state in (PlayerState.IDLE, PlayerState.MOVING)
        if free:
            if self.held_action:
                self.hold_time += dt
            if self.mouse_aiming:
                self.facing = self.aim_direction.copy()
            elif movement.length_squared():
                self.facing = movement.normalize()
        started = None
        if free and self.buffered and self.cooldowns[self.buffered.action] <= 1e-8:
            command = self.buffered
            if command.aim is not None and command.aim.length_squared():
                self.facing = command.aim.normalize()
            elif command.action == "dash" and movement.length_squared():
                self.facing = movement.normalize()
            if command.spread:
                self.facing.rotate_ip(self.rng.uniform(-command.spread, command.spread))
            self.action_charge = command.charge
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
            target = direction * (S.SPRINT_SPEED if self.sprinting else self.rewards.effective().move_speed)
            rate = self.motion.acceleration if direction.length_squared() else self.motion.friction
            if rate > 0:
                self.velocity = self.velocity.move_towards(target, rate * dt)
            else:
                self.velocity = target
            if self.state in (PlayerState.IDLE, PlayerState.MOVING):
                self.state = PlayerState.MOVING if self.velocity.length_squared() else PlayerState.IDLE
        return started

    def _start_action(self, action: str) -> None:
        self.cancel_hold()
        self.state = {"dash": PlayerState.DASHING, "slash": PlayerState.ATTACKING,
                      "throw": PlayerState.THROWING}[action]
        self.state_time = 0.0
        self.action_serial += 1
        values = self.rewards.effective()
        self.action_modifiers = self.rewards.snapshot()
        self.timing = values.throw_timing if action == "throw" else values.slash_timing
        self.cooldowns[action] = values.dash_cooldown if action == "dash" else self.timing.cooldown
        self.cooldown_totals[action] = self.cooldowns[action]
        self.flow_transition = self.rewards.accept_attack(action)
        empowered = bool(self.flow_transition and self.flow_transition["earned"])
        multiplier = S.FLOW_DAMAGE_MULTIPLIER if empowered else 1.
        self.attack = None
        self.projectile = None
        if action == "slash":
            self.attack = make_slash(self.facing, self.action_charge, values, multiplier)
            self.attack.flow_bonus = empowered
        elif action == "throw":
            self.projectile = make_shuriken(self.position, self.facing, effective=values, damage_multiplier=multiplier)
            self.projectile.flow_bonus = empowered
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
        self.cancel_hold()
        self.velocity = Vector2()
        if not self.alive:
            self.rewards.reset()
        return True


class EchoState(Enum):
    WAITING = auto()
    ATTACK_QUEUED = auto()
    ATTACKING = auto()
    FADING = auto()
    EXPIRED = auto()


class ShadowEcho:
    """One stationary attack, captured when the player actually starts it."""
    def __init__(self, position, facing, lifetime=None):
        self.position = position.copy()
        self.facing = facing.copy()
        self.state = EchoState.WAITING
        self.timer = S.ECHO_LIFETIME if lifetime is None else lifetime
        self.state_time = 0.0
        self.action = None
        self.attack = None
        self.captured_attack = None
        self.projectile = None
        self.charge = 0.0
        self.timing = action_timing("slash", S.SLASH_COOLDOWN, S.PARRY_WINDOW, False)

    def queue(self, action, direction, charge=0.0, attack=None, projectile=None, timing=None):
        if self.state != EchoState.WAITING or action not in ("slash", "throw"):
            return
        self.action = action
        self.charge = charge
        self.captured_attack = (replace(attack, direction=attack.direction.copy(), hit_entities=set())
                                if attack is not None else None)
        self.timing = timing or action_timing(action, S.SLASH_COOLDOWN if action == "slash"
                                             else S.SHURIKEN_COOLDOWN, S.PARRY_WINDOW, False)
        # Store a copy: later movement or mouse input must not steer this attack.
        self.facing = direction.copy()
        if action == "throw":
            self.projectile = (replace(projectile, position=self.position + self.facing * 24,
                                       velocity=projectile.velocity.copy(), owner="echo", travelled=0., alive=True)
                               if projectile else make_shuriken(self.position, self.facing, owner="echo"))
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
            self.timer = self.timing.duration - overshoot
            if self.action == "slash":
                self.attack = self.captured_attack or make_slash(self.facing, self.charge)
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
        return self.attack is not None and parry_active(self.state_time, self.timing.parry_window)

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
