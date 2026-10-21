"""World-space integration and the handcrafted route, without a display."""
from collections import deque
from types import SimpleNamespace
import pygame
import pytest
from pygame import Vector2
import settings as S
from combat import Projectile, deal_damage, resolve_projectiles
from enemy import Enemy, EnemyState
from game import Game, Sandbox
from level import Camera, Prop, Room, TRAINING_GROUNDS
from player import Command, InputFrame


@pytest.mark.parametrize("position,expected", [
    ((0, 0), (0, 0)), ((9999, 0), (4864, 0)),
    ((0, 9999), (0, 3232)), ((9999, 9999), (4864, 3232)),
])
def test_camera_clamps_at_every_corner(position, expected):
    camera = Camera(Room(TRAINING_GROUNDS).bounds)
    camera.follow(Vector2(position), 0, snap=True)
    assert camera.offset == Vector2(expected)
    assert camera.visible_rect.left >= camera.bounds.left
    assert camera.visible_rect.bottom <= camera.bounds.bottom


def test_camera_round_trip_smoothing_and_small_world():
    offsets = []
    for dt in (1 / 30, 1 / 60, 1 / 120):
        camera = Camera((0, 0, 6000, 4000))
        for _ in range(round(.5 / dt)):
            camera.follow(Vector2(3200, 2200), dt)
        offsets.append(camera.offset)
        point = Vector2(3491.25, 2011.75)
        assert camera.screen_to_world(camera.world_to_screen(point)).distance_to(point) < 1e-8
        assert camera.world_to_screen(camera.offset) == Vector2(S.WORLD_VIEW[:2])
    assert all(offset.distance_to(offsets[0]) < 1e-8 for offset in offsets)
    assert 0 < offsets[0].x < 2560
    small = Camera((48, 140, 200, 200))
    small.follow(Vector2(-1000, 9000), 1)
    assert small.offset == Vector2(48, 140)


def test_world_movement_dash_and_projectiles_use_solid_shapes():
    room = Room(TRAINING_GROUNDS)
    start = Vector2(24, 32) * S.TILE_SIZE
    wall = next(p for p in room.props if p.asset == "crate" and p.position == Vector2(26, 32) * S.TILE_SIZE)
    end = room.move(start, Vector2(500, 0), S.PLAYER_RADIUS)
    assert start.x > S.WIDTH
    assert end.x == pytest.approx(wall.colliders()[0].left - S.PLAYER_RADIUS)
    assert room.projectile_blocked(start, start + Vector2(500, 0), 7)
    tree = Prop("tree", Vector2(4000, 1500))
    assert tree.colliders()[0].width < tree.rect.width / 4
    assert not tree.colliders()[0].collidepoint(tree.position)
    assert Prop("grass", Vector2()).colliders() == []
    gate = Prop("gate", Vector2(4000, 1000))
    assert not any(body.collidepoint(gate.position) for body in gate.colliders())
    assert all(not body.collidepoint(gate.position) for body in Prop("gate", gate.position, 90).colliders())


