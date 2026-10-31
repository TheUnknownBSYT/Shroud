"""Authored-map acceptance: actual clearance, staged gates, reset, UI, and every export."""
from collections import Counter
from types import SimpleNamespace
import pygame
import pytest
from pygame import Vector2
from shroud import settings as S
from shroud.assets import CATALOG, asset_path
from shroud.campaign import LEVEL_IDS, load_level
from shroud.combat import deal_damage
from shroud.drawing import Renderer
from shroud.enemy import EnemyState
from shroud.game import Game, Sandbox
from shroud.level import Room
from shroud.level_validation import reachable, path_to, validate_level
from shroud.player import Command, InputFrame, ShadowEcho, EchoState


@pytest.fixture
def display(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((S.WIDTH, S.HEIGHT))
    yield
    pygame.quit()


def test_catalogue_and_fixed_order():
    assert len(LEVEL_IDS) == len(set(LEVEL_IDS)) == 18
    counts = Counter(level_id.split('_')[0] for level_id in LEVEL_IDS)
    assert counts == dict(training=1, temple=3, rooftop=3, misty=3, autumn=3, snow=3, final=2)
    geometry = [repr(load_level(level_id)["floors"]) for level_id in LEVEL_IDS]
    assert len(set(geometry)) == 18
    with pytest.raises(ValueError, match="Unknown level"):
        load_level("../main")
    first = load_level(LEVEL_IDS[0])
    first["spawn"][0] = -100
    assert load_level(LEVEL_IDS[0])["spawn"][0] > 0


@pytest.mark.parametrize("level_id", LEVEL_IDS)
def test_every_authored_route_and_stage_has_clearance(level_id):
    assert validate_level(load_level(level_id)) == []


@pytest.mark.parametrize("level_id", LEVEL_IDS)
def test_completion_reset_and_gate_collision(level_id):
    world = Sandbox(room=Room(load_level(level_id)))
    room = world.room
    world.player.position = Vector2(room.exit_rect.center)
    world.step(S.SIMULATION_STEP, InputFrame())
    assert not world.complete
    for group in dict.fromkeys(name for name, _ in room.gates):
        members = [e for e in world.enemies if e.group == group]
        assert members
        for enemy in members[:-1]:
            deal_damage(world, enemy, 999, "slash")
        assert group not in room.open_gates
        deal_damage(world, members[-1], 999, "slash")
        assert group in room.open_gates
        assert all(rect not in room.walls for name, rect in room.gates if name == group)
    # Walk the proven route using the actual movement resolver, not a teleport.
    path = path_to(reachable(room, room.spawn), Vector2(room.exit_rect.center))
    position = room.spawn.copy()
    for point in path[1:]:
        position = room.move(position, point - position, S.PLAYER_RADIUS)
        assert position.distance_to(point) < .01
    world.player.position = position
    world.step(S.SIMULATION_STEP, InputFrame())
    assert world.complete and not world.projectiles and world.echo is None
    # Completion must freeze; reset restores the complete authored encounter.
    before = world.time
    world.step(1, InputFrame(commands=[Command("dash")]))
    assert world.time == before
    world.reset()
    assert not world.complete and world.player.position == room.spawn
    assert world.checkpoint is None and world.player.health == S.PLAYER_HEALTH
    assert all(enemy.alive for enemy in world.enemies)
    assert not room.open_gates and not world.projectiles and not world.impacts


@pytest.mark.parametrize("level_id", [i for i in LEVEL_IDS if load_level(i).get("checkpoints")])
def test_refuges_require_their_stage_and_retry_without_softlock(level_id):
    data = load_level(level_id)
    for checkpoint in data["checkpoints"]:
        world = Sandbox(room=Room(data))
        world.player.position = Vector2(checkpoint["spawn"]) * S.TILE_SIZE
        world.update_checkpoint()
        assert world.checkpoint is None
        for enemy in world.enemies:
            if enemy.group in checkpoint["requires"]:
                deal_damage(world, enemy, 999, "slash")
        world.player.health = 1
        world.update_checkpoint()
        assert world.checkpoint == checkpoint and world.player.health == S.PLAYER_HEALTH
        world.player.health = 2
        world.update_checkpoint()
        assert world.player.health == 2  # Not an infinite healing station.
        world.player.health = 0
        world.echo = ShadowEcho(world.player.position, Vector2(1, 0))
        world.retry_checkpoint()
        assert world.player.alive and world.player.position == Vector2(checkpoint["spawn"]) * S.TILE_SIZE
        assert world.echo is None and not world.projectiles
        assert set(checkpoint["requires"]) <= world.room.open_gates
        assert all(not e.alive for e in world.enemies if e.group in checkpoint["requires"])
        assert all(e.alive for e in world.enemies if e.group not in checkpoint["requires"])


def test_export_dimensions_alpha_and_solid_bounds(display):
    for name, spec in CATALOG.items():
        image = pygame.image.load(asset_path(name)).convert_alpha()
        assert list(image.get_size()) == spec["size"]
        pixels = image.get_width() * image.get_height()
        visible = pygame.mask.from_surface(image, 0).count()
        opaque = pygame.mask.from_surface(image, 254).count()
        assert pixels - visible == spec["transparent_pixels"]
        assert visible - opaque == spec["partial_alpha_pixels"]
        assert visible > 0
        for rect in spec["solids"]:
            assert image.get_rect().contains(pygame.Rect(rect))


@pytest.mark.parametrize("level_id", LEVEL_IDS)
def test_every_level_renders_and_transitions(display, level_id):
    game = Game(level_id, seed=7)
    world = game.world
    game.renderer.update(world, 0)
    game.renderer.draw(game.screen, world, True, 60, False)
    game.renderer.draw_map(game.screen, world)
    game.renderer.draw_selector(game.screen, LEVEL_IDS.index(level_id))
    for name in set(world.room.tiles.values()):
        assert game.renderer._asset(name).get_size() == (S.TILE_SIZE, S.TILE_SIZE)
    assert not game.advance()
    world.complete = True
    following = game.run_state.following
    result = game.advance()
    assert result == (following is not None)
    if following:
        assert game.world.room.data["id"] == following
        assert game.world.player.position == game.world.room.spawn
        assert not game.world.complete and not game.world.projectiles
        assert game.camera.bounds == game.world.room.bounds
    else:
        assert game.world is world and world.complete


def test_state_art_effects_and_cached_alpha_do_not_leak(display):
    game = Game("temple_01")
    world = game.world
    renderer = game.renderer
    for state in EnemyState:
        enemy = world.enemies[0]
        enemy.state = state
        enemy.health = 0 if state == EnemyState.DEAD else enemy.max_health
        for timer in (0, .1, .5, 2.4):
            enemy.timer = timer
            renderer._enemy(enemy)
    for state in (EchoState.WAITING, EchoState.ATTACK_QUEUED, EchoState.ATTACKING, EchoState.FADING):
        for action in ("slash", "throw"):
            echo = ShadowEcho(world.player.position, Vector2(-1, 0))
            echo.state, echo.action, echo.timer = state, action, .1
            renderer._echo(echo)
    for name in ("fx_slash", "fx_dash", "fx_movement_dust", "fx_deflect", "fx_defeat", "fx_hit", "fx_impact_dust"):
        for progress in (0, .5, 1):
            renderer._effect(name, progress, world.player.position, Vector2(1, 0))
    assert all(image.get_alpha() == 255 for image in renderer.environment.values())


def test_echo_body_has_four_distinct_directions(display, monkeypatch):
    game = Game("training_01")
    bodies = []
    scene = game.renderer.scene
    class CaptureScene:
        def blit(self, source, *args, **kwargs):
            bodies.append(source.copy())
            return scene.blit(source, *args, **kwargs)
    monkeypatch.setattr(game.renderer, "scene", CaptureScene())
    images = []
    for direction in ((1, 0), (-1, 0), (0, -1), (0, 1)):
        bodies.clear()
        echo = ShadowEcho(game.world.player.position, Vector2(direction))
        echo.state_time = .5  # Past spawn effect, before any action.
        game.renderer._echo(echo)
        images.append(pygame.image.tobytes(bodies[0], "RGBA"))
    assert len(set(images)) == 4


def test_selector_map_pause_and_direct_loading(display, monkeypatch):
    game = Game("training_01", seed=7)
    game.clock = SimpleNamespace(tick=lambda fps: 9, get_fps=lambda: 60)
    monkeypatch.setattr(pygame.event, "get", lambda: [])
    def command(action):
        game.input = SimpleNamespace(read=lambda *args: InputFrame(commands=[Command(action)]),
                                         cancel_space=lambda: None)
        game.run(frame_limit=1)
    before = game.world.time
    game.world.player.queue(Command("hold_slash"))
    command("select_level")
    assert game.selecting and game.world.time == before and game.world.player.held_action is None
    command("right")
    command("confirm")
    assert game.world.room.data["id"] == LEVEL_IDS[9]
    assert not game.selecting
    before = game.world.time
    command("map")
    assert game.map_open and game.world.time == before
    command("quit")
    assert not game.map_open
    game.world.player.health = 0
    command("confirm")
    assert game.world.player.alive
