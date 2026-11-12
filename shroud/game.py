"""Input, the arena simulation, and the main loop."""
from dataclasses import dataclass, asdict
import random
import pygame
from pygame import Vector2
from shroud import settings as S
from shroud.player import Player, PlayerState, Command, InputFrame, ShadowEcho, EchoState
from shroud.enemy import Enemy, EnemyState
from shroud.combat import Projectile, resolve_melee, resolve_projectiles
from shroud.drawing import Renderer
from shroud.rewards import RunRewards, Choice, load_caches, nearby_cache
from shroud.history import RunHistory
from shroud.level import Camera, Room
from shroud.campaign import LEVEL_IDS, BIOME_IDS, SELECTOR_ROWS, load_level, Run

class EventBus:
    """Synchronous callbacks; RunHistory optionally retains detached event snapshots."""
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
        self.mouse_buttons = set()
        self.space_pressed_at = None

    def cancel_space(self) -> None:
        """Require a fresh press after focus loss, overlays, or reset."""
        self.space_pressed_at = None

    def read(self, events: list[pygame.event.Event], player_position: Vector2) -> InputFrame:
        result = InputFrame()
        now = pygame.time.get_ticks()
        for event in events:
            if event.type == pygame.KEYDOWN and not getattr(event, "repeat", False):
                for action, codes in self.keys.items():
                    if event.key in codes:
                        if action == "dash":
                            if self.space_pressed_at is None:
                                self.space_pressed_at = now
                        else:
                            result.commands.append(Command(action))
                            if action in ("pause", "reset", "map", "select_level", "confirm", "quit"):
                                self.cancel_space()
            elif event.type == pygame.KEYUP and event.key in self.keys["dash"]:
                if (self.space_pressed_at is not None
                        and now - self.space_pressed_at < S.SPRINT_HOLD_TIME * 1000):
                    result.commands.append(Command("dash"))
                self.cancel_space()
            elif event.type == pygame.MOUSEMOTION:
                if pygame.FRect(S.WORLD_VIEW).collidepoint(event.pos):
                    self.cursor = Vector2(event.pos)
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and event.button in S.MOUSE_BINDINGS:
                inside = pygame.FRect(S.WORLD_VIEW).collidepoint(event.pos)
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if not inside:
                        continue
                    self.mouse_buttons.add(event.button)
                else:
                    self.mouse_buttons.discard(event.button)
                if inside:
                    self.cursor = Vector2(event.pos)
                prefix = "hold_" if event.type == pygame.MOUSEBUTTONDOWN else "release_"
                result.commands.append(Command(prefix + S.MOUSE_BINDINGS[event.button]))
            elif event.type == pygame.WINDOWFOCUSLOST:
                self.cursor = None
                self.mouse_buttons.clear()
                self.cancel_space()
        result.aim_target = self.cursor.copy() if self.cursor is not None else None
        keys = pygame.key.get_pressed()
        def held(action):
            return any(keys[key] for key in self.keys[action])
        result.sprint = (self.space_pressed_at is not None
                         and now - self.space_pressed_at >= S.SPRINT_HOLD_TIME * 1000)
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
    def __init__(self, events: EventBus | None = None, room=None, rewards=None, history=None, progress=(1, 1)) -> None:
        self.events = events if events is not None else EventBus()
        self.room = room if room is not None else Room()
        self.time = 0.0
        self.rewards = rewards if rewards is not None else RunRewards()
        self.history = history if history is not None else RunHistory()
        self.run_position, self.run_length = progress
        self.history.attach(self)
        self.reset(clear_rewards=False)

    def reset(self, clear_rewards=True) -> None:
        if clear_rewards:
            self.rewards.reset()
            self.history.clear()
        self.caches = load_caches(self.room.data)
        self.checkpoint = None
        for screen in self.room.bamboo:
            screen.broken = False
            screen.shots_taken = 0
        self.player = Player(self.room.spawn.copy(), self.room.rules, self.rewards)
        self.biome_elapsed = 0.0
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

    def retry_checkpoint(self):
        """Rebuild combat, then restore only the authored cleared stage and refuge spawn."""
        checkpoint = self.checkpoint
        self.reset()
        if checkpoint is not None:
            self.checkpoint = checkpoint
            self.player.position = Vector2(checkpoint["spawn"]) * S.TILE_SIZE
            for enemy in self.enemies:
                if enemy.group in checkpoint["requires"]:
                    enemy.health = 0
                    enemy.state = EnemyState.DEAD
            self.room.refresh_gates(self.enemies)

    def update_checkpoint(self):
        if not self.room.data or not self.player.alive:
            return
        checkpoints = self.room.data.get("checkpoints", [])
        current = checkpoints.index(self.checkpoint) if self.checkpoint in checkpoints else -1
        for index, checkpoint in enumerate(checkpoints):
            if (index > current and set(checkpoint["requires"]) <= self.room.open_gates
                    and self.player.position.distance_to(Vector2(checkpoint["spawn"]) * S.TILE_SIZE) < 65):
                self.checkpoint = checkpoint
                self.player.health = self.player.max_health

    def impact(self, position: Vector2, kind: str) -> None:
        self.impacts.append(Impact(position.copy(), kind))
        strength = {"hit": 2, "hurt": 4, "parry": 6, "defeat": 5}.get(kind, 0)
        self.shake = max(self.shake, strength)

    def step(self, dt: float, inputs: InputFrame) -> None:
        if dt <= 0 or self.complete:
            return
        self.time += dt
        if self.history.status == "playing":
            self.history.elapsed += dt
        self.biome_elapsed += dt
        if self.player.alive:
            self.elapsed += dt
        for effect in self.impacts:
            effect.remaining -= dt
        self.impacts = [effect for effect in self.impacts if effect.remaining > 0]
        self.shake = max(0, self.shake - dt * 28)
        self.update_echo(dt)
        self.player.update_aim(dt, inputs.aim_target)
        self.player.set_sprint(inputs.sprint)
        player_shuriken = sum(
            p.kind == "shuriken" and p.owner == "player" for p in self.projectiles
        )
        for command in inputs.commands:
            if command.action == "burst" and self.player.alive:
                self.rewards.activate(self.events)
                continue
            if command.action == "throw" and player_shuriken >= S.MAX_SHURIKEN:
                continue
            self.player.queue(command)
        if (player_shuriken >= S.MAX_SHURIKEN and self.player.buffered is not None
                and self.player.buffered.action == "throw"):
            self.player.buffered = None
        action = self.player.tick(dt, inputs.movement)
        if action:
            captured = self.player.projectile if action == "throw" else self.player.attack
            captured.action_id = self.history.next_action()
            name = {"slash": "player_slash", "dash": "player_dash", "throw": "player_throw_shuriken"}[action]
            self.events.emit(name, timestamp=self.time, position=tuple(self.player.position),
                             direction=tuple(self.player.facing), action_id=captured.action_id,
                             owner="player", damage=captured.damage, flow_bonus=captured.flow_bonus,
                             reach=captured.max_range if action == "throw" else captured.reach,
                             timing=asdict(self.player.timing) if action != "dash" else dict(duration=S.DASH_DURATION),
                             modifiers=self.player.action_modifiers)
            if self.player.flow_transition:
                self.events.emit("flow_transition", action_id=captured.action_id, **self.player.flow_transition)
        if action == "throw":
            self.projectiles.append(self.player.projectile)
        if action == "dash":
            # Capture before movement, and replace even an already queued Echo.
            self.echo = ShadowEcho(self.player.position, self.player.facing, self.rewards.effective().echo_lifetime)
        elif action in ("slash", "throw") and self.echo is not None:
            self.echo.queue(action, self.player.facing, self.player.action_charge, self.player.attack,
                            self.player.projectile, self.player.timing)
        before = self.player.position.copy()
        displacement = self.player.velocity * dt
        self.player.position = self.room.move(before, displacement, self.player.radius)
        for axis in (0, 1):
            if abs(self.player.position[axis] - before[axis] - displacement[axis]) > .001:
                self.player.velocity[axis] = 0  # No stored ice momentum pushing into a wall.
        resolve_melee(self, self.player)
        if self.echo is not None:
            resolve_melee(self, self.echo)
        for enemy in self.enemies:
            can_attack = self.player.alive and self.rewards.active != "smoke_veil" and self.room.rules.visible_enemy(self.player.position, enemy.position)
            if self.room.data and can_attack:
                can_attack = not self.room.projectile_blocked(enemy.position, self.player.position, 0)
            projectile = enemy.tick(dt, self.player.position, can_attack)
            if projectile:
                self.projectiles.append(projectile)
        resolve_projectiles(self, dt)
        self.update_checkpoint()
        was_haste = self.rewards.active == "haste"
        self.rewards.tick(dt, self.events)
        if was_haste and self.rewards.active != "haste" and self.player.state != PlayerState.DASHING:
            limit = S.SPRINT_SPEED if self.player.sprinting else self.rewards.effective().move_speed
            self.player.velocity = self.player.velocity.clamp_magnitude(limit)
        if not self.player.alive:
            self.history.finish(self, "death")
            self.echo = None
            self.rewards.reset()
        elif (self.room.data and self.room.exit_rect.collidepoint(self.player.position)
              and self.room.gates_cleared):
            self.complete = True
            self.player.cancel_hold()
            self.player.buffered = None
            self.echo = None
            self.projectiles.clear()
            if getattr(self, "run_position", 1) == getattr(self, "run_length", 1):
                self.history.finish(self, "completed")
                self.rewards.reset()

    def update_echo(self, dt):
        if self.echo is None:
            return
        action = self.echo.tick(dt)
        if action:
            self.impact(self.echo.position, "echo")
            captured = self.echo.projectile if action == "throw" else self.echo.attack
            self.events.emit("echo_attack", action=action, action_id=captured.action_id,
                             owner="echo", damage=captured.damage, flow_bonus=captured.flow_bonus,
                             timing=asdict(self.echo.timing))
        if action == "throw":
            self.projectiles.append(self.echo.projectile)
        if self.echo.state == EchoState.EXPIRED:
            self.echo = None


