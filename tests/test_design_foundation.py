"""Keep design drafts referentially sound without enabling them in the game."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from shroud.campaign import LEVEL_IDS, load_level

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads((ROOT / path).read_text())


def test_only_core_layouts_are_runtime_data():
    assert len(LEVEL_IDS) == 18
    assert {p.stem for p in (ROOT / 'data/levels').glob('*.json')} == set(LEVEL_IDS)
    assert not (ROOT / 'archive').exists()
    for level_id in LEVEL_IDS:
        raw = read(f'data/levels/{level_id}.json')
        assert 'biome' not in raw
        assert {floor[0] for floor in raw['floors']} <= {'earth', 'stone', 'mat', 'platform'}


def test_every_planned_assignment_preserves_authored_anchors_and_targets():
    plan = read('design/encounters.json')
    biomes = read('design/biomes.json')['biomes']
    enemies = read('design/enemies.json')['enemies']
    assert plan['status'] == 'design_only'
    assert [m['id'] for m in plan['maps']] == list(LEVEL_IDS)
    assert len({m['purpose'] for m in plan['maps']}) == 18
    for info in plan['maps']:
        choices = load_level(info['id']).get('choices', [])
        assert info['decision'] == (choices[0] if choices else None)
    assert {b['id'] for b in biomes} == {'grounds', 'snow', 'marsh', 'wind'}
    families = {e['id'] for e in enemies}
    assert len(families) == 5
    assert {e['id'] for e in enemies if e['playable']} == {'archer'}
    assert len({e['id'] for e in plan['encounters']}) == 144
    cells = Counter()
    for encounter in plan['encounters']:
        data = load_level(encounter['map_id'])
        assert encounter['status'] == 'planned_unvalidated'
        assert encounter['biome_id'] in {b['id'] for b in biomes}
        assert encounter['variant'] in {'isolation', 'contrast'}
        cells[encounter['map_id'], encounter['biome_id']] += 1
        assignments = encounter['assignments']
        assert [a['spawn_index'] for a in assignments] == list(range(len(data['enemies'])))
        for assignment, original in zip(assignments, data['enemies']):
            assert assignment['group'] == original[0]
            if original[4]:
                assert assignment['family'] in families
            else:
                assert assignment['family'] == 'practice_target'
    assert set(cells) == {(m, b['id']) for m in LEVEL_IDS for b in biomes}
    assert set(cells.values()) == {2}


def test_new_enemy_art_is_preserved_and_complete():
    manifest = read('assets/characters/new_enemies/manifest.json')
    assert len(manifest) == 32
    paths = set()
    for entry in manifest:
        path = ROOT / entry['path']
        paths.add(path)
        assert entry['size'] == [320, 320]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
        assert entry['original_path'].startswith('newenemies/')
    assert paths == set((ROOT / 'assets/characters/new_enemies').rglob('*.png'))
