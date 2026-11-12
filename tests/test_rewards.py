"""Run rewards, real combat consequences, authored caches and modal isolation."""
import random
from collections import defaultdict
from types import SimpleNamespace

import pygame
import pytest
from pygame import Vector2
from shroud import settings as S
from shroud.biomes import BiomeRules
from shroud.campaign import BIOME_IDS, load_level
from shroud.combat import Projectile, make_slash, parry_contact, in_arc
from shroud.enemy import Enemy, EnemyState
from shroud.game import EventBus, Game, Sandbox
from shroud.level import Room
from shroud.level_validation import validate_level
from shroud.player import Command, InputFrame, Player, ShadowEcho
from shroud.rewards import Cache, Choice, RunRewards, nearby_cache
from shroud.reward_ui import card_rects, CONFIRM_RECT, CANCEL_RECT


def arena(biome="grounds"):
    room = Room()
    room.rules = BiomeRules.from_level({"biome": biome})
    room.bounds = pygame.FRect(0, 0, 6000, 3000)
    room.static_walls = []
    room.refresh_gates([])
    world = Sandbox(room=room)
    world.enemies.clear()
    world.player.position.update(1000, 1000)
    return world


def step(world, frames=1, movement=(0, 0), commands=()):
    for i in range(frames):
        world.step(S.SIMULATION_STEP, InputFrame(Vector2(movement), list(commands) if i == 0 else []))


def cache(category="technique", offers=None):
    return Cache("test-cache", category, Vector2(), offers=offers)


@pytest.mark.parametrize("key,stat,base,factors", [
    ("sharpening", "slash_damage", S.SLASH_DAMAGE, (1.15, 1.25, 1.30)),
    ("reach", "slash_reach", S.SLASH_REACH, (1.10, 1.20, 1.25)),
    ("quick_charge", "charge_time", S.SLASH_CHARGE_TIME, (.85, .75, .70)),
    ("footwork", "dash_cooldown", S.DASH_COOLDOWN, (.85, .75, .70)),
])
def test_ranks_are_totals_from_base_and_caps_leave_pool(key, stat, base, factors):
    rewards = RunRewards()
    for rank, factor in enumerate(factors, 1):
        assert rewards.upgrade(key)
        assert rewards.ranks[key] == rank
        assert getattr(rewards.effective(), stat) == pytest.approx(base * factor)
    assert not rewards.upgrade(key) and key not in rewards.eligible("technique")
    rewards.reset()
    assert getattr(rewards.effective(), stat) == base and not rewards.ranks


def test_baseline_and_captured_slash_echo_charge_and_parry(monkeypatch):
    world = arena()
    assert world.player.rewards.effective().slash_damage == S.SLASH_DAMAGE
    baseline = make_slash(Vector2(1, 0))
    step(world, commands=[Command("slash")])
    assert (world.player.attack.damage, world.player.attack.reach, world.player.attack.direction) == (baseline.damage, baseline.reach, baseline.direction)
    world.reset()
    world.enemies.clear()
    rewards = world.rewards
    rewards.ranks = {"sharpening": 2, "reach": 3, "quick_charge": 3, "footwork": 3}
    player = world.player
    player.queue(Command("hold_slash"))
    player.tick(.525, Vector2())
    assert player.hold_progress == pytest.approx(1)
    player.queue(Command("release_slash"))
    player.tick(S.SIMULATION_STEP, Vector2())
    attack = player.attack
    assert attack.damage == round(S.SLASH_DAMAGE * 1.25 * S.SLASH_CHARGE_DAMAGE)
    assert attack.reach == pytest.approx(S.SLASH_REACH * 1.25 * S.SLASH_CHARGE_REACH)
    echo = ShadowEcho(Vector2(), Vector2(1, 0))
    echo.queue("slash", player.facing, player.action_charge, attack)
    attack.hit_entities.add(5)
    rewards.reset()
    echo.tick(S.ECHO_DELAY)
    assert echo.attack.damage == attack.damage and echo.attack.reach == attack.reach
    assert echo.attack.hit_entities == set() and echo.attack is not attack
    bolt = Projectile(Vector2(90, 0), Vector2(), 1, "enemy", 100, radius=1)
    assert in_arc(echo.position, echo.facing, bolt.position, bolt.radius, echo.attack.reach)
    assert parry_contact(echo, bolt) is None  # Upgraded sword reach, unchanged parry reach.
    rewards.upgrade("footwork")
    player._start_action("dash")
    assert player.cooldowns["dash"] == pytest.approx(S.DASH_COOLDOWN * .85)
    echo = ShadowEcho(Vector2(), Vector2(1, 0))
    echo.queue("throw", Vector2(1, 0))
    original = echo.projectile.damage
    monkeypatch.setattr(S, "SHURIKEN_DAMAGE", 999)
    echo.tick(S.ECHO_DELAY)
    assert echo.projectile.damage == original and echo.projectile.owner == "echo"


