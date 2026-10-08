"""Input, the arena simulation, and the main loop."""
from dataclasses import dataclass
from math import ceil
import pygame
from pygame import Vector2
import settings as S
from player import Player, Command, InputFrame, ShadowEcho, EchoState
from enemy import Enemy
from combat import Projectile, make_shuriken, resolve_melee, resolve_projectiles
from drawing import Renderer

class EventBus:
    """Optional game-event callbacks. Nothing is recorded or saved."""
    def __init__(self):
        self.listeners = {}

    def subscribe(self, name, handler):
        self.listeners.setdefault(name, []).append(handler)

    def emit(self, name, **payload):
        for handler in tuple(self.listeners.get(name, [])):
            handler(payload)


class InputHandler:
    def __init__(self) -> None:
        self.keys = {action: tuple(pygame.key.key_code(key) for key in names)
                     for action, names in S.BINDINGS.items()}
        self.cursor = None

    def read(self, events: list[pygame.event.Event], player_position: Vector2) -> InputFrame:
        result = InputFrame()
        for event in events:
            if event.type == pygame.KEYDOWN and not getattr(event, "repeat", False):
                for action, codes in self.keys.items():
                    if event.key in codes:
                        result.commands.append(Command(action))
            elif event.type == pygame.MOUSEMOTION:
                self.cursor = Vector2(event.pos)
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and event.button in S.MOUSE_BINDINGS:
                self.cursor = Vector2(event.pos)
                prefix = "hold_" if event.type == pygame.MOUSEBUTTONDOWN else "release_"
                result.commands.append(Command(prefix + S.MOUSE_BINDINGS[event.button]))
        result.aim_target = self.cursor.copy() if self.cursor is not None else None
        keys = pygame.key.get_pressed()
        def held(action):
            return any(keys[key] for key in self.keys[action])
        result.movement = Vector2(held("right") - held("left"), held("down") - held("up"))
        if result.movement.length_squared() > 1:
            result.movement.normalize_ip()
        return result


class Room:
    def __init__(self) -> None:
        self.bounds = pygame.FRect(48, 140, S.WIDTH - 96, S.HEIGHT - 218)
        self.walls = [pygame.FRect(440, 295, 58, 112), pygame.FRect(744, 465, 58, 112)]
        self.spawn = Vector2(250, 435)
        self.enemy_spawns = [Vector2(880, 300), Vector2(1030, 505), Vector2(550, 605)]

    def move(self, position: Vector2, displacement: Vector2, radius: float) -> Vector2:
        # Subdivision prevents fast dashes tunnelling through thin walls.
        steps = max(1, ceil(displacement.length() / max(radius * 0.5, 1)))
        step = displacement / steps
        result = position.copy()
        for _ in range(steps):
            for axis in (0, 1):
                result[axis] += step[axis]
                body = pygame.FRect(result.x - radius, result.y - radius, radius * 2, radius * 2)
                for wall in self.walls:
                    if body.colliderect(wall):
                        if step[axis] > 0:
                            result[axis] = (wall.left if axis == 0 else wall.top) - radius
                        elif step[axis] < 0:
                            result[axis] = (wall.right if axis == 0 else wall.bottom) + radius
                        body.center = result
                result.x = max(self.bounds.left + radius, min(self.bounds.right - radius, result.x))
                result.y = max(self.bounds.top + radius, min(self.bounds.bottom - radius, result.y))
        return result

    def projectile_blocked(self, start: Vector2, end: Vector2, radius: float) -> bool:
        if not self.bounds.inflate(-radius * 2, -radius * 2).collidepoint(end):
            return True
        return any(wall.inflate(radius * 2, radius * 2).clipline(start, end) for wall in self.walls)


@dataclass
class Impact:
    position: Vector2
    kind: str
    remaining: float = 0.32