class Game:
    def __init__(self, level_id=None, run_length=S.RUN_LENGTH, seed=None, biome=None) -> None:
        pygame.display.set_caption("SHROUD | Handcrafted Journeys")
        self.screen = pygame.display.set_mode((S.WIDTH, S.HEIGHT))
        self.clock = pygame.time.Clock()
        self.run_rng = random.Random(seed)
        self.rewards = RunRewards(random.Random(seed))
        self.history = RunHistory()
        self.choice = None
        self.reward_notice = ""
        self.reward_notice_time = 0.0
        self.run_length = run_length
        self.biome_override = biome
        self.run_state = Run(run_length, first=level_id, rng=self.run_rng, biome=biome)
        self.input = InputHandler()
        self.debug = False
        self._load_current()

    def _load_current(self):
        """Build a random biome for this run slot before replacing the current scene."""
        world = Sandbox(room=Room(self.run_state.load_current()), rewards=self.rewards,
                        history=self.history, progress=(self.run_state.index + 1, len(self.run_state.level_ids)))
        world.run_position = self.run_state.index + 1
        world.run_length = len(self.run_state.level_ids)
        following = self.run_state.following
        world.next_layout = load_level(following)["name"] if following else None
        camera = Camera(world.room.bounds)
        camera.follow(world.player.position, 0, snap=True)
        renderer = Renderer(world, camera)
        self.world, self.camera, self.renderer = world, camera, renderer
        self.choice = None
        self.reward_notice = ""
        self.reward_notice_time = 0.0
        self.selection = LEVEL_IDS.index(self.run_state.current)
        for name in ("reward_confirmed", "burst_activated", "burst_expired"):
            world.events.subscribe(name, lambda payload, name=name: self.reward_notification(name, payload))
        self.selector_biome = self.biome_override
        self.selecting = self.paused = self.map_open = False

    def load(self, level_id, *, biome_override=...):
        """Start a run; omitted biome preserves choice, explicit None selects Random."""
        chosen = self.biome_override if biome_override is ... else biome_override
        new_run = Run(self.run_length, first=level_id, rng=self.run_rng, biome=chosen)
        previous, previous_biome = self.run_state, self.biome_override
        previous_rewards = self.rewards
        previous_history = self.history
        self.history = RunHistory()
        self.rewards = RunRewards(self.rewards.rng)
        self.run_state, self.biome_override = new_run, chosen
        try:
            self._load_current()
        except Exception:
            self.run_state, self.biome_override = previous, previous_biome
            self.rewards = previous_rewards
            self.history = previous_history
            raise

    def advance(self):
        if not self.world.complete or self.run_state.following is None:
            return False
        self.run_state.index += 1
        try:
            self._load_current()
        except Exception:
            self.run_state.index -= 1
            raise
        return True

    def cancel_combat_input(self):
        self.world.player.cancel_hold()
        self.world.player.buffered = None
        self.world.player.set_sprint(False)
        self.input.cancel_space()
        if hasattr(self.input, "mouse_buttons"):
            self.input.mouse_buttons.clear()

    def reward_notification(self, name, payload):
        from shroud.rewards import REWARDS, RANKS
        reward = REWARDS[payload["reward"]]
        if name == "reward_confirmed":
            suffix = f" {RANKS[payload['rank']]} acquired" if reward.category == "technique" else " stored / Q to activate"
        else:
            suffix = " activated / 10 seconds" if name == "burst_activated" else " expired"
        self.reward_notice = reward.name + suffix
        self.reward_notice_time = 3.0

    def open_cache(self):
        self.reward_notice_time = 3.0
        cache = nearby_cache(self.world)
        if cache is None:
            self.reward_notice = "No available cache nearby."
            return
        if cache.offer(self.world.rewards, self.world.events) is None:
            self.reward_notice = "Not enough eligible techniques for two choices. Cache kept."
            return
        self.choice = Choice(cache)
        self.reward_notice = ""
        self.cancel_combat_input()

    def reward_input(self, events):
        """Consume a whole event batch at the modal boundary, before gameplay reads it."""
        if any(event.type == pygame.WINDOWFOCUSLOST for event in events):
            return False  # Main loop handles focus before any command is accepted.
        if getattr(self, "choice", None) is None:
            if (not self.paused and not self.selecting and not self.map_open
                    and self.world.player.alive and not self.world.complete
                    and any(event.type == pygame.KEYDOWN
                            and event.key in tuple(pygame.key.key_code(key) for key in S.BINDINGS["interact"])
                            and not getattr(event, "repeat", False) for event in events)):
                self.open_cache()
                self.cancel_combat_input()
                return True
            return False
        from shroud.reward_ui import card_rects, CONFIRM_RECT, CANCEL_RECT
        for event in events:
            if event.type == pygame.KEYDOWN and not getattr(event, "repeat", False):
                if event.key == pygame.K_ESCAPE:
                    if self.choice.cancel():
                        self.choice = None
                    break
                if event.key in (pygame.K_1, pygame.K_2):
                    self.choice.select(event.key - pygame.K_1)
                elif event.key == pygame.K_RETURN:
                    if self.choice.confirm(self.world.rewards, self.world.events):
                        self.choice = None
                    break
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if CANCEL_RECT.collidepoint(event.pos):
                    if self.choice.cancel():
                        self.choice = None
                    break
                if CONFIRM_RECT.collidepoint(event.pos):
                    if self.choice.confirm(self.world.rewards, self.world.events):
                        self.choice = None
                    break
                for index, rect in enumerate(card_rects()):
                    if rect.collidepoint(event.pos):
                        self.choice.select(index)
        self.cancel_combat_input()
        return True

    def run(self, frame_limit: int | None = None, screenshot: str | None = None) -> None:
        running, accumulator, frames = True, 0.0, 0
        pending = []
        while running:
            dt = min(self.clock.tick(S.FPS) / 1000, S.MAX_FRAME_TIME)
            events = pygame.event.get()
            focus_lost = any(event.type == pygame.WINDOWFOCUSLOST for event in events)
            if focus_lost:
                self.paused = True
                self.cancel_combat_input()
                self.input.cursor = None
            blocked_frame = focus_lost or self.reward_input(events)
            if any(event.type == pygame.QUIT for event in events):
                running = False
            inputs = InputFrame() if blocked_frame else self.input.read(events, self.world.player.position)
            if blocked_frame:
                pending.clear()
                accumulator = 0
            for command in inputs.commands:
                if command.action == "map" and not self.selecting:
                    self.map_open = not self.map_open
                    blocked_frame = True
                    break
                if self.map_open:
                    if command.action == "quit":
                        self.map_open = False
                        blocked_frame = True
                        break
                    continue
                if command.action == "select_level":
                    self.selecting = not self.selecting
                    if self.selecting:
                        self.selector_biome = self.biome_override
                    blocked_frame = True
                    break
                if self.selecting:
                    if command.action == "quit":
                        self.selecting = False
                        blocked_frame = True
                        break
                    elif command.action in ("up", "down", "left", "right"):
                        change = {"up": -1, "down": 1, "left": -SELECTOR_ROWS, "right": SELECTOR_ROWS}[command.action]
                        self.selection = (self.selection + change) % len(LEVEL_IDS)
                    elif command.action == "select_biome":
                        choices = (None, *BIOME_IDS)
                        self.selector_biome = choices[(choices.index(self.selector_biome) + 1) % len(choices)]
                    elif command.action == "confirm":
                        self.load(LEVEL_IDS[self.selection], biome_override=self.selector_biome)
                        pending.clear()
                        accumulator = 0
                        inputs.movement = Vector2()
                        blocked_frame = True
                        break
                    continue
                if command.action == "quit":
                    running = False
                elif command.action == "debug":
                    self.debug = not self.debug
                elif command.action == "pause":
                    self.paused = not self.paused
                    blocked_frame = True
                    break
                elif command.action == "reset":
                    self.rewards.reset()
                    self.history.clear()
                    self._load_current()
                    pending.clear()
                    accumulator = 0.0
                    self.paused = False
                    inputs.movement = Vector2()
                    blocked_frame = True
                    break
                elif command.action == "confirm":
                    if not self.world.player.alive:
                        self.world.retry_checkpoint()
                        self.renderer.reset()
                        self.camera.follow(self.world.player.position, 0, snap=True)
                        self.paused = False
                    else:
                        self.advance()
                    pending.clear()
                    accumulator = 0
                    inputs.movement = Vector2()
                    blocked_frame = True
                    break
                elif not self.paused and not self.world.complete:
                    pending.append(command)
            if (not blocked_frame and getattr(self, "choice", None) is None
                    and not self.paused and not self.selecting and not self.map_open and not self.world.complete):
                accumulator += dt
                while accumulator + 1e-9 >= S.SIMULATION_STEP:
                    aim = None
                    if inputs.aim_target is not None:
                        aim = self.camera.screen_to_world(inputs.aim_target)
                    self.world.step(S.SIMULATION_STEP, InputFrame(inputs.movement, pending, aim, inputs.sprint))
                    pending = []
                    accumulator -= S.SIMULATION_STEP
                self.camera.follow(self.world.player.position, dt)
                self.renderer.update(self.world, dt)
            else:
                self.cancel_combat_input()
                pending.clear()
                accumulator = 0
            # Presentation clock only: opening art can animate while the choice pauses play.
            for cache in self.world.caches:
                cache.opening = max(0.0, cache.opening - dt)
            if getattr(self, "reward_notice_time", 0) > 0:
                self.reward_notice_time = max(0.0, self.reward_notice_time - dt)
                if self.reward_notice_time == 0:
                    self.reward_notice = ""
            self.renderer.draw(self.screen, self.world, self.debug, self.clock.get_fps(), self.paused)
            if self.selecting:
                self.renderer.draw_selector(self.screen, self.selection, self.selector_biome)
            elif self.map_open:
                self.renderer.draw_map(self.screen, self.world)
            if hasattr(self.renderer, "reward_ui"):
                modal = self.paused or self.selecting or self.map_open or self.world.complete or getattr(self, "choice", None) is not None
                self.renderer.reward_ui.status(self.screen, self.world, modal, getattr(self, "reward_notice", ""))
                if getattr(self, "choice", None) is not None:
                    self.renderer.reward_ui.overlay(self.screen, self.world, self.choice)
                elif self.paused and not self.selecting and not self.map_open:
                    self.renderer.reward_ui.details(self.screen, self.world)
            pygame.display.flip()
            frames += 1
            if frame_limit is not None and frames >= frame_limit:
                running = False
        if screenshot:
            pygame.image.save(self.screen, screenshot)