def route(room, start, end, excluded=None):
    """Breadth-first search at half-tile spacing, using swept player-size clearance."""
    spacing = S.TILE_SIZE / 2
    origin = tuple(round(value / spacing) for value in start)
    goal = tuple(round(value / spacing) for value in end)
    parents = {origin: None}
    queue = deque([origin])
    while queue:
        cell = queue.popleft()
        if cell == goal:
            result = []
            while cell is not None:
                result.append(Vector2(cell) * spacing)
                cell = parents[cell]
            return result[::-1]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            other = (cell[0] + dx, cell[1] + dy)
            point = Vector2(other) * spacing
            tile = (int(point.x // S.TILE_SIZE), int(point.y // S.TILE_SIZE))
            if other in parents or tile not in room.tiles or (excluded and excluded.collidepoint(point)):
                continue
            if not room.projectile_blocked(Vector2(cell) * spacing, point, S.PLAYER_RADIUS):
                parents[other] = cell
                queue.append(other)
    return None


def test_encounters_gate_progress_and_both_branches_reach_exit():
    world = Sandbox(room=Room(TRAINING_GROUNDS))
    room = world.room
    fork, reunion = Vector2(34, 20) * S.TILE_SIZE, Vector2(56, 22) * S.TILE_SIZE
    assert route(room, room.spawn, fork) is None
    for enemy in world.enemies:
        if enemy.group == "courtyard":
            deal_damage(world, enemy, 999, "slash")
    assert room.open_gates == {"courtyard"}
    entrance = route(room, room.spawn, fork)
    assert entrance
    assert route(room, fork, Vector2(room.exit_rect.center)) is None
    upper = pygame.FRect(36 * S.TILE_SIZE, 12 * S.TILE_SIZE, 14 * S.TILE_SIZE, 5 * S.TILE_SIZE)
    lower = pygame.FRect(36 * S.TILE_SIZE, 18 * S.TILE_SIZE, 14 * S.TILE_SIZE, 4 * S.TILE_SIZE)
    direct = route(room, fork, reunion, upper)
    garden = route(room, fork, reunion, lower)
    assert direct and garden and len(garden) > len(direct)
    for path in (entrance, direct, garden):
        for start, end in zip(path, path[1:]):
            assert room.move(start, end - start, S.PLAYER_RADIUS).distance_to(end) < .01
    for enemy in world.enemies:
        if enemy.group == "final":
            deal_damage(world, enemy, 999, "slash")
    assert route(room, reunion, Vector2(room.exit_rect.center))
    assert world.stats["targets"] == 10


@pytest.mark.parametrize("action", ["slash", "throw"])
def test_echo_attacks_and_mouse_aim_stay_in_world_space_after_scroll(action):
    world = Sandbox(room=Room(TRAINING_GROUNDS))
    world.enemies.clear()
    world.player.position = Vector2(2300, 3100)
    origin = world.player.position.copy()
    world.player.facing = Vector2(1, 0)
    camera = Camera(world.room.bounds)
    camera.follow(origin, 0, snap=True)
    world.step(S.SIMULATION_STEP, InputFrame(Vector2(0, -1), [Command("dash")]))
    for _ in range(24):
        world.step(S.SIMULATION_STEP, InputFrame())
    assert world.echo.position == origin
    camera.follow(world.player.position + Vector2(700, -400), 0, snap=True)
    enemy = Enemy(50, origin + Vector2(58, 0), 999, shooting=False, respawn=False)
    world.enemies.append(enemy)
    target = world.player.position + Vector2(400, 0)
    screen_cursor = camera.world_to_screen(target)
    for index in range(100):
        commands = [Command(action)] if index == 30 else []
        world.step(S.SIMULATION_STEP, InputFrame(Vector2(), commands, camera.screen_to_world(screen_cursor)))
    assert world.player.aim_direction.x > .99
    assert enemy.health < enemy.max_health
    assert world.stats["echo_hits"] == 1


def test_sentries_activate_locally_and_cover_blocks_telegraphs():
    world = Sandbox(room=Room(TRAINING_GROUNDS))
    enemy = next(e for e in world.enemies if e.group == "final")
    for _ in range(240):
        world.step(S.SIMULATION_STEP, InputFrame())
    assert enemy.state == EnemyState.IDLE and not world.projectiles
    # Crates at (26, 32) hide the player from a nearby sentry on the other side.
    enemy.position = Vector2(25, 32) * S.TILE_SIZE
    world.player.position = Vector2(28, 32) * S.TILE_SIZE
    world.enemies = [enemy]
    for _ in range(240):
        world.step(S.SIMULATION_STEP, InputFrame())
    assert enemy.state == EnemyState.IDLE and not world.projectiles
    world.player.position = enemy.position + Vector2(0, 160)
    for _ in range(130):
        world.step(S.SIMULATION_STEP, InputFrame())
    assert enemy.state == EnemyState.ATTACK


def test_stats_completion_freeze_and_restart():
    world = Sandbox(room=Room(TRAINING_GROUNDS))
    deal_damage(world, world.player, 1, "bolt")
    deal_damage(world, world.player, 1, "bolt")  # Invulnerability rejects this hit.
    assert world.stats["damage"] == 1
    world.player.tick(S.HIT_STUN + .01, Vector2())
    world.player.position = Vector2(2300, 3100)
    world.player.facing = Vector2(1, 0)
    world.player.queue(Command("slash"))
    world.player.tick(S.SIMULATION_STEP, Vector2())
    world.projectiles = [Projectile(world.player.position + Vector2(100, 0),
                                    Vector2(-800, 0), 1, "enemy", 1500, "bolt", 6)]
    resolve_projectiles(world, .05)
    assert world.stats["deflections"] == 1
    for enemy in world.enemies:
        if enemy.group in ("courtyard", "final"):
            deal_damage(world, enemy, 999, "slash", owner="echo")
    assert world.stats["targets"] == world.stats["echo_hits"] == 10
    world.player.position = Vector2(world.room.exit_rect.center)
    world.step(S.SIMULATION_STEP, InputFrame())
    assert world.complete and not world.projectiles and world.echo is None
    elapsed = world.elapsed
    world.step(10, InputFrame(Vector2(1, 0), [Command("dash")]))
    assert world.elapsed == elapsed
    world.reset()
    assert not world.complete and world.elapsed == 0
    assert world.player.position == world.room.spawn
    assert all(value == 0 for value in world.stats.values())
    assert not world.room.open_gates and all(e.alive for e in world.enemies)


def test_training_targets_stay_defeated_and_spawns_have_clearance():
    world = Sandbox(room=Room(TRAINING_GROUNDS))
    for entity in [world.player, *world.enemies]:
        body = pygame.FRect(0, 0, entity.radius * 2, entity.radius * 2)
        body.center = entity.position
        assert not any(body.colliderect(wall) for wall in world.room.walls)
    enemy = world.enemies[0]
    deal_damage(world, enemy, 999, "slash")
    enemy.tick(S.ENEMY_RESPAWN + 10, world.player.position, True)
    assert not enemy.alive


def test_game_loop_converts_mouse_and_restart_snaps_camera(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()
    try:
        game = Game()
        game.clock = SimpleNamespace(tick=lambda fps: 9, get_fps=lambda: 60)
        game.world.player.position = Vector2(2300, 3100)
        game.camera.follow(game.world.player.position, 0, snap=True)
        target = game.world.player.position + Vector2(150, -90)
        cursor = game.camera.world_to_screen(target)
        frame = InputFrame(aim_target=cursor)
        game.input = SimpleNamespace(read=lambda *args: frame)
        monkeypatch.setattr(pygame.event, "get", lambda: [])
        received = []
        step = game.world.step

        def capture(dt, inputs):
            received.append(inputs.aim_target.copy() if inputs.aim_target is not None else None)
            step(dt, inputs)

        monkeypatch.setattr(game.world, "step", capture)
        game.run(frame_limit=1)
        assert received == [target]
        game.world.complete = True
        frame = InputFrame(commands=[Command("reset")])
        game.run(frame_limit=1)
        assert not game.world.complete
        assert game.world.player.position == game.world.room.spawn
        assert game.camera.offset.x == 0
        assert game.camera.offset.y == pytest.approx(game.world.room.spawn.y - S.WORLD_VIEW[3] / 2)
    finally:
        pygame.quit()
