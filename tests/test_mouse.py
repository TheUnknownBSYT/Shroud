"""Mouse aiming, charge/release, and action cancellation regressions."""
from collections import defaultdict
from types import SimpleNamespace

import pygame
import pytest
from pygame import Vector2

import settings as S
from combat import Projectile
from enemy import Enemy
from game import Game, InputHandler, Sandbox
from player import Command, InputFrame, Player, ShadowEcho


@pytest.fixture
def pygame_input(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    yield
    pygame.quit()


def step(world, seconds=S.SIMULATION_STEP, commands=(), target=None, movement=None):
    for index in range(round(seconds / S.SIMULATION_STEP)):
        world.step(S.SIMULATION_STEP, InputFrame(
            movement or Vector2(), list(commands) if index == 0 else [], target))


def empty_world():
    world = Sandbox()
    world.enemies.clear()
    return world


def test_aim_smoothing_is_frame_independent_and_takes_short_route():
    directions = []
    for dt in (1 / 30, 1 / 60, 1 / 120, 1 / 240):
        player = Player(Vector2())
        player.aim_direction = Vector2(1, 0).rotate(179)
        target = Vector2(100, 0).rotate(-179)
        for _ in range(round(0.1 / dt)):
            player.update_aim(dt, target)
        directions.append(player.aim_direction)
        assert abs(player.aim_direction.angle_to(target)) < 0.2
        assert player.aim_direction.length() == pytest.approx(1)
    for direction in directions:
        assert direction.distance_to(directions[0]) < 1e-8


def test_cursor_deadzone_and_strafing_keep_aim_stable():
    world = empty_world()
    origin = world.player.position.copy()
    step(world, 0.2, target=origin + Vector2(400, 0), movement=Vector2(0, 1))
    assert world.player.position.y > origin.y
    assert world.player.facing.x > 0.98
    before = world.player.aim_direction.copy()
    world.player.update_aim(0.1, world.player.position)
    assert world.player.aim_direction == before


def test_mouse_events_hold_and_release_once(monkeypatch, pygame_input):
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: defaultdict(bool))
    reader = InputHandler()
    frame = reader.read([
        pygame.event.Event(pygame.MOUSEMOTION, pos=(300, 400)),
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(300, 400)),
    ], Vector2())
    assert [c.action for c in frame.commands] == ["hold_throw"]
    assert frame.aim_target == Vector2(300, 400)
    assert reader.read([], Vector2()).commands == []
    frame = reader.read([pygame.event.Event(pygame.MOUSEBUTTONUP, button=3, pos=(320, 400))], Vector2())
    assert [c.action for c in frame.commands] == ["release_throw"]
    assert frame.aim_target == Vector2(320, 400)


@pytest.mark.parametrize("hold,spread", [(0, S.SHURIKEN_SPREAD), (0.225, S.SHURIKEN_SPREAD / 2), (0.6, 0)])
def test_shuriken_spread_shrinks_to_zero_and_fires_only_on_release(hold, spread):
    world = empty_world()
    world.player.rng = SimpleNamespace(uniform=lambda low, high: high)
    world.player.queue(Command("hold_throw"))
    if hold:
        step(world, hold)
    assert not world.projectiles
    assert world.player.action_serial == 0
    step(world, commands=[Command("release_throw")])
    star = world.projectiles[0]
    assert Vector2(1, 0).angle_to(star.velocity) == pytest.approx(spread)
    assert world.player.held_action is None
    step(world, commands=[Command("release_throw")])
    assert world.player.action_serial == 1


def test_charged_slash_extends_reach_and_echo_copies_its_damage():
    world = empty_world()
    origin = world.player.position.copy()
    world.echo = ShadowEcho(origin, Vector2(1, 0))
    enemy = Enemy(1, origin + Vector2(110, 0), 999)
    world.enemies.append(enemy)
    step(world, 1, [Command("hold_slash")])
    assert enemy.health == enemy.max_health
    assert world.player.hold_progress == 1
    step(world, commands=[Command("release_slash")])
    assert world.player.attack.damage == S.SLASH_DAMAGE * S.SLASH_CHARGE_DAMAGE
    assert world.player.attack.reach == pytest.approx(S.SLASH_REACH * S.SLASH_CHARGE_REACH)
    step(world, 0.25)
    assert enemy.health == enemy.max_health - 60  # One hit despite many active frames.
    step(world, S.ECHO_DELAY)
    assert enemy.health == 0


def test_quick_slash_and_no_parry_while_charging():
    world = empty_world()
    step(world, commands=[Command("hold_slash")])
    assert not world.player.parry_active
    step(world, commands=[Command("release_slash")])
    assert world.player.parry_active
    assert world.player.attack.damage == S.SLASH_DAMAGE


def test_attack_and_echo_direction_do_not_follow_later_mouse_motion():
    world = empty_world()
    world.echo = ShadowEcho(world.player.position, Vector2(1, 0))
    step(world, commands=[Command("hold_slash"), Command("release_slash")])
    direction = world.player.facing.copy()
    step(world, 0.15, target=world.player.position + Vector2(0, -300))
    assert world.player.aim_direction.y < -0.9
    assert world.player.attack.direction == direction
    assert world.player.facing == direction
    assert world.echo.facing == direction


@pytest.mark.parametrize("cancel", ["dash", "hurt", "death", "reset"])
def test_interruption_cancels_charge_and_late_release(cancel):
    world = empty_world()
    step(world, 0.3, [Command("hold_slash")])
    if cancel == "dash":
        step(world, commands=[Command("dash")], movement=Vector2(0, 1))
        assert world.player.facing == Vector2(0, 1)
    elif cancel == "reset":
        world.reset()
    else:
        world.player.receive_damage(999 if cancel == "death" else 1)
    assert world.player.held_action is None
    serial = world.player.action_serial
    step(world, 0.5, [Command("release_slash")])
    assert world.player.action_serial == serial


def test_mouse_release_respects_active_star_limit():
    world = empty_world()
    world.projectiles = [Projectile(Vector2(100 + i * 20, 200), Vector2(), 20, "player", 1000)
                         for i in range(S.MAX_SHURIKEN)]
    step(world, 0.6, [Command("hold_throw")])
    step(world, commands=[Command("release_throw")])
    assert len(world.projectiles) == S.MAX_SHURIKEN
    assert world.player.action_serial == 0
    assert world.player.held_action is None
    world.projectiles.clear()
    step(world, 0.1)
    assert not world.projectiles  # A rejected release cannot fire later.


@pytest.mark.parametrize("event", [pygame.event.Event(pygame.WINDOWFOCUSLOST),
                                   pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p)])
def test_pause_and_focus_loss_cancel_charge_without_firing(monkeypatch, event, pygame_input):
    game = Game.__new__(Game)
    game.world = empty_world()
    step(game.world, 0.3, [Command("hold_throw")])
    before = game.world.time
    game.input = InputHandler()
    game.clock = SimpleNamespace(tick=lambda fps: 16, get_fps=lambda: 60)
    game.renderer = SimpleNamespace(draw=lambda *args: None, update=lambda *args: None)
    game.screen, game.debug, game.paused = None, False, False
    monkeypatch.setattr(pygame.event, "get", lambda: [event])
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: defaultdict(bool))
    monkeypatch.setattr(pygame.display, "flip", lambda: None)
    game.run(frame_limit=1)
    assert game.paused
    assert game.world.time == before
    assert game.world.player.held_action is None
    assert not game.world.projectiles
