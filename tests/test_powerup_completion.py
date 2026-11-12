"""Complete modifier interactions, frozen action phases and detached run evidence."""
import json
import random
from types import SimpleNamespace
import pygame
import pytest
from pygame import Vector2
from shroud import settings as S
from shroud.combat import Projectile, deal_damage, resolve_projectiles, parry_contact
from shroud.enemy import Enemy
from shroud.game import Game, Sandbox, EventBus
from shroud.history import RunHistory
from shroud.player import Command, InputFrame, Player, PlayerState, ShadowEcho, EchoState
from shroud.rewards import REWARDS, RunRewards, Cache, Choice
from shroud.reward_ui import CONFIRM_RECT, CANCEL_RECT, card_rects, value_text, bonus_text
from tools.powerup_lab import configure


def arena():
    world = Sandbox()
    world.enemies.clear()
    world.room.bounds = pygame.FRect(0, 0, 6000, 4000)
    world.room.static_walls = []
    world.room.refresh_gates([])
    world.player.position.update(1000, 1000)
    return world


def step(world, seconds=S.SIMULATION_STEP, commands=(), movement=(0, 0)):
    for index in range(round(seconds / S.SIMULATION_STEP)):
        world.step(S.SIMULATION_STEP, InputFrame(Vector2(movement), list(commands) if index == 0 else []))


def action(world, kind):
    # Wait for real recovery/cooldown rather than overriding the player's state.
    step(world, .5)
    step(world, commands=[Command(kind)])
    return world.player.projectile if kind == "throw" else world.player.attack


def records(world, event):
    return [entry for entry in world.history.records if entry["event"] == event]


@pytest.mark.parametrize("key,stat,expected", [
    ("rapid_throw", "throw_cooldown", (.238, .22, .22)),
    ("long_throw", "shuriken_range", (624, 702, 780)),
    ("lingering_echo", "echo_lifetime", (4, 4.5, 5)),
    ("parry", "parry_window", (.17, .20, .22)),
])
def test_remaining_rank_totals_and_live_values(key, stat, expected):
    rewards = RunRewards()
    for rank, result in enumerate(expected, 1):
        before, preview = rewards.preview(key)
        assert before == getattr(rewards.effective(), stat)
        assert rewards.upgrade(key)
        assert getattr(rewards.effective(), stat) == pytest.approx(result)
        assert preview == getattr(rewards.effective(), stat)
    assert not rewards.upgrade(key) and key not in rewards.eligible("technique")
    assert value_text(key, expected[-1]) == ("780 px" if key == "long_throw" else f"{expected[-1]:g} s")
    assert bonus_text(key, 3) == {"rapid_throw": "-30%", "long_throw": "+50%",
                                  "lingering_echo": "+2 s", "parry": "+0.1 s"}[key]


def test_eight_techniques_and_four_bursts_are_eligible_isolated_and_capped():
    a, b = RunRewards(random.Random(1)), RunRewards(random.Random(1))
    assert len(a.eligible("technique")) == 8 and len(a.eligible("burst")) == 4
    for key in list(a.eligible("technique")):
        for _ in range(3):
            assert a.upgrade(key)
    assert not a.eligible("technique") and b.ranks == {}
    a.stored = "flow"
    a.activate(EventBus())
    a.accept_attack("slash")
    assert b.active is None and b.flow_previous is None
    a.reset()
    assert a.effective() == b.effective()


@pytest.mark.parametrize("rank", [1, 2, 3])
def test_long_throw_freezes_range_without_speed_change_and_echo_keeps_it(rank):
    world = arena()
    world.rewards.ranks = {"long_throw": rank}
    action(world, "dash")
    star = action(world, "throw")
    copied = world.echo.projectile
    assert star.max_range == pytest.approx((624, 702, 780)[rank - 1])
    assert star.velocity.length() == S.SHURIKEN_SPEED and copied.velocity == star.velocity
    assert copied.owner == "echo" and copied is not star and copied.action_id == star.action_id
    world.rewards.reset()
    step(world, S.ECHO_DELAY)
    assert copied in world.projectiles and copied.max_range == star.max_range
    star.advance(10)
    assert star.travelled == star.max_range and star.expired


