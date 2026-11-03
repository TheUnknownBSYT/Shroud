"""Destructible cover, first-contact ordering and the three authored bamboo pilots."""
import random
from types import SimpleNamespace

import pygame
import pytest
from pygame import Vector2
from shroud import settings as S
from shroud.campaign import BIOME_IDS, Run, load_level
from shroud.combat import Projectile, make_slash, resolve_melee, resolve_projectiles, segment_rect
from shroud.enemy import Enemy, EnemyState
from shroud.game import Sandbox, Game
from shroud.level import Room, BambooScreen
from shroud.player import Command, InputFrame
from shroud.level_validation import validate_level


@pytest.fixture
def world():
    room = Room()
    room.bounds = pygame.FRect(0, 0, 1200, 800)
    room.static_walls = []
    room.refresh_gates([])
    world = Sandbox(room=room)
    world.enemies = []
    world.player.position = Vector2(900, 600)
    return world


def shoot(world, start=(100, 300), end=(700, 300), team='player', owner='player'):
    bolt = Projectile(Vector2(start), Vector2(end) - Vector2(start), 20, team, 2000,
                      kind='bolt' if team == 'enemy' else 'shuriken', owner=owner)
    world.projectiles.append(bolt)
    resolve_projectiles(world, 1)
    return bolt


@pytest.mark.parametrize('team,owner', [('player', 'player'), ('player', 'echo'), ('enemy', 'enemy')])
def test_cover_absorbs_three_shots_and_fourth_hits_actor(world, team, owner):
    screen = BambooScreen(Vector2(400, 300));world.room.bamboo = [screen]
    target = world.player if team == 'enemy' else Enemy(1, Vector2(600, 300), 999)
    target.position = Vector2(600, 300)
    if team != 'enemy':world.enemies = [target]
    before = target.health
    for hit in range(1, 4):
        first = shoot(world, team=team, owner=owner)
        assert screen.shots_taken == hit and screen.broken == (hit == 3)
        assert not first.alive and target.health == before
        assert first.position.x < screen.position.x
    assert len([fx for fx in world.impacts if fx.kind == 'bamboo']) == 1
    shoot(world, team=team, owner=owner)
    assert target.health < before
    assert len([fx for fx in world.impacts if fx.kind == 'bamboo']) == 1


def test_nearest_screen_wins_even_when_list_order_is_reversed(world):
    near, far = BambooScreen(Vector2(300, 300)), BambooScreen(Vector2(500, 300))
    world.room.bamboo = [far, near]
    for _ in range(3):shoot(world)
    assert near.broken and not far.broken
    for _ in range(3):shoot(world)
    assert far.broken


def test_wall_before_cover_wins_and_cover_before_wall_breaks(world):
    cover = BambooScreen(Vector2(400, 300));world.room.bamboo = [cover]
    world.room.static_walls = [pygame.FRect(250, 200, 20, 200)]
    world.room.refresh_gates([])
    bolt = shoot(world)
    assert not cover.broken and bolt.position.x == pytest.approx(243)
    world.room.static_walls = [pygame.FRect(550, 200, 20, 200)]
    world.room.refresh_gates([])
    shoot(world)
    assert cover.shots_taken == 1 and not cover.broken


@pytest.mark.parametrize('team', ['player', 'enemy'])
def test_actor_before_cover_or_wall_is_hit_first(world, team):
    target = world.player if team == 'enemy' else Enemy(1, Vector2(250, 300), 999)
    target.position = Vector2(250, 300)
    if team == 'player':world.enemies = [target]
    screen = BambooScreen(Vector2(400, 300));world.room.bamboo = [screen]
    world.room.static_walls = [pygame.FRect(550, 200, 20, 200)];world.room.refresh_gates([])
    before = target.health
    shoot(world, team=team)
    assert target.health < before and not screen.broken


def test_wall_wins_exact_contact_tie(world):
    cover = BambooScreen(Vector2(400, 300));world.room.bamboo = [cover]
    world.room.static_walls = [cover.hitbox.copy()];world.room.refresh_gates([])
    shoot(world)
    assert not cover.broken


