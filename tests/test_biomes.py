"""Playable biome rules: momentum, fair mist, wind, overrides and reset isolation."""
import math

import pygame
import pytest
from pygame import Vector2

from shroud import settings as S
from shroud.biomes import BiomeRules
from shroud.campaign import LEVEL_IDS, load_level
from shroud.combat import Projectile, resolve_projectiles
from shroud.enemy import Enemy, EnemyState
from shroud.game import Game, Sandbox
from shroud.level import Room
from shroud.player import Command, InputFrame, Player, PlayerState


def arena(biome):
    room = Room()
    room.biome = biome
    room.rules = BiomeRules.from_level({'biome': biome})
    room.bounds = pygame.FRect(0, 0, 3000, 2000)
    room.static_walls = []
    room.refresh_gates([])
    world = Sandbox(room=room)
    world.enemies = []
    world.player.position.update(1500, 1000)
    return world


@pytest.mark.parametrize('level_id', LEVEL_IDS)
def test_authored_settings_apply_only_to_selected_biome(level_id):
    snow = Room(load_level(level_id, 'snow')).rules
    marsh = Room(load_level(level_id, 'marsh')).rules
    wind = Room(load_level(level_id, 'wind')).rules
    ground = Room(load_level(level_id, 'grounds')).rules
    assert snow.acceleration > 0 and snow.friction > 0 and snow.fade_radius == 0
    assert marsh.clear_radius < marsh.fade_radius and marsh.acceleration == 0
    assert 300 <= wind.wind_force(6.5).length() <= 450 and wind.fade_radius == 0
    assert wind.wind_phase(11.9)[0] == 'gust' and wind.wind_phase(12)[0] == 'calm'
    assert ground.acceleration == ground.friction == ground.fade_radius == ground.wind_acceleration == 0
    # Constructing one variant must never change another room's settings.
    assert Room(load_level(level_id, 'bamboo')).rules == ground


@pytest.mark.parametrize('settings', [
    {'unknown': {}}, {'snow': {'speed': 900}}, {'snow': {'friction': -1}},
    {'snow': {'acceleration': math.nan}}, {'marsh': {'clear_radius': 500}},
    {'wind': {'wind_direction': [0, 0]}}, {'wind': {'period_seconds': 2}},
])
def test_bad_overrides_fail_even_when_inactive(settings):
    with pytest.raises(ValueError):
        BiomeRules.from_level({'biome': 'grounds', 'biome_settings': settings})


def test_snow_accelerates_brakes_reverses_and_retains_keyboard_facing():
    player = Player(Vector2(), BiomeRules.from_level({'biome': 'snow'}))
    player.tick(.1, Vector2(1, 0))
    assert player.velocity.x == pytest.approx(96)
    player.tick(.1, Vector2())
    assert player.velocity.x == pytest.approx(28.5)
    player.tick(.1, Vector2(-1, 0))
    assert player.velocity.x == pytest.approx(-67.5) and player.direction_name == 'west'
    player.tick(.1, Vector2())
    assert player.velocity == Vector2()


def test_snow_sprint_brakes_with_finite_distance_and_dash_exit_is_capped():
    world = arena('snow')
    player = world.player
    for _ in range(120):
        world.step(S.SIMULATION_STEP, InputFrame(Vector2(1, 0), sprint=True))
    assert player.velocity.length() == pytest.approx(S.SPRINT_SPEED)
    start = player.position.copy()
    for _ in range(120):world.step(S.SIMULATION_STEP, InputFrame())
    assert player.velocity == Vector2()
    assert 165 < player.position.distance_to(start) < 175  # v²/(2*675) = 170.7 px.
    world.step(S.SIMULATION_STEP, InputFrame(commands=[Command('dash', Vector2(1, 0))]))
    while player.state == PlayerState.DASHING:
        world.step(S.SIMULATION_STEP, InputFrame())
    assert player.velocity.length() <= S.PLAYER_SPEED


def test_snow_collision_removes_only_blocked_momentum_and_retry_resets_it():
    world = arena('snow')
    world.room.static_walls = [pygame.FRect(1550, 600, 30, 800)]
    world.room.refresh_gates([])
    for _ in range(120):world.step(S.SIMULATION_STEP, InputFrame(Vector2(1, 1)))
    assert world.player.position.x == pytest.approx(1550 - S.PLAYER_RADIUS)
    assert world.player.velocity.x == 0 and world.player.velocity.y > 0
    world.retry_checkpoint()
    assert world.player.velocity == Vector2() and world.biome_elapsed == 0
    assert world.player.motion.friction == 675