@pytest.mark.parametrize("category", ["technique", "burst"])
def test_fixed_distinct_offers_rng_isolation_and_once_only(category):
    rewards = RunRewards(random.Random(4))
    player = Player(Vector2(), rewards=rewards)
    state = player.rng.getstate()
    bus, events = EventBus(), []
    for name in ("reward_offered", "reward_confirmed"):
        bus.subscribe(name, lambda event, name=name: events.append(name))
    chest = cache(category)
    offers = chest.offer(rewards, bus)
    assert len(offers) == len(set(offers)) == 2
    assert set(offers) <= set(rewards.eligible(category))
    rng_state = rewards.rng.getstate()
    for _ in range(5):
        assert chest.offer(rewards, bus) == offers
        assert Choice(chest).cancel()
    assert rewards.rng.getstate() == rng_state and player.rng.getstate() == state
    choice = Choice(chest)
    assert not choice.confirm(rewards, bus)
    choice.select(1)
    assert choice.confirm(rewards, bus)
    assert not choice.confirm(rewards, bus) and chest.offer(rewards, bus) is None
    assert events == ["reward_offered", "reward_confirmed"]
    assert (rewards.ranks == {offers[1]: 1}) if category == "technique" else rewards.stored == offers[1]


def test_exhausted_pool_and_stale_capped_offer_do_not_consume():
    rewards, bus = RunRewards(random.Random(2)), EventBus()
    rewards.ranks = {key: 3 for key in rewards.eligible("technique")}
    for remaining in (0, 1):
        if remaining:
            rewards.ranks["reach"] = 2
        chest = cache()
        before = rewards.rng.getstate()
        assert chest.offer(rewards, bus) is None
        assert not chest.claimed and chest.offers is None and rewards.rng.getstate() == before
    stale = Choice(cache(offers=("sharpening", "reach")), selected=0)
    assert not stale.confirm(rewards, bus) and not stale.cache.claimed
    stale.select(1)
    assert stale.confirm(rewards, bus) and rewards.ranks["reach"] == 3


def test_burst_replacement_cancel_waiting_charge_and_exact_expiry():
    rewards, bus, expired = RunRewards(), EventBus(), []
    bus.subscribe("burst_expired", expired.append)
    rewards.stored = "haste"
    assert rewards.activate(bus)
    rewards.stored = "smoke_veil"
    choice = Choice(cache("burst", ("haste", "smoke_veil")), selected=0)
    assert not choice.confirm(rewards, bus) and choice.replacing
    assert not choice.cancel() and rewards.stored == "smoke_veil" and not choice.cache.claimed
    assert not choice.confirm(rewards, bus)
    assert choice.confirm(rewards, bus) and rewards.stored == "haste"
    assert not rewards.activate(bus) and rewards.remaining == 10
    for _ in range(1199):
        rewards.tick(1 / 120, bus)
    assert rewards.active == "haste" and not expired
    rewards.tick(1 / 120, bus)
    assert rewards.active is None and rewards.expired == "haste" and len(expired) == 1
    assert rewards.effective().move_speed == S.PLAYER_SPEED
    assert rewards.activate(bus) and rewards.stored is None
    rewards.reset()
    assert rewards.active is rewards.stored is rewards.expired is None and rewards.remaining == 0


