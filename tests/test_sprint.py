"""Sprint input, combat exclusion, and forgiving ranged combat."""
from collections import defaultdict

import pygame
import pytest
from pygame import Vector2

from shroud import settings as S
from shroud.combat import make_shuriken, resolve_projectiles
from shroud.enemy import Enemy
from shroud.game import InputHandler, Sandbox
from shroud.player import Command, InputFrame, Player, PlayerState


@pytest.mark.parametrize('movement', [Vector2(1, 0), Vector2(1, 1)])
def test_sprint_speed_and_release(movement):
    player = Player(Vector2())
    player.set_sprint(True)
    player.tick(S.SIMULATION_STEP, movement)
    assert player.velocity.length() == pytest.approx(480)
    player.set_sprint(False)
    player.tick(S.SIMULATION_STEP, movement)
    assert player.velocity.length() == pytest.approx(S.PLAYER_SPEED)


@pytest.mark.parametrize('action', ['slash', 'throw', 'dash', 'hold_slash', 'hold_throw'])
def test_sprint_blocks_all_new_attacks_and_does_not_defer_them(action):
    world = Sandbox()
    world.enemies.clear()
    world.step(S.SIMULATION_STEP, InputFrame(commands=[Command(action)], sprint=True))
    assert world.player.action_serial == 0
    assert world.player.held_action is None
    world.step(S.SIMULATION_STEP, InputFrame())
    assert world.player.action_serial == 0


@pytest.mark.parametrize('action', ['slash', 'throw'])
def test_sprint_cancels_charge_and_buffer(action):
    player = Player(Vector2())
    player.queue(Command('hold_' + action))
    player.queue(Command(action))
    player.set_sprint(True)
    assert player.held_action is None and player.buffered is None
    player.set_sprint(False)
    player.queue(Command('release_' + action))
    assert player.tick(S.SIMULATION_STEP, Vector2()) is None


def test_active_slash_finishes_before_sprinting():
    player = Player(Vector2())
    player.queue(Command('slash'))
    player.tick(S.SIMULATION_STEP, Vector2(1, 0))
    player.set_sprint(True)
    player.tick(S.SIMULATION_STEP, Vector2(1, 0))
    assert player.state == PlayerState.ATTACKING
    assert not player.sprinting
    assert player.velocity.length() == S.PLAYER_SPEED
    player.tick(S.SLASH_DURATION, Vector2(1, 0))
    assert player.sprinting and player.attack is None
    assert player.velocity.length() == S.SPRINT_SPEED


@pytest.fixture
def space_input(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: defaultdict(bool))
    clock = [1000]
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: clock[0])
    yield InputHandler(), clock
    pygame.display.quit()


def space_event(kind):
    return pygame.event.Event(kind, key=pygame.K_SPACE)


def test_space_tap_dashes_only_on_release(space_input):
    reader, clock = space_input
    frame = reader.read([space_event(pygame.KEYDOWN)], Vector2())
    assert not frame.commands and not frame.sprint
    clock[0] += 100
    frame = reader.read([space_event(pygame.KEYUP)], Vector2())
    assert [c.action for c in frame.commands] == ["dash"] and not frame.sprint
    assert not reader.read([], Vector2()).commands


def test_space_hold_sprints_without_dashing_on_release(space_input):
    reader, clock = space_input
    reader.read([space_event(pygame.KEYDOWN)], Vector2())
    clock[0] += 179
    assert not reader.read([], Vector2()).sprint
    clock[0] += 1
    frame = reader.read([], Vector2())
    assert frame.sprint and not frame.commands
    clock[0] += 200
    frame = reader.read([space_event(pygame.KEYUP)], Vector2())
    assert not frame.sprint and not frame.commands


@pytest.mark.parametrize("event", [pygame.event.Event(pygame.WINDOWFOCUSLOST),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F2)])
def test_interrupted_space_never_dashes_on_late_release(space_input, event):
    reader, clock = space_input
    reader.read([space_event(pygame.KEYDOWN)], Vector2())
    clock[0] += 50
    reader.read([event], Vector2())
    frame = reader.read([space_event(pygame.KEYUP)], Vector2())
    assert not frame.sprint and not frame.commands


def test_repeated_space_does_not_restart_hold(space_input):
    reader, clock = space_input
    reader.read([space_event(pygame.KEYDOWN)], Vector2())
    clock[0] += 200
    frame = reader.read([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, repeat=True)], Vector2())
    assert frame.sprint and not frame.commands


def test_long_press_and_release_between_reads_does_not_dash(space_input):
    reader, clock = space_input
    reader.read([space_event(pygame.KEYDOWN)], Vector2())
    clock[0] += 300
    frame = reader.read([space_event(pygame.KEYUP)], Vector2())
    assert not frame.commands and not frame.sprint


@pytest.mark.parametrize('owner', ['player', 'echo'])
def test_shuriken_hits_distant_grazing_target(owner):
    world = Sandbox()
    origin = world.player.position.copy()
    enemy = Enemy(1, origin + Vector2(400, 35), 999)
    world.enemies = [enemy]
    world.projectiles = [make_shuriken(origin, Vector2(1, 0), owner)]
    for _ in range(80):
        resolve_projectiles(world, S.SIMULATION_STEP)
    assert enemy.health == enemy.max_health - S.SHURIKEN_DAMAGE
    assert not world.projectiles


def test_shuriken_still_has_finite_range():
    star = make_shuriken(Vector2(), Vector2(1, 0))
    star.advance(10)
    assert star.expired and star.travelled == 520
    assert star.position.x == 544  # Includes its 24-pixel spawn offset.