@pytest.mark.parametrize("rank,wait", [(1, 4), (2, 4.5), (3, 5)])
def test_lingering_changes_wait_only_and_wait_is_captured(rank, wait):
    world = arena()
    world.rewards.ranks["lingering_echo"] = rank
    step(world, commands=[Command("dash")])
    echo = world.echo
    assert echo.timer == wait
    world.rewards.reset()
    echo.tick(wait - .01)
    assert echo.state == EchoState.WAITING
    echo.queue("throw", Vector2(1, 0))
    assert echo.timer == S.ECHO_DELAY
    assert echo.tick(S.ECHO_DELAY) == "throw"
    echo.tick(S.THROW_DURATION)
    assert echo.state == EchoState.FADING and echo.timer == pytest.approx(S.ECHO_FADE_DURATION)


@pytest.mark.parametrize("rank,window", [(0, .12), (1, .17), (2, .20), (3, .22)])
def test_parry_window_preserves_angle_reach_incoming_and_wall_interception(rank, window):
    world = arena()
    if rank:
        world.rewards.ranks["parry"] = rank
    step(world, commands=[Command("slash")])
    player = world.player
    player.state_time = window - .001
    bolt = Projectile(player.position + Vector2(50, 0), Vector2(-300, 0), 1, "enemy", 1000, radius=1)
    assert player.parry_active and parry_contact(player, bolt) is not None
    bolt.velocity *= -1
    assert parry_contact(player, bolt) is None
    bolt.velocity *= -1
    bolt.position = bolt.previous = player.position + Vector2(-50, 0)
    assert parry_contact(player, bolt) is None
    bolt.position = bolt.previous = player.position + Vector2(100, 0)
    assert parry_contact(player, bolt) is None
    # A wall contacts a fast incoming shot before the enlarged-time parry can intercept.
    world.room.static_walls = [pygame.FRect(1100, 900, 10, 200)]
    world.room.refresh_gates([])
    bolt.position = bolt.previous = player.position + Vector2(200, 0)
    world.projectiles = [bolt]
    resolve_projectiles(world, .5)
    assert not world.projectiles and world.stats["deflections"] == 0
    player.state_time = window
    assert not player.parry_active


@pytest.mark.parametrize("rank", [0, 1, 2, 3])
def test_frenzy_clamps_composed_cooldowns_and_preserves_phases(rank):
    player = Player(Vector2())
    if rank:
        player.rewards.ranks = {"rapid_throw": rank, "parry": rank}
    player.rewards.stored = "frenzy"
    player.rewards.activate(EventBus())
    player.queue(Command("slash"))
    assert player.tick(S.SIMULATION_STEP, Vector2()) == "slash"
    timing = player.timing
    assert timing.phase_end == S.SLASH_ACTIVE_END
    assert timing.duration == pytest.approx(.26) and timing.cooldown == pytest.approx(.26)
    for when, active in [(.059, False), (.06, True), (.219, True), (.22, False)]:
        player.state_time = when
        assert player.damage_active == active
        assert timing.animation_time(when) == pytest.approx(when)
    assert timing.animation_time(.24) == pytest.approx(.26)
    player._start_action("throw")
    factor = (1, .85, .75, .70)[rank]
    assert player.timing.duration == pytest.approx(.14)
    assert player.cooldowns["throw"] == pytest.approx(max(.14, .28 * factor * .65))
    assert player.timing.animation_time(.06) == .06
    assert player.timing.animation_time(.10) == pytest.approx(.14)


def test_frenzy_cannot_truncate_an_extended_parry_window(monkeypatch):
    monkeypatch.setattr(S, "PARRY_WINDOW", .19)
    rewards = RunRewards()
    rewards.ranks["parry"] = 3
    rewards.stored = "frenzy"
    rewards.activate(EventBus())
    timing = rewards.effective().slash_timing
    assert timing.parry_window == pytest.approx(.29)
    assert timing.duration == pytest.approx(.295)
    monkeypatch.setattr(S, "PARRY_WINDOW", 2.)
    assert rewards.effective().slash_timing.duration == S.SLASH_DURATION
    assert rewards.effective().parry_window == S.SLASH_DURATION