class Sandbox:
    def __init__(self, events: EventBus | None = None) -> None:
        self.events = events if events is not None else EventBus()
        self.room = Room()
        self.time = 0.0
        self.reset()

    def reset(self) -> None:
        self.player = Player(self.room.spawn.copy())
        self.echo = None
        self.enemies = [Enemy(i + 1, position.copy(), 1.2 + i * 0.9)
                        for i, position in enumerate(self.room.enemy_spawns)]
        self.projectiles: list[Projectile] = []
        self.impacts: list[Impact] = []
        self.shake = 0.0
        self.events.emit("room_entered", timestamp=self.time, room="training", position=tuple(self.player.position))

    def impact(self, position: Vector2, kind: str) -> None:
        self.impacts.append(Impact(position.copy(), kind))
        strength = {"hit": 2, "hurt": 4, "parry": 6, "defeat": 5}.get(kind, 0)
        self.shake = max(self.shake, strength)

    def step(self, dt: float, inputs: InputFrame) -> None:
        if dt <= 0:
            return
        self.time += dt
        for effect in self.impacts:
            effect.remaining -= dt
        self.impacts = [effect for effect in self.impacts if effect.remaining > 0]
        self.shake = max(0, self.shake - dt * 28)
        self.update_echo(dt)
        self.player.update_aim(dt, inputs.aim_target)
        player_shuriken = sum(
            p.kind == "shuriken" and p.owner == "player" for p in self.projectiles
        )
        for command in inputs.commands:
            if command.action == "throw" and player_shuriken >= S.MAX_SHURIKEN:
                continue
            self.player.queue(command)
        if (player_shuriken >= S.MAX_SHURIKEN and self.player.buffered is not None
                and self.player.buffered.action == "throw"):
            self.player.buffered = None
        action = self.player.tick(dt, inputs.movement)
        if action:
            name = {"slash": "player_slash", "dash": "player_dash", "throw": "player_throw_shuriken"}[action]
            self.events.emit(name, timestamp=self.time, position=tuple(self.player.position), direction=tuple(self.player.facing))
        if action == "throw":
            self.projectiles.append(make_shuriken(self.player.position, self.player.facing))
        if action == "dash":
            # Capture before movement, and replace even an already queued Echo.
            self.echo = ShadowEcho(self.player.position, self.player.facing)
        elif action in ("slash", "throw") and self.echo is not None:
            self.echo.queue(action, self.player.facing, self.player.action_charge)
        self.player.position = self.room.move(self.player.position, self.player.velocity * dt, self.player.radius)
        resolve_melee(self, self.player)
        if self.echo is not None:
            resolve_melee(self, self.echo)
        for enemy in self.enemies:
            projectile = enemy.tick(dt, self.player.position, self.player.alive)
            if projectile:
                self.projectiles.append(projectile)
        resolve_projectiles(self, dt)
        if not self.player.alive:
            self.echo = None

    def update_echo(self, dt):
        if self.echo is None:
            return
        action = self.echo.tick(dt)
        if action:
            self.impact(self.echo.position, "echo")
        if action == "throw":
            self.projectiles.append(make_shuriken(self.echo.position, self.echo.facing, owner="echo"))
        if self.echo.state == EchoState.EXPIRED:
            self.echo = None


class Game:
    def __init__(self) -> None:
        pygame.display.set_caption("SHROUD | The Courtyard")
        self.screen = pygame.display.set_mode((S.WIDTH, S.HEIGHT))
        self.clock = pygame.time.Clock()
        self.world = Sandbox()
        self.renderer = Renderer(self.world)
        self.input = InputHandler()
        self.debug = False
        self.paused = False

    def run(self, frame_limit: int | None = None, screenshot: str | None = None) -> None:
        running, accumulator, frames = True, 0.0, 0
        pending = []
        while running:
            dt = min(self.clock.tick(S.FPS) / 1000, S.MAX_FRAME_TIME)
            events = pygame.event.get()
            inputs = self.input.read(events, self.world.player.position)
            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.WINDOWFOCUSLOST:
                    self.paused = True
                    self.world.player.cancel_hold()
                    self.world.player.buffered = None
                    inputs.commands.clear()
            for command in inputs.commands:
                if command.action == "quit":
                    running = False
                elif command.action == "debug":
                    self.debug = not self.debug
                elif command.action == "pause":
                    self.paused = not self.paused
                    self.world.player.cancel_hold()
                    self.world.player.buffered = None
                    pending.clear()
                elif command.action == "reset":
                    self.world.reset()
                    self.renderer.reset()
                    pending.clear()
                    accumulator = 0.0
                    self.paused = False
                elif not self.paused:
                    pending.append(command)
            if not self.paused:
                accumulator += dt
                while accumulator + 1e-9 >= S.SIMULATION_STEP:
                    self.world.step(S.SIMULATION_STEP, InputFrame(inputs.movement, pending, inputs.aim_target))
                    pending = []
                    accumulator -= S.SIMULATION_STEP
                self.renderer.update(self.world, dt)
            else:
                pending.clear()
                accumulator = 0
            self.renderer.draw(self.screen, self.world, self.debug, self.clock.get_fps(), self.paused)
            pygame.display.flip()
            frames += 1
            if frame_limit is not None and frames >= frame_limit:
                running = False
        if screenshot:
            pygame.image.save(self.screen, screenshot)
