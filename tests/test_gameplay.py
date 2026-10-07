"""Deterministic simulation checks; no window, event loop, or assets required."""
import random
import pytest
from pygame import Vector2
import settings as S
from player import Animation, AnimationController
from game import EventBus
from player import Command, InputFrame
from player import Player, PlayerState
from enemy import Enemy, EnemyState
from combat import Projectile
from combat import segment_circle
from game import Room
from game import Sandbox


def advance(world, seconds, movement=None, commands=()):
    for i in range(round(seconds / S.SIMULATION_STEP)):
        world.step(S.SIMULATION_STEP, InputFrame(movement or Vector2(), list(commands) if i == 0 else []))


def training_world():
    world = Sandbox()
    world.enemies = [Enemy(1, Vector2(310, 435), 999)]
    return world


def test_animation_loop_completion_and_restart():
    clock = AnimationController({"idle": Animation(4, 0.1), "slash": Animation(5, 0.06, False)})
    clock.update(0.51)
    assert clock.frame_index == 1
    clock.play("slash")
    clock.update(0.18)
    assert clock.frame_index == 3
    assert not clock.finished
    clock.update(1)
    assert clock.frame_index == 4 and clock.finished
    clock.play("slash", restart=True)
    assert clock.frame_index == 0 and not clock.finished


@pytest.mark.parametrize("dt", [1 / 30, 1 / 60, 1 / 120, 1 / 240])
def test_movement_normalized_and_frame_independent(dt):
    player = Player(Vector2())
    for _ in range(round(1 / dt)):
        player.tick(dt, Vector2(1, 1))
        player.position += player.velocity * dt
    assert player.position.length() == pytest.approx(S.PLAYER_SPEED)
    player.tick(dt, Vector2())
    assert player.velocity.length() == 0


def test_dash_duration_damage_and_cooldown():
    world = training_world()
    start = world.player.position.copy()
    advance(world, S.DASH_DURATION, commands=[Command("dash")])
    assert world.player.position.x - start.x == pytest.approx(S.DASH_SPEED * S.DASH_DURATION)
    assert world.enemies[0].health == S.ENEMY_HEALTH - S.DASH_DAMAGE
    advance(world, 0.2, commands=[Command("dash")])
    assert world.player.state == PlayerState.IDLE
    assert world.player.action_serial == 1
    advance(world, 0.4)
    advance(world, 0.01, commands=[Command("dash")])
    assert world.player.state == PlayerState.DASHING


def test_slash_startup_then_one_hit_per_swing():
    world = training_world()
    advance(world, 0.05, commands=[Command("slash")])
    assert world.enemies[0].health == S.ENEMY_HEALTH
    advance(world, 0.2)
    assert world.enemies[0].health == S.ENEMY_HEALTH - S.SLASH_DAMAGE
    advance(world, 0.12)
    advance(world, 0.25, commands=[Command("slash")])
    assert world.enemies[0].health == S.ENEMY_HEALTH - 2 * S.SLASH_DAMAGE


def test_slash_ignores_enemy_behind_player():
    world = training_world()
    world.enemies[0].position.x = 200
    advance(world, 0.3, commands=[Command("slash")])
    assert world.enemies[0].health == S.ENEMY_HEALTH


def incoming(world, offset=60):
    bolt = Projectile(world.player.position + Vector2(offset, 0), Vector2(-260, 0), 1, "enemy", 1500, "bolt", 6)
    world.projectiles.append(bolt)
    return bolt


def test_timed_slash_reflects_and_damages_sender():
    world = training_world()
    world.enemies[0].position.x = 400
    bolt = incoming(world)
    events = []
    world.events.subscribe("player_parry", events.append)
    advance(world, 0.01, commands=[Command("slash")])
    assert bolt.team == "player" and bolt.velocity.x > 0
    assert len(events) == 1
    advance(world, 0.4)
    assert world.player.health == S.PLAYER_HEALTH
    assert world.enemies[0].health == S.ENEMY_HEALTH - S.REFLECTED_DAMAGE


def test_late_slash_and_rear_bolt_do_not_parry():
    world = training_world()
    advance(world, 0.17, commands=[Command("slash")])
    incoming(world, 25)
    advance(world, 0.03)
    assert world.player.health == S.PLAYER_HEALTH - 1
    world.reset()
    bolt = incoming(world, -25)
    bolt.velocity.x = 260
    advance(world, 0.03, commands=[Command("slash")])
    assert world.player.health == S.PLAYER_HEALTH - 1


def test_hit_stun_invulnerability_and_death():
    player = Player(Vector2())
    assert player.receive_damage(1)
    assert player.state == PlayerState.STUNNED
    assert not player.receive_damage(1)
    player.tick(S.HIT_INVULNERABILITY + 0.01, Vector2())
    assert player.state == PlayerState.IDLE
    assert player.receive_damage(999)
    assert player.health == 0 and player.state == PlayerState.DEAD
    player.queue(Command("dash"))
    player.tick(1, Vector2(1, 0))
    assert player.state == PlayerState.DEAD and player.velocity.length() == 0


def test_input_buffer_starts_action_once_recovery_finishes():
    world = training_world()
    advance(world, 0.25, commands=[Command("slash")])
    advance(world, 0.07, commands=[Command("dash")])
    assert world.player.state == PlayerState.DASHING
    assert world.player.action_serial == 2