def test_frenzy_action_and_echo_timing_survive_expiry():
    world = arena()
    action(world, "dash")
    step(world, .2)
    world.rewards.stored = "frenzy"
    world.rewards.activate(world.events)
    world.rewards.remaining = S.SIMULATION_STEP
    step(world, commands=[Command("slash")])
    player, echo = world.player, world.echo
    assert world.rewards.active is None and player.timing.duration == pytest.approx(.26)
    assert echo.timing == player.timing and player.cooldowns["slash"] == pytest.approx(.26)
    step(world, .25)
    assert player.state == PlayerState.ATTACKING
    step(world, .025)
    assert player.state == PlayerState.IDLE
    step(world, .1)
    assert echo.state == EchoState.ATTACKING and echo.timing.duration == pytest.approx(.26)
    # A normal action is equally stable if Frenzy is activated while it is underway.
    step(world, commands=[Command("slash")])
    assert player.timing.duration == S.SLASH_DURATION
    world.rewards.stored = "frenzy"
    step(world, commands=[Command("burst")])
    assert player.timing.duration == S.SLASH_DURATION


def test_flow_only_alternating_accepted_attacks_and_dash_is_neutral():
    world = arena()
    world.rewards.stored = "flow"
    world.rewards.activate(world.events)
    assert action(world, "slash").damage == 30
    assert action(world, "throw").damage == 28
    assert action(world, "slash").damage == 42
    assert action(world, "slash").damage == 30
    action(world, "dash")
    assert world.rewards.flow_previous == "slash"
    assert action(world, "throw").damage == 28
    transitions = [r["details"] for r in records(world, "flow_transition")]
    assert [r["earned"] for r in transitions] == [False, True, True, False, True]
    assert [r["current"] for r in transitions] == ["slash", "throw", "slash", "slash", "throw"]


def test_flow_ignores_holds_rejected_capacity_stun_and_echo_but_copies_bonus():
    world = arena()
    action(world, "dash")
    world.rewards.stored = "flow"
    world.rewards.activate(world.events)
    step(world, .1, commands=[Command("hold_slash")])
    assert world.rewards.flow_previous is None
    world.player.cancel_hold()
    first = action(world, "slash")
    assert not first.flow_bonus
    step(world, S.ECHO_DELAY)
    assert len(records(world, "flow_transition")) == 1
    action(world, "dash")
    world.projectiles = [Projectile(Vector2(4000, 3000), Vector2(), 1, "player", 1000) for _ in range(S.MAX_SHURIKEN)]
    step(world, commands=[Command("throw")])
    assert world.rewards.flow_previous == "slash"
    world.projectiles.clear()
    world.player.receive_damage(1)
    step(world, .12, commands=[Command("throw")])  # Input buffer expires during hit stun.
    assert world.rewards.flow_previous == "slash"
    star = action(world, "throw")
    copied = world.echo.projectile
    assert star.damage == copied.damage == 28 and copied.flow_bonus
    world.rewards.remaining = S.SIMULATION_STEP
    step(world)
    assert world.rewards.flow_previous is None
    step(world, S.ECHO_DELAY)
    assert copied.damage == 28 and len(records(world, "flow_transition")) == 2
    assert records(world, "echo_attack")[-1]["details"]["action_id"] == star.action_id


def test_flow_charged_sharpening_echo_hit_attribution_and_no_shared_hit_set():
    world = arena()
    world.rewards.ranks = {"sharpening": 2, "reach": 3}
    action(world, "dash")
    # Put player and Echo together so the same enemy can be hit independently.
    world.player.position = world.echo.position.copy()
    world.rewards.stored = "flow"
    world.rewards.activate(world.events)
    action(world, "throw")  # This consumes that Echo; create another without advancing Flow.
    action(world, "dash")
    step(world, .2)
    world.player.position = world.echo.position.copy()
    world.projectiles.clear()
    enemy = Enemy(99, world.player.position + Vector2(50, 0), 999, shooting=False)
    enemy.health = enemy.max_health = 1000
    world.enemies = [enemy]
    step(world, commands=[Command("slash", charge=1.)])
    captured = world.player.attack
    assert captured.damage == 105 and captured.flow_bonus
    assert captured.reach == pytest.approx(119)
    step(world, .6)
    hits = records(world, "enemy_hit")
    assert [h["details"]["owner"] for h in hits] == ["player", "echo"]
    assert all(h["details"]["action_id"] == captured.action_id and h["details"]["flow_bonus"] for h in hits)
    assert enemy.health == 790