def test_marsh_cancels_hidden_attack_and_revealed_enemy_telegraphs_before_firing():
    world = arena('marsh')
    enemy = Enemy(1, world.player.position + Vector2(500, 0), 0, activation_range=620)
    world.enemies = [enemy]
    for _ in range(240):world.step(S.SIMULATION_STEP, InputFrame())
    assert enemy.state == EnemyState.IDLE and not world.projectiles
    enemy.position = world.player.position + Vector2(300, 0)
    for _ in range(121):world.step(S.SIMULATION_STEP, InputFrame())
    assert enemy.state == EnemyState.ATTACK and not world.projectiles
    enemy.position = world.player.position + Vector2(500, 0)
    world.step(S.SIMULATION_STEP, InputFrame())
    assert enemy.state == EnemyState.IDLE and not world.projectiles


@pytest.mark.parametrize('elapsed,phase', [(0, 'calm'), (2.999, 'calm'), (3, 'warning'),
                                           (3.999, 'warning'), (4, 'gust'), (11.999, 'gust'), (12, 'calm')])
def test_wind_warns_before_gust_and_repeats(elapsed, phase):
    rules = BiomeRules.from_level({'biome': 'wind'})
    assert rules.wind_phase(elapsed)[0] == phase
    assert bool(rules.wind_force(elapsed).length_squared()) == (phase == 'gust')


@pytest.mark.parametrize('team,owner,kind', [('player', 'player', 'shuriken'), ('player', 'echo', 'shuriken'),
                                           ('enemy', 'enemy', 'bolt'), ('player', 'player', 'reflected')])
def test_gust_bends_every_shot_and_swept_collision_still_stops_it(team, owner, kind):
    world = arena('wind')
    world.biome_elapsed = 6.5
    shot = Projectile(Vector2(500, 500), Vector2(0, 100), 1, team, 2000, kind, owner=owner)
    world.projectiles = [shot]
    resolve_projectiles(world, .5)
    assert shot.position == Vector2(550, 550) and shot.velocity == Vector2(200, 100)
    world.room.static_walls = [pygame.FRect(575, 500, 10, 200)]
    world.room.refresh_gates([])
    resolve_projectiles(world, .5)
    assert not shot.alive and shot.position.x == pytest.approx(575 - shot.radius)


def test_wind_does_not_push_player_and_retry_restarts_calm_phase():
    world = arena('wind')
    start = world.player.position.copy()
    world.biome_elapsed = 6.5
    world.step(S.SIMULATION_STEP, InputFrame())
    assert world.player.position == start
    world.retry_checkpoint()
    assert world.biome_elapsed == 0 and world.room.rules.wind_force(0) == Vector2()


def test_wind_integration_is_step_independent_and_range_counts_bent_path():
    shots = []
    for steps in (30, 120):
        shot = Projectile(Vector2(), Vector2(0, 100), 1, 'player', 2000)
        for _ in range(steps):shot.advance(1 / steps, Vector2(160, 0))
        shots.append(shot)
    assert shots[0].position.distance_to(shots[1].position) < 1e-8
    assert shots[0].position == Vector2(80, 100)
    limited = Projectile(Vector2(), Vector2(0, 100), 1, 'player', 40)
    limited.advance(1, Vector2(160, 0))
    assert limited.expired and limited.travelled == 40 and limited.position.length() == pytest.approx(40)


def test_actual_parry_keeps_wind_on_reflected_bolt():
    world = arena('wind')
    world.biome_elapsed = 6.5
    world.player.queue(Command('slash', Vector2(1, 0)))
    world.player.tick(.01, Vector2())
    shot = Projectile(world.player.position + Vector2(150, 0), Vector2(-800, 0), 1, 'enemy', 2000, 'bolt')
    world.projectiles = [shot]
    resolve_projectiles(world, .15)
    assert shot.team == 'player' and shot.kind == 'reflected'
    speed = shot.velocity.x
    resolve_projectiles(world, .1)
    assert shot.velocity.x == pytest.approx(speed + 40)


@pytest.mark.parametrize('biome', ['snow', 'marsh', 'wind'])
def test_biome_rendering_and_marsh_projectile_visibility(monkeypatch, biome):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    pygame.display.init();pygame.font.init()
    try:
        game = Game('temple_01', biome=biome)
        world = game.world
        world.biome_elapsed = 3.5
        game.renderer.draw(game.screen, world, False, 60, False)
        world.biome_elapsed = 6.5
        game.renderer.draw(game.screen, world, False, 60, False)
        game.renderer.draw_map(game.screen, world)
        if biome == 'marsh':
            world.shake = 0
            point = world.player.position + Vector2(530, 0)
            world.projectiles = [Projectile(point, Vector2(-800, 0), 1, 'enemy', 2000, 'bolt')]
            game.renderer.draw(game.screen, world, False, 60, False)
            pixel = tuple(round(v) for v in game.camera.world_to_screen(point))
            assert max(game.screen.get_at(pixel)[:3]) > 120  # Visible above opaque outer fog.
            assert game.renderer.mist.get_at((S.WIDTH + 550, S.HEIGHT)).a == 255
            assert game.renderer.mist.get_at((S.WIDTH, S.HEIGHT)).a == 0
    finally:pygame.quit()