def test_parry_before_bamboo_cancels_old_path_but_bamboo_before_parry_blocks(world):
    world.player.position = Vector2(400, 300)
    world.player.facing = Vector2(1, 0)
    world.player.queue(Command('slash'));world.player.tick(.01, Vector2())
    cover = BambooScreen(Vector2(200, 300));world.room.bamboo = [cover]
    bolt = shoot(world, start=(700, 300), end=(100, 300), team='enemy')
    assert bolt.alive and bolt.team == 'player' and not cover.broken
    # The same incoming path now meets bamboo before it reaches the parry arc.
    cover.position.x = 600
    world.projectiles.clear()
    bolt = shoot(world, start=(700, 300), end=(100, 300), team='enemy')
    assert cover.shots_taken == 1 and not bolt.alive and bolt.team == 'enemy'
    assert world.player.health == S.PLAYER_HEALTH


@pytest.mark.parametrize('owner', ['player', 'echo'])
def test_slash_cuts_once_with_reach_direction_and_walls_respected(world, owner):
    front = BambooScreen(Vector2(350, 300));rear = BambooScreen(Vector2(200, 300))
    far = BambooScreen(Vector2(500, 300));blocked = BambooScreen(Vector2(300, 355))
    world.room.bamboo = [front, rear, far, blocked]
    world.room.static_walls = [pygame.FRect(280, 325, 40, 10)];world.room.refresh_gates([])
    actor = SimpleNamespace(position=Vector2(300, 300), attack=make_slash(Vector2(1, 0)), damage_active=True)
    if owner == 'echo':world.echo = actor
    resolve_melee(world, actor);resolve_melee(world, actor)
    assert front.broken and not rear.broken and not far.broken and not blocked.broken
    assert [fx.kind for fx in world.impacts] == ['bamboo']
    assert world.stats['targets'] == world.stats['echo_hits'] == 0


def test_walking_and_dashing_stop_until_a_slash_cuts_bamboo(world):
    cover = BambooScreen(Vector2(400, 300));world.room.bamboo = [cover]
    stopped = world.room.move(Vector2(300, 300), Vector2(200, 0), S.PLAYER_RADIUS)
    assert stopped.x == cover.footprint.left - S.PLAYER_RADIUS
    world.player.position = stopped.copy()
    world.player.queue(Command('dash', Vector2(1, 0)));world.player.tick(.01, Vector2())
    resolve_melee(world, world.player)
    assert not cover.broken and cover.shots_taken == 0
    actor = SimpleNamespace(position=stopped, attack=make_slash(Vector2(1, 0)), damage_active=True)
    resolve_melee(world, actor)
    assert cover.broken
    assert world.room.move(Vector2(300, 300), Vector2(200, 0), S.PLAYER_RADIUS) == Vector2(500, 300)


def test_enemy_can_see_through_and_shoot_down_cover(world):
    # Authored-room sight gating runs; movement/gates remain the empty arena fixture.
    world.room.data = {'checkpoints': []};world.room.exit_rect = pygame.FRect(1100, 700, 30, 30)
    world.room.bamboo = [BambooScreen(Vector2(400, 300))]
    world.player.position = Vector2(600, 300)
    world.enemies = [Enemy(1, Vector2(200, 300), 0, activation_range=620)]
    world.step(S.SIMULATION_STEP, InputFrame())
    assert world.enemies[0].state == EnemyState.ATTACK
    for _ in range(1200):
        world.step(S.SIMULATION_STEP, InputFrame())
        if world.room.bamboo[0].broken:break
    assert world.room.bamboo[0].broken
    assert world.player.health == S.PLAYER_HEALTH


def test_reset_and_checkpoint_retry_restore_cover():
    data = load_level('temple_01', 'bamboo')
    data['checkpoints'] = [{'name': 'test refuge', 'spawn': data['spawn'], 'requires': ['seal']}]
    world = Sandbox(room=Room(data))
    for cover in world.room.bamboo:
        cover.broken = True
        cover.shots_taken = S.BAMBOO_SHOT_HITS
    world.checkpoint = data['checkpoints'][0]
    world.retry_checkpoint()
    assert all(not cover.broken and cover.shots_taken == 0 for cover in world.room.bamboo)
    assert world.checkpoint is data['checkpoints'][0] and 'seal' in world.room.open_gates
    world.room.bamboo[0].broken = True
    world.reset()
    assert not world.room.bamboo[0].broken and world.checkpoint is None