def test_history_detaches_offer_choice_replacement_and_context_without_reroll():
    world = arena()
    world.rewards.rng.seed(8)
    chest = Cache("garden", "technique", Vector2())
    pair = chest.offer(world.rewards, world.events)
    original = records(world, "reward_offered")[0]
    assert original["kind"] == "opportunity" and original["timestamp"] == 0
    assert original["context"]["health"] == original["context"]["max_health"] == S.PLAYER_HEALTH
    effects = original["details"]["effects"]
    assert [effect["reward"] for effect in effects] == list(pair)
    assert all(effect["next_rank"] == 1 and "before" in effect and "after" in effect for effect in effects)
    for _ in range(3):
        chest.offer(world.rewards, world.events)
    assert len(records(world, "reward_offered")) == 1
    assert len(records(world, "reward_reopened")) == 3
    choice = Choice(chest, selected=0)
    assert choice.confirm(world.rewards, world.events)
    confirmed = records(world, "reward_confirmed")[0]
    assert confirmed["kind"] == "choice" and confirmed["details"]["prior"]["ranks"] == {}
    assert confirmed["details"]["offer_id"] == original["details"]["offer_id"]
    assert not choice.confirm(world.rewards, world.events)
    world.rewards.stored = "haste"
    burst = Cache("burst", "burst", Vector2(), offers=("flow", "frenzy"))
    choice = Choice(burst, selected=1)
    assert not choice.confirm(world.rewards, world.events)
    assert not choice.cancel()
    assert not choice.confirm(world.rewards, world.events)
    assert choice.confirm(world.rewards, world.events)
    replacement = records(world, "reward_confirmed")[-1]["details"]
    assert replacement["replacement"] and replacement["prior"]["stored"] == "haste"
    assert not records(world, "burst_activated")
    original["context"]["counters"]["damage"] = 999
    chest.offer_details[0]["after"] = 999
    assert records(world, "reward_offered")[0]["details"]["effects"][0]["after"] != 999
    assert records(world, "reward_offered")[0]["context"]["counters"]["damage"] == 0
    json.dumps(world.history.records, allow_nan=False)


def test_history_bounded_no_frame_dump_damage_and_completed_lifetime():
    history = RunHistory(limit=8)
    world = Sandbox(history=history)
    world.enemies.clear()
    step(world, 2.)
    assert len(history.records) == 1  # Only room entry, no 240-frame dump.
    for _ in range(12):
        action(world, "slash")
    assert len(history.records) == 8 and history.dropped == 5
    assert history.records[-1]["sequence"] == 13
    world.rewards.ranks["parry"] = 3
    deal_damage(world, world.player, 999, "bolt", "enemy")
    step(world)
    damage = records(world, "player_hit")[0]
    assert damage["details"]["owner"] == "enemy" and damage["details"]["actual_damage"] == S.PLAYER_HEALTH
    assert damage["details"]["modifiers_before"]["ranks"] == {"parry": 3}
    assert history.status == "death"
    snapshot = history.records
    step(world, 1.)
    assert history.records == snapshot
    world.retry_checkpoint()
    assert history.status == "playing" and len(history.records) == 1 and history.elapsed == 0


@pytest.mark.parametrize("owner", ["player", "echo"])
def test_successful_parry_records_owner_and_links_reflected_hit(owner):
    world = arena()
    world.rewards.ranks["parry"] = 3
    if owner == "echo":
        action(world, "dash")
    attack = action(world, "slash")
    if owner == "echo":
        step(world, S.ECHO_DELAY)
    defender = world.player if owner == "player" else world.echo
    defender.state_time = .18  # Outside the baseline window, inside Parry III.
    enemy = Enemy(99, defender.position + Vector2(110, 0), 999, shooting=False)
    world.enemies = [enemy]
    bolt = Projectile(defender.position + Vector2(65, 0), Vector2(-300, 0), 10, "enemy", 1000)
    world.projectiles = [bolt]
    resolve_projectiles(world, .01)
    entry = records(world, owner + "_parry")[0]
    assert entry["kind"] == "performance" and entry["details"]["owner"] == owner
    assert entry["details"]["action_id"] == attack.action_id
    assert entry["context"]["counters"]["deflections"] == 1
    resolve_projectiles(world, .2)
    hit = records(world, "enemy_hit")[0]["details"]
    assert hit["source"] == "reflected" and hit["owner"] == owner
    assert hit["action_id"] == attack.action_id and not hit["flow_bonus"]


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()
    result = Game("training_01", seed=3, biome="grounds", run_length=2)
    result.clock = SimpleNamespace(tick=lambda fps: 17, get_fps=lambda: 60)
    yield result
    pygame.quit()


