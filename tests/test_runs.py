"""Finite run progression and independent biome presentation with real clearance."""
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest
from shroud import settings as S
from shroud.campaign import Run, LEVEL_IDS, BIOME_IDS, load_level
from shroud.game import Game
from shroud.level import Room
from shroud.level_validation import validate_level
from shroud.player import Command, InputFrame


def test_seeded_runs_have_fixed_length_without_repeated_layouts():
    a, b = Run(rng=random.Random(12)), Run(rng=random.Random(12))
    assert len(a.level_ids) == len(set(a.level_ids)) == S.RUN_LENGTH == 5
    assert a.level_ids == b.level_ids
    assert [a.load_current()['biome'] for _ in range(12)] == [b.load_current()['biome'] for _ in range(12)]
    assert set(a.level_ids) <= set(LEVEL_IDS)
    assert Run(18, rng=random.Random(1)).level_ids != Run(18, rng=random.Random(12)).level_ids


@pytest.mark.parametrize('length', [1, 5, 18])
def test_selected_start_uses_one_slot_and_randomizes_the_rest(length):
    run = Run(length, first='snow_01', rng=random.Random(8))
    assert run.current == 'snow_01'
    assert len(run.level_ids) == len(set(run.level_ids)) == length
    for index, layout in enumerate(run.level_ids):
        run.index = index
        assert run.current == layout
        assert run.following == (run.level_ids[index + 1] if index + 1 < length else None)


@pytest.mark.parametrize('length', [0, -1, 19])
def test_invalid_lengths_fail_before_any_level_load(length):
    with pytest.raises(ValueError, match='Run length'):
        Run(length)


def test_unknown_layouts_and_biomes_are_rejected():
    with pytest.raises(ValueError):
        Run(first='../main')
    with pytest.raises(ValueError):
        load_level('snow_01', biome='unknown')
    with pytest.raises(ValueError):
        load_level('training_02')


def test_biome_is_rolled_on_each_load_without_mutating_source():
    class Predictable(random.Random):
        def __init__(self):
            super().__init__(4)
            self.conditions = iter(BIOME_IDS)
        def choice(self, sequence):
            return next(self.conditions)
    run = Run(first='snow_01', rng=Predictable())
    for biome in BIOME_IDS:
        assert run.load_current()['biome'] == biome
    assert run.index == 0 and run.current == 'snow_01'
    assert load_level('snow_01')['biome'] == 'grounds'
    raw = json.loads((Path(__file__).parents[1] / 'data/levels/snow_01.json').read_text())
    assert 'biome' not in raw


@pytest.mark.parametrize('level_id', LEVEL_IDS)
@pytest.mark.parametrize('biome', BIOME_IDS)
def test_all_layout_biome_pairs_keep_routes_and_collision(level_id, biome):
    data = load_level(level_id, biome)
    room, control = Room(data), Room(load_level(level_id))
    assert room.biome == biome
    assert set(room.tiles) == set(control.tiles)
    assert room.static_walls == control.static_walls
    assert room.gates == control.gates
    assert validate_level(data) == []


def test_game_finishes_exactly_five_levels_and_restart_keeps_slot(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    pygame.display.init()
    pygame.font.init()
    try:
        game = Game(seed=42)
        planned = game.run_state.level_ids
        seen = []
        for index, layout in enumerate(planned):
            assert game.world.room.data['id'] == layout
            assert game.world.run_position == index + 1
            assert game.world.run_length == 5
            assert not game.advance()
            seen.append(layout)
            game.renderer.draw(game.screen, game.world, False, 60, False)
            game.world.complete = True
            game.renderer.draw(game.screen, game.world, False, 60, False)
            assert game.advance() == (index < 4)
        assert len(seen) == len(set(seen)) == 5
        final = game.world
        assert not game.advance() and game.world is final
        # R reloads the final run slot with a new biome draw, without extending the run.
        game.clock = SimpleNamespace(tick=lambda fps: 9, get_fps=lambda: 60)
        game.input = SimpleNamespace(read=lambda *args: InputFrame(commands=[Command('reset')]), cancel_space=lambda: None)
        monkeypatch.setattr(pygame.event, 'get', lambda: [])
        game.run(frame_limit=1)
        assert game.world is not final and not game.world.complete
        assert game.run_state.level_ids == planned and game.run_state.index == 4
        assert game.world.run_position == game.world.run_length == 5
        game.load('snow_01')
        assert game.run_state.index == 0 and game.world.run_position == 1
        assert game.world.room.data['id'] == 'snow_01'
        assert len(game.run_state.level_ids) == 5
    finally:
        pygame.quit()
