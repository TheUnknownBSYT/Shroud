"""Input, the arena simulation, and the main loop."""
from dataclasses import dataclass
import pygame
from pygame import Vector2
import settings as S
from player import Player, Command, InputFrame, ShadowEcho, EchoState
from enemy import Enemy
from combat import Projectile, make_shuriken, resolve_melee, resolve_projectiles
from drawing import Renderer
from level import Camera, Room, TRAINING_GROUNDS

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


@dataclass
class Impact:
    position: Vector2
    kind: str
    remaining: float = 0.32


class Sandbox:
    def __init__(self, events: EventBus | None = None, room=None) -> None:
        self.events = events if events is not None else EventBus()
        self.room = room if room is not None else Room()
        self.time = 0.0
        self.reset()

    def reset(self) -> None:
        self.player = Player(self.room.spawn.copy())
        self.echo = None
        self.enemies = []
        if self.room.data:
            for i, (group, sprite, x, y, shoots) in enumerate(self.room.data["enemies"]):
                self.enemies.append(Enemy(
                    i + 1, Vector2(x, y) * S.TILE_SIZE, 1.2 + (i % 3) * .4,
                    shooting=shoots, respawn=False, group=group, sprite=sprite,
                    activation_range=S.ENEMY_ACTIVATION_RANGE,
                ))
        else:
            self.enemies = [Enemy(i + 1, position.copy(), 1.2 + i * .9)
                            for i, position in enumerate(self.room.enemy_spawns)]
        self.room.open_gates.clear()
        self.room.refresh_gates(self.enemies)
        self.elapsed = 0.0
        self.complete = False
        self.stats = {"targets": 0, "damage": 0, "deflections": 0, "echo_hits": 0}
        self.projectiles: list[Projectile] = []
        self.impacts: list[Impact] = []
        self.shake = 0.0
        self.events.emit("room_entered", timestamp=self.time, room="training", position=tuple(self.player.position))

    def impact(self, position: Vector2, kind: str) -> None:
        self.impacts.append(Impact(position.copy(), kind))
        strength = {"hit": 2, "hurt": 4, "parry": 6, "defeat": 5}.get(kind, 0)
        self.shake = max(self.shake, strength)

    def step(self, dt: float, inputs: InputFrame) -> None:
        if dt <= 0 or self.complete:
            return
        self.time += dt
        if self.player.alive:
            self.elapsed += dt
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
            can_attack = self.player.alive
            if self.room.data and can_attack:
                can_attack = not self.room.projectile_blocked(enemy.position, self.player.position, 0)
            projectile = enemy.tick(dt, self.player.position, can_attack)
            if projectile:
                self.projectiles.append(projectile)
        resolve_projectiles(self, dt)
        if not self.player.alive:
            self.echo = None
        elif (self.room.data and self.room.exit_rect.collidepoint(self.player.position)
              and len(self.room.open_gates) == len(self.room.gates)):
            self.complete = True
            self.player.cancel_hold()
            self.player.buffered = None
            self.echo = None
            self.projectiles.clear()

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
        pygame.display.set_caption("SHROUD | Training Grounds")
        self.screen = pygame.display.set_mode((S.WIDTH, S.HEIGHT))
        self.clock = pygame.time.Clock()
        self.world = Sandbox(room=Room(TRAINING_GROUNDS))
        self.camera = Camera(self.world.room.bounds)
        self.camera.follow(self.world.player.position, 0, snap=True)
        self.renderer = Renderer(self.world, self.camera)
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
                    self.camera.follow(self.world.player.position, 0, snap=True)
                    pending.clear()
                    accumulator = 0.0
                    self.paused = False
                elif not self.paused and not self.world.complete:
                    pending.append(command)
            if not self.paused and not self.world.complete:
                accumulator += dt
                while accumulator + 1e-9 >= S.SIMULATION_STEP:
                    aim = None
                    if inputs.aim_target is not None:
                        aim = self.camera.screen_to_world(inputs.aim_target)
                    self.world.step(S.SIMULATION_STEP, InputFrame(inputs.movement, pending, aim))
                    pending = []
                    accumulator -= S.SIMULATION_STEP
                self.camera.follow(self.world.player.position, dt)
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