def test_projectile_range_clamps_and_swept_collision_hits():
    projectile = Projectile(Vector2(), Vector2(1000, 0), 20, "player", 250)
    projectile.advance(1)
    assert projectile.position.x == 250 and projectile.expired
    assert segment_circle(Vector2(), Vector2(1000, 0), Vector2(100, 0), 10) == pytest.approx(0.09)
    world = training_world()
    world.projectiles.append(Projectile(Vector2(250, 435), Vector2(10000, 0), 20, "player", 1000))
    advance(world, 0.01)
    assert world.enemies[0].health == S.ENEMY_HEALTH - 20


def test_throw_uses_facing_and_hits_then_despawns():
    world = training_world()
    advance(world, 0.15, commands=[Command("throw")])
    assert world.enemies[0].health == S.ENEMY_HEALTH - S.SHURIKEN_DAMAGE
    assert not world.projectiles


def test_nearest_enemy_takes_projectile_damage():
    world = training_world()
    world.enemies.insert(0, Enemy(2, Vector2(360, 435), 999))
    world.projectiles.append(Projectile(Vector2(250, 435), Vector2(20000, 0), 20, "player", 1000))
    advance(world, 0.01)
    assert world.enemies[0].health == S.ENEMY_HEALTH
    assert world.enemies[1].health == S.ENEMY_HEALTH - 20


def test_wall_slide_boundary_and_dash_cannot_tunnel():
    room = Room()
    end = room.move(Vector2(400, 320), Vector2(500, 0), S.PLAYER_RADIUS)
    assert end.x == pytest.approx(440 - S.PLAYER_RADIUS)
    slid = room.move(Vector2(424, 320), Vector2(50, 50), S.PLAYER_RADIUS)
    assert slid.x == pytest.approx(424) and slid.y > 320
    end = room.move(Vector2(250, 435), Vector2(-1000, 0), S.PLAYER_RADIUS)
    assert end.x == room.bounds.left + S.PLAYER_RADIUS


def test_projectiles_stop_at_walls():
    world = training_world()
    world.projectiles.append(Projectile(Vector2(400, 320), Vector2(1000, 0), 20, "player", 1000))
    advance(world, 0.1)
    assert not world.projectiles


def test_sword_cannot_damage_through_cover():
    world = training_world()
    world.player.position = Vector2(424, 320)
    world.enemies[0].position = Vector2(505, 320)
    advance(world, 0.3, commands=[Command("slash")])
    assert world.enemies[0].health == S.ENEMY_HEALTH


def test_aim_direction_and_active_shuriken_limit():
    world = training_world()
    advance(world, 0.01, commands=[Command("throw", Vector2(0, -100))])
    assert world.player.facing == Vector2(0, -1)
    assert world.projectiles[0].velocity == Vector2(0, -S.SHURIKEN_SPEED)
    advance(world, 0.3)
    world.projectiles = [Projectile(Vector2(200 + i * 20, 200), Vector2(), 20, "player", 1000)
                         for i in range(S.MAX_SHURIKEN)]
    count = world.player.action_serial
    advance(world, 0.01, commands=[Command("throw")])
    assert world.player.action_serial == count
    assert len(world.projectiles) == S.MAX_SHURIKEN


def test_damage_clamps_and_emits_one_defeat():
    world = training_world()
    defeated = []
    world.events.subscribe("enemy_defeated", defeated.append)
    world.enemies[0].health = 1
    advance(world, 0.25, commands=[Command("slash")])
    assert world.enemies[0].health == 0
    assert len(defeated) == 1


def test_enemy_telegraph_locks_aim_and_respawns():
    enemy = Enemy(1, Vector2(), 0)
    assert enemy.tick(0.01, Vector2(100, 0), True) is None
    assert enemy.state == EnemyState.ATTACK
    bolt = enemy.tick(S.ENEMY_TELEGRAPH, Vector2(0, 100), True)
    assert bolt.velocity.x > 0 and bolt.velocity.y == 0
    enemy.receive_damage(999)
    assert enemy.state == EnemyState.DEAD
    enemy.tick(S.ENEMY_RESPAWN, Vector2(), True)
    assert enemy.alive and enemy.state == EnemyState.IDLE


def test_events_and_reset_do_not_persist_combat_state():
    events = EventBus()
    seen = []
    events.subscribe("room_entered", seen.append)
    world = Sandbox(events)
    advance(world, 0.1, commands=[Command("throw")])
    world.reset()
    assert len(seen) == 2
    assert not world.projectiles and not world.impacts
    assert all(value == 0 for value in world.player.cooldowns.values())


def test_five_minute_simulation_stays_bounded_and_can_reset():
    world = Sandbox()
    rng = random.Random(42)
    movement = Vector2()
    for frame in range(5 * 60 * 120):
        commands = []
        if frame % 30 == 0:
            movement = Vector2(rng.choice([-1, 0, 1]), rng.choice([-1, 0, 1]))
            commands = [Command(rng.choice(["dash", "slash", "throw"]))]
        if not world.player.alive:
            world.reset()
        world.step(S.SIMULATION_STEP, InputFrame(movement, commands))
        assert world.room.bounds.collidepoint(world.player.position)
        assert len(world.projectiles) <= 32
        assert len(world.impacts) <= 30
        assert 0 <= world.player.health <= S.PLAYER_HEALTH