def test_smoke_cancels_windup_but_existing_projectiles_still_damage():
    world = arena()
    enemy = Enemy(1, world.player.position + Vector2(200, 0), 0)
    world.enemies = [enemy]
    step(world)
    assert enemy.state == EnemyState.ATTACK
    aim = enemy.aim.copy()
    world.rewards.stored = "smoke_veil"
    step(world, commands=[Command("burst")])
    assert enemy.state == EnemyState.IDLE
    step(world, 1198, movement=(0, .1))
    assert enemy.aim == aim and not world.projectiles
    incoming = Projectile(world.player.position + Vector2(10, 0), Vector2(-300, 0), 1, "enemy", 100)
    world.projectiles.append(incoming)
    health = world.player.health
    step(world)
    assert world.player.health == health - 1 and world.rewards.active is None
    step(world, 60)
    assert not world.projectiles and enemy.state == EnemyState.IDLE
    step(world, 150)
    assert enemy.state in (EnemyState.ATTACK, EnemyState.COOLDOWN)


@pytest.mark.parametrize("biome", ["grounds", "snow"])
def test_haste_collision_dash_and_expiry_restore_base_without_drift(biome):
    world = arena(biome)
    world.room.static_walls = [pygame.FRect(1100, 500, 20, 1000)]
    world.room.refresh_gates([])
    world.rewards.stored = "haste"
    step(world, 120, movement=(1, 0), commands=[Command("burst")])
    assert world.player.position.x <= 1100 - S.PLAYER_RADIUS
    assert world.player.velocity.x == 0
    world.player.position.update(2000, 1000)
    step(world, 120, movement=(1, 0))
    assert world.player.velocity.length() == pytest.approx(450)
    step(world, movement=(1, 0), commands=[Command("dash")])
    assert world.player.velocity.length() == S.DASH_SPEED
    step(world, 120)
    world.rewards.remaining = S.SIMULATION_STEP
    step(world, movement=(1, 0))
    assert world.rewards.active is None and world.player.velocity.length() <= S.PLAYER_SPEED
    step(world, 120, movement=(1, 0))
    assert world.player.velocity.length() == pytest.approx(S.PLAYER_SPEED)


@pytest.mark.parametrize("biome", BIOME_IDS)
def test_authored_caches_reachable_at_unlock_stage_in_every_biome(biome):
    data = load_level("training_01", biome)
    assert [c["category"] for c in data["caches"]].count("technique") == 3
    assert [c["category"] for c in data["caches"]].count("burst") == 2
    assert validate_level(data) == []
    world = Sandbox(room=Room(data))
    chest = next(c for c in world.caches if c.requires)
    world.player.position = chest.position.copy()
    assert nearby_cache(world) is None
    world.room.open_gates.update(chest.requires)
    world.room.refresh_gates([])
    assert nearby_cache(world) is chest


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()
    game = Game("training_01", run_length=2, seed=7, biome="grounds")
    game.world.player.position = game.world.caches[0].position + Vector2(0, -60)
    game.clock = SimpleNamespace(tick=lambda fps: 100, get_fps=lambda: 10)
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: defaultdict(bool))
    yield game
    pygame.quit()


def key(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False)


def click(rect):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center)


def frame(game, monkeypatch, events):
    monkeypatch.setattr(pygame.event, "get", lambda: events)
    game.run(frame_limit=1)


def test_mouse_keyboard_choice_freezes_world_and_never_attacks(game, monkeypatch):
    world = game.world
    world.rewards.stored = "haste"
    world.rewards.activate(world.events)
    world.player.queue(Command("hold_slash"))
    frame(game, monkeypatch, [key(pygame.K_e), key(pygame.K_q), click(card_rects()[0])])
    assert game.choice and world.player.held_action is None
    assert game.choice.selected is None and world.time == 0
    offers = game.choice.cache.offers
    layout_rng = game.run_rng.getstate()
    frame(game, monkeypatch, [click(card_rects()[1])])
    frame(game, monkeypatch, [pygame.event.Event(pygame.MOUSEMOTION, pos=card_rects()[0].center)])
    assert game.choice.selected == 1
    frame(game, monkeypatch, [key(pygame.K_ESCAPE)])
    frame(game, monkeypatch, [key(pygame.K_e)])
    assert game.choice.cache.offers == offers
    assert game.run_rng.getstate() == layout_rng
    frame(game, monkeypatch, [key(pygame.K_1), click(CONFIRM_RECT), key(pygame.K_q)])
    assert game.choice is None and world.rewards.ranks == {offers[0]: 1}
    frame(game, monkeypatch, [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=CONFIRM_RECT.center)])
    assert world.player.action_serial == 0 and not world.projectiles
    assert world.time == pytest.approx(.1) and world.rewards.remaining == pytest.approx(9.9)