def test_lab_actual_choice_replacement_activation_and_all_cards_render(game, monkeypatch):
    configure(game, {key: 2 for key in game.rewards.eligible("technique")}, "haste", ("flow", "frenzy"))
    def batch(events):
        monkeypatch.setattr(pygame.event, "get", lambda: events)
        game.run(frame_limit=1)
    click = lambda rect: pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    key = lambda code: pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False)
    batch([click(card_rects()[0]), click(CONFIRM_RECT)])
    assert game.choice.replacing and game.rewards.stored == "haste"
    batch([click(CANCEL_RECT)])
    batch([key(pygame.K_2), key(pygame.K_RETURN)])
    batch([key(pygame.K_RETURN)])
    assert game.choice is None and game.rewards.stored == "frenzy"
    batch([key(pygame.K_q)])
    assert game.rewards.active == "frenzy" and game.rewards.stored is None
    remaining = game.rewards.remaining
    batch([key(pygame.K_p), key(pygame.K_q)])
    assert game.rewards.remaining == remaining
    ui, labels = game.renderer.reward_ui, []
    monkeypatch.setattr(ui, "text", lambda surface, text, *args, **kwargs: labels.append(text))
    ui.details(game.screen, game.world)
    assert all(any(REWARDS[key].name in label for label in labels) for key in game.rewards.eligible("technique"))
    keys = list(REWARDS)
    for index in range(0, len(keys), 2):
        chest = Cache("preview", REWARDS[keys[index]].category, Vector2(), offers=tuple(keys[index:index+2]))
        ui.overlay(game.screen, game.world, Choice(chest, selected=0))
    assert all(key in ui.small_icons for key in REWARDS)
    assert all(record["developer"] for record in game.history.records)
    json.dumps(game.history.records)


def test_history_and_rewards_cross_levels_until_new_run(game):
    game.rewards.upgrade("rapid_throw")
    step(game.world, .1)
    history = game.history
    game.world.complete = True
    assert game.advance()
    assert game.world.history is history and game.rewards.ranks == {"rapid_throw": 1}
    entry = history.records[-1]
    assert entry["context"]["level_number"] == 2 and entry["timestamp"] == pytest.approx(.1)
    game.world.history.finish(game.world, "completed")
    completed = history.records
    game.rewards.reset()
    assert history.records == completed
    game.load("training_01")
    assert game.history is not history and len(game.history.records) == 1
    assert history.records == completed and not game.rewards.ranks


def test_renderer_uses_captured_frenzy_recovery_clock(game):
    player = game.world.player
    game.rewards.stored = "frenzy"
    game.rewards.activate(game.world.events)
    player.queue(Command("slash"))
    player.tick(S.SIMULATION_STEP, Vector2())
    player.state_time = .24
    game.rewards.reset()
    game.renderer.update(game.world, 0)
    assert game.renderer.animation.elapsed == pytest.approx(.26)
    assert player.cooldown_totals["slash"] == pytest.approx(.26)


@pytest.mark.parametrize("burst", ["smoke_veil", "haste", "frenzy", "flow"])
def test_each_burst_expires_once_after_1200_steps_and_never_reuses_slot(burst):
    world = arena()
    world.rewards.stored = burst
    step(world, commands=[Command("burst")])
    world.rewards.stored = "flow"
    step(world, 1198 / 120, commands=[Command("burst")])
    assert world.rewards.active == burst and world.rewards.stored == "flow"
    step(world)
    assert world.rewards.active is None and world.rewards.flow_previous is None
    assert len(records(world, "burst_expired")) == 1
    step(world)
    assert len(records(world, "burst_activated")) == 1 and world.rewards.stored == "flow"


def test_lab_rejects_mixed_capped_or_invalid_setup_without_mutating_run(game):
    original = game.rewards.snapshot()
    history = game.history.records
    for ranks, burst, offers in [({"reach": 4}, None, None), ({}, "missing", None),
                                 ({}, None, ("flow", "reach")), ({"parry": 3}, None, ("reach", "parry"))]:
        with pytest.raises(ValueError):
            configure(game, ranks, burst, offers)
    assert game.rewards.snapshot() == original and game.history.records == history
