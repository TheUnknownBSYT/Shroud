"""Echo timing and combat checks without a display."""
import pytest
from pygame import Vector2
import settings as S
from combat import Projectile
from enemy import Enemy
from game import Sandbox
from player import Command, EchoState, InputFrame


def advance(world, seconds, commands=()):
    for frame in range(round(seconds / S.SIMULATION_STEP)):
        world.step(S.SIMULATION_STEP, InputFrame(commands=list(commands) if frame == 0 else []))


def dash(world, direction=Vector2(1, 0)):
    world.player.facing = direction.copy()
    advance(world, 0.16, [Command("dash")])


def empty_world():
    world = Sandbox()
    world.enemies.clear()
    return world


def test_dash_leaves_one_stationary_echo_and_cooldown_does_not_replace_it():
    world = empty_world()
    origin = world.player.position.copy()
    dash(world)
    echo = world.echo
    assert echo.position == origin
    assert world.player.position != origin
    assert echo.state == EchoState.WAITING
    advance(world, 0.2, [Command("dash")])
    assert world.echo is echo
    advance(world, 0.3)
    next_origin = world.player.position.copy()
    dash(world)
    assert world.echo is not echo
    assert world.echo.position == next_origin
    assert echo.position == origin


def test_echo_slash_is_delayed_and_hits_each_enemy_once():
    world = empty_world()
    enemy = Enemy(1, world.player.position + Vector2(0, 60), 999)
    world.enemies.append(enemy)
    dash(world)
    advance(world, S.SIMULATION_STEP, [Command("slash", Vector2(0, 1))])
    assert world.echo.state == EchoState.ATTACK_QUEUED
    advance(world, S.ECHO_DELAY - S.SIMULATION_STEP)
    assert world.echo.state == EchoState.ATTACK_QUEUED
    assert enemy.health == S.ENEMY_HEALTH
    advance(world, S.SIMULATION_STEP)
    assert world.echo.state == EchoState.ATTACKING
    assert enemy.health == S.ENEMY_HEALTH
    advance(world, S.SLASH_DURATION)
    assert enemy.health == S.ENEMY_HEALTH - S.SLASH_DAMAGE
    advance(world, S.ECHO_FADE_DURATION)
    assert world.echo is None
    assert enemy.health == S.ENEMY_HEALTH - S.SLASH_DAMAGE


def test_echo_throw_keeps_original_direction_and_costs_no_extra_capacity():
    world = empty_world()
    dash(world)
    origin = world.echo.position.copy()
    aim = Vector2(3, 4)
    advance(world, S.SIMULATION_STEP, [Command("throw", aim)])
    expected_direction = aim.normalize()
    # Keep the original alive while testing capacity, independent of range tuning.
    world.projectiles[0].max_range = 1000
    aim.update(-1, 0)
    world.player.facing = Vector2(-1, 0)
    # Fill the player's active-star allowance after the original throw.
    for i in range(S.MAX_SHURIKEN - 1):
        world.projectiles.append(Projectile(Vector2(100 + 20 * i, 200), Vector2(), 20, "player", 1000))
    advance(world, S.ECHO_DELAY)
    echo_stars = [p for p in world.projectiles if p.owner == "echo"]
    assert len(echo_stars) == 1
    star = echo_stars[0]
    assert star.velocity == expected_direction * S.SHURIKEN_SPEED
    assert star.previous == origin + expected_direction * 24
    assert len(world.projectiles) == S.MAX_SHURIKEN + 1
    enemy = Enemy(1, star.position + expected_direction * 55, 999)
    world.enemies.append(enemy)
    advance(world, 0.15)
    assert enemy.health == S.ENEMY_HEALTH - S.SHURIKEN_DAMAGE
    advance(world, S.THROW_DURATION + S.ECHO_FADE_DURATION)
    assert world.echo is None


@pytest.mark.parametrize("timing,direction,reflects", [
    (0.02, Vector2(1, 0), True),
    (0.16, Vector2(1, 0), False),
    (0.02, Vector2(-1, 0), False),
])
def test_echo_parry_uses_the_same_window_and_facing_rules(timing, direction, reflects):
    world = empty_world()
    origin = world.player.position.copy()
    enemy = Enemy(1, origin + Vector2(180, 0), 999)
    world.enemies.append(enemy)
    dash(world, Vector2(0, -1))
    advance(world, S.SIMULATION_STEP, [Command("slash", direction)])
    advance(world, S.ECHO_DELAY + timing)
    bolt = Projectile(origin + Vector2(60, 0), Vector2(-260, 0), 1, "enemy", 1500, "bolt", 6)
    world.projectiles.append(bolt)
    advance(world, S.SIMULATION_STEP)
    assert (bolt.team == "player") is reflects
    advance(world, 0.4)
    assert world.player.health == S.PLAYER_HEALTH
    expected_damage = S.REFLECTED_DAMAGE if reflects else 0
    assert enemy.health == S.ENEMY_HEALTH - expected_damage


def test_new_dash_cancels_queued_attack_and_echo_only_captures_first_action():
    world = empty_world()
    dash(world)
    advance(world, 0.25)
    advance(world, S.SIMULATION_STEP, [Command("throw", Vector2(0, -1))])
    old_echo = world.echo
    old_echo.queue("slash", Vector2(1, 0))
    assert old_echo.action == "throw"
    advance(world, 0.25)
    dash(world)
    assert world.echo is not old_echo
    assert world.echo.state == EchoState.WAITING
    assert not any(p.owner == "echo" for p in world.projectiles)


def test_unused_echo_expires_rejected_input_does_not_consume_and_reset_clears():
    world = empty_world()
    dash(world)
    world.player.cooldowns["slash"] = 1
    advance(world, 0.2, [Command("slash")])
    assert world.echo.state == EchoState.WAITING
    advance(world, S.ECHO_LIFETIME + S.ECHO_FADE_DURATION)
    assert world.echo is None
    dash(world)
    advance(world, S.SIMULATION_STEP, [Command("throw")])
    assert world.echo.state == EchoState.ATTACK_QUEUED
    world.reset()
    assert world.echo is None
    assert world.projectiles == []


def test_attack_queued_before_expiry_finishes_even_after_waiting_lifetime():
    world = empty_world()
    dash(world)
    advance(world, world.echo.timer - 0.05)
    advance(world, S.SIMULATION_STEP, [Command("throw")])
    advance(world, S.ECHO_DELAY)
    assert any(p.owner == "echo" for p in world.projectiles)
    advance(world, S.THROW_DURATION + S.ECHO_FADE_DURATION)
    assert world.echo is None