@pytest.mark.parametrize("opening,closing", [
    (pygame.K_p, pygame.K_p), (pygame.K_TAB, pygame.K_TAB), (pygame.K_F2, pygame.K_ESCAPE),
    (None, pygame.K_p),
])
def test_all_menus_focus_and_boundary_batches_freeze_bursts(game, monkeypatch, opening, closing):
    world = game.world
    world.rewards.stored = "smoke_veil"
    world.rewards.activate(world.events)
    world.rewards.stored = "haste"
    game.input.cursor = Vector2(640, 400)
    event = key(opening) if opening else pygame.event.Event(pygame.WINDOWFOCUSLOST)
    frame(game, monkeypatch, [key(pygame.K_j), event, key(pygame.K_q)])
    if opening is None:
        assert game.input.cursor is None
    for _ in range(3):
        frame(game, monkeypatch, [key(pygame.K_q)])
    frame(game, monkeypatch, [key(closing), key(pygame.K_q), key(pygame.K_j)])
    assert world.time == 0 and world.rewards.remaining == 10
    assert world.rewards.stored == "haste" and world.player.action_serial == 0
    frame(game, monkeypatch, [])
    assert world.time == pytest.approx(.1)  # No catch-up for the six modal frames.


def test_replacement_buttons_and_reset_across_levels_death_and_finish(game, monkeypatch):
    world = game.world
    chest = cache("burst", ("smoke_veil", "haste"))
    game.choice = Choice(chest, selected=1)
    world.rewards.stored = "smoke_veil"
    frame(game, monkeypatch, [click(CONFIRM_RECT)])
    assert game.choice.replacing and not chest.claimed
    frame(game, monkeypatch, [click(CANCEL_RECT)])
    assert not game.choice.replacing and world.rewards.stored == "smoke_veil"
    frame(game, monkeypatch, [key(pygame.K_RETURN)])
    frame(game, monkeypatch, [key(pygame.K_RETURN)])
    assert chest.claimed and game.choice is None and world.rewards.stored == "haste"
    world.rewards.upgrade("reach")
    world.complete = True
    game.advance()
    assert game.world.rewards is world.rewards and game.world.rewards.ranks == {"reach": 1}
    game.world.player.receive_damage(999)
    assert not game.rewards.ranks and game.rewards.stored is None
    game.world.retry_checkpoint()
    game.rewards.upgrade("footwork")
    frame(game, monkeypatch, [key(pygame.K_r)])
    assert not game.rewards.ranks and all(not c.claimed for c in game.world.caches)
    game.rewards.upgrade("reach")
    game.load("training_01")
    assert not game.rewards.ranks
    world = game.world
    world.run_position = world.run_length
    world.rewards.upgrade("reach")
    world.rewards.stored = "haste"
    world.room.open_gates = {name for name, _ in world.room.gates}
    world.room.refresh_gates([])
    world.player.position = Vector2(world.room.exit_rect.center)
    step(world)
    assert world.complete and not world.rewards.ranks and world.rewards.stored is None


def test_pending_input_before_open_and_rendering_cannot_change_rewards(game, monkeypatch):
    ticks = iter([1, 100, 100, 100])
    batches = iter([[key(pygame.K_j)], [key(pygame.K_e)], [key(pygame.K_ESCAPE)], []])
    game.clock = SimpleNamespace(tick=lambda fps: next(ticks), get_fps=lambda: 10)
    monkeypatch.setattr(pygame.event, "get", lambda: next(batches))
    game.run(frame_limit=4)  # J initially waits for a physics step; E must discard it.
    assert game.world.player.action_serial == 0 and game.world.time == pytest.approx(.1)
    choice = Choice(game.world.caches[0])
    game.rewards.stored = "smoke_veil"
    game.rewards.activate(game.world.events)
    labels = []
    ui = game.renderer.reward_ui
    monkeypatch.setattr(ui, "text", lambda screen, text, *args, **kwargs: labels.append(text))
    before = (game.rewards.rng.getstate(), game.rewards.remaining, choice.cache.opening)
    for _ in range(10):
        ui.overlay(game.screen, game.world, choice)
        ui.status(game.screen, game.world, paused=True)
    assert before == (game.rewards.rng.getstate(), game.rewards.remaining, choice.cache.opening)
    assert any("PAUSED" in label and "10.0s" in label for label in labels)