@pytest.mark.parametrize('level_id', ['temple_01', 'rooftop_03', 'snow_01'])
def test_pilot_anchors_activate_only_in_bamboo(level_id):
    for biome in BIOME_IDS:
        room = Room(load_level(level_id, biome))
        assert len(room.bamboo) >= 40 if biome == 'bamboo' else len(room.bamboo) == 0
    assert validate_level(load_level(level_id, 'bamboo')) == []


def test_biome_override_is_validated_and_keeps_bamboo_across_loads():
    run = Run(first='temple_01', rng=random.Random(1), biome='bamboo')
    assert [run.load_current()['biome'] for _ in range(3)] == ['bamboo'] * 3
    with pytest.raises(ValueError, match='Unknown biome'):Run(biome='bad')


@pytest.mark.parametrize('start,end,expected', [((0, 5), (20, 5), .25), ((8, 5), (8, 5), 0),
                                                ((0, 20), (20, 20), None), ((20, 5), (0, 5), .5)])
def test_swept_rectangle_contact(start, end, expected):
    result = segment_rect(Vector2(start), Vector2(end), pygame.FRect(5, 0, 5, 10))
    assert result == (pytest.approx(expected) if expected is not None else None)


def test_shot_stops_at_world_boundary(world):
    bolt = shoot(world, start=(1100, 100), end=(1500, 100))
    assert not bolt.alive and bolt.position.x == pytest.approx(1200 - bolt.radius)


def test_boundary_contact_fraction_stays_bounded_at_float_precision_edge(world):
    # FRect may round this endpoint onto its excluded right edge.
    bolt = shoot(world, start=(1180, 100), end=(1193 - 1e-7, 100))
    assert 1180 <= bolt.position.x <= 1193


def test_bamboo_renders_intact_broken_and_survives_new_run_selection(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy');pygame.display.init();pygame.font.init()
    try:
        game = Game('temple_01', run_length=1, biome='bamboo')
        for broken in (False, True):
            for cover in game.world.room.bamboo:cover.broken = broken
            game.renderer.draw(game.screen, game.world, True, 60, False)
            game.renderer.draw_map(game.screen, game.world)
        game.load('snow_01')
        assert game.world.room.biome == 'bamboo' and len(game.world.room.bamboo) >= 40
    finally:pygame.quit()


def test_enemy_shot_crossing_visible_upper_stems_cannot_hit_player(world):
    cover = BambooScreen(Vector2(400, 300));world.room.bamboo = [cover]
    world.player.position = Vector2(600, 255)
    assert cover.prop.rect.collidepoint(400, 255)
    assert not cover.footprint.collidepoint(400, 255)
    bolt = shoot(world, start=(100, 255), end=(700, 255), team='enemy')
    assert not bolt.alive and cover.shots_taken == 1 and not cover.broken
    assert world.player.health == S.PLAYER_HEALTH


@pytest.mark.parametrize('end', [(7, 4), (4, 7)])
def test_continuous_wall_seams_block_movement_and_shots(world, end):
    from shroud.level import bamboo_positions
    points = bamboo_positions({'bamboo_walls': [{'start': [4, 4], 'end': end}]})
    world.room.bamboo = [BambooScreen(p) for p in points]
    horizontal = end[0] != 4
    for a, b in zip(points, points[1:]):
        middle = (a + b) / 2
        offset = Vector2(0, 100) if horizontal else Vector2(100, 0)
        start, finish = middle - offset, middle + offset
        assert world.room.move(start, finish-start, S.PLAYER_RADIUS).distance_to(finish) > 50
        assert world.room.projectile_contact(start, finish, 7) is not None
    for cover in world.room.bamboo:
        cover.broken = True
        cover.shots_taken = S.BAMBOO_SHOT_HITS
    assert world.room.move(start, finish-start, S.PLAYER_RADIUS).distance_to(finish) < .01
