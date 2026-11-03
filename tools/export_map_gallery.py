"""Export actual authored geometry and editorial intent; never execute planned mechanics.

Run from the project root: .venv/bin/python -m tools.export_map_gallery
"""
import json
import os
from pathlib import Path
import textwrap

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame
from shroud.assets import asset_path, BIOME_NAMES
from shroud.campaign import LEVEL_IDS, BIOME_IDS, load_level
from shroud.level import Room
from shroud import settings as S

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'local' / 'map_gallery'
INK = (16, 25, 32)
TEXT = (229, 235, 232)
ACCENT = (133, 224, 196)


def paragraph(surface, text, x, y, width=41, size=25, color=TEXT):
    """Draw wrapped editorial text; return the next free vertical coordinate."""
    font = pygame.font.Font(None, size)
    for line in textwrap.wrap(text, width):
        surface.blit(font.render(line, True, color), (x, y))
        y += size + 4
    return y + 12


def map_image(data, extent=(1090, 1030)):
    """Paint tiles and props at proportional scale, then expose authored gameplay markers."""
    room = Room(data)
    scale = min(extent[0] / room.bounds.width, extent[1] / room.bounds.height)
    canvas = pygame.Surface(extent)
    canvas.fill((28, 41, 46))
    origin = pygame.Vector2((extent[0] - room.bounds.width * scale) / 2,
                            (extent[1] - room.bounds.height * scale) / 2)
    cache = {}

    def point(position):
        return pygame.Vector2(position) * scale + origin

    def art(name, position, factor, angle=0):
        key = name, factor, angle
        if key not in cache:
            raw = pygame.image.load(asset_path(name))
            size = tuple(max(1, round(v * factor * scale)) for v in raw.get_size())
            cache[key] = pygame.transform.rotate(pygame.transform.smoothscale(raw, size), angle)
        sprite = cache[key]
        canvas.blit(sprite, sprite.get_rect(center=point(position)))

    def box(rect, color, width=2):
        pygame.draw.rect(canvas, color, pygame.Rect(*point(rect.topleft),
                         max(2, rect.width * scale), max(2, rect.height * scale)), width)

    def marker(position, label, color):
        pos = point(position)
        pygame.draw.circle(canvas, INK, pos, 12)
        pygame.draw.circle(canvas, color, pos, 12, 2)
        image = pygame.font.Font(None, 20).render(str(label), True, color)
        canvas.blit(image, image.get_rect(center=pos))

    for (x, y), name in room.tiles.items():
        art(name, ((x + .5) * S.TILE_SIZE, (y + .5) * S.TILE_SIZE), S.ENVIRONMENT_SCALE)
    for prop in room.decorations + sorted(room.props, key=lambda p: p.position.y):
        art(prop.asset, prop.position, S.ENVIRONMENT_SCALE, prop.angle)
    for cover in room.bamboo:
        art(cover.prop.asset, cover.prop.position, S.ENVIRONMENT_SCALE)
        pygame.draw.circle(canvas, (177, 223, 127), point(cover.position), 6, 1)
    for i, (_, asset, x, y, active) in enumerate(data['enemies']):
        art(asset, (x * S.TILE_SIZE, y * S.TILE_SIZE), S.SPRITE_SIZE / 320)
        marker((x * S.TILE_SIZE, y * S.TILE_SIZE), i + 1, (244, 148, 135) if active else (183, 188, 196))
    for i, choice in enumerate(data.get('choices', [])):
        for j, branch in enumerate(choice['branches']):
            rect = pygame.FRect(*(v * S.TILE_SIZE for v in branch))
            box(rect, (212, 185, 108), 1)
            marker(rect.center, chr(65 + i * 2 + j), (242, 211, 123))
    for name, gate in room.gates:
        box(gate, (241, 158, 83), 4)
    box(room.exit_rect, ACCENT, 3)
    marker(room.spawn, 'S', ACCENT)
    marker(room.exit_rect.center, 'E', ACCENT)
    for checkpoint in data.get('checkpoints', []):
        marker(pygame.Vector2(checkpoint['spawn']) * S.TILE_SIZE, 'R', (133, 186, 255))
    return canvas


def export():
    """Rebuild map sheets, all 90 biome previews, an overview and enemy pose sheets."""
    pygame.font.init()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'maps').mkdir(exist_ok=True)
    (OUT / 'enemies').mkdir(exist_ok=True)
    plan = json.loads((ROOT / 'design/encounters.json').read_text())
    assert [m['id'] for m in plan['maps']] == list(LEVEL_IDS)
    overview = pygame.Surface((1800, 2100))
    overview.fill(INK)
    paragraph(overview, 'SHROUD / 18 PURPOSEFUL LAYOUTS', 36, 22, 90, 42)
    paragraph(overview, 'Actual layouts / example biome skins. Every layout supports all five biomes.', 36, 73, 120, 24)
    for index, info in enumerate(plan['maps']):
        data = load_level(info['id'], BIOME_IDS[index % len(BIOME_IDS)])
        sheet = pygame.Surface((1680, 1280))
        sheet.fill(INK)
        paragraph(sheet, f'{index + 1:02} / {data["name"]}', 40, 28, 85, 46)
        paragraph(sheet, f'{info["id"]}  |  {data["size"][0]} x {data["size"][1]} tiles  |  example biome: {BIOME_NAMES[data["biome"]]}', 42, 85, 120, 25, ACCENT)
        sheet.blit(map_image(data), (30, 140))
        y = paragraph(sheet, 'DESIGN PURPOSE', 1150, 150, 36, 26, ACCENT)
        y = paragraph(sheet, info['purpose'], 1150, y, 34, 30)
        y = paragraph(sheet, info['reason'], 1150, y, 39, 25)
        y = paragraph(sheet, 'FUTURE OBSERVATION', 1150, y + 10, 38, 26, ACCENT)
        y = paragraph(sheet, info['primary_measure'] + ': ' + info['confound'], 1150, y, 39, 25)
        y = paragraph(sheet, 'BIOMES / FUTURE RULES', 1150, y + 10, 38, 26, ACCENT)
        y = paragraph(sheet, 'Grounds: normal. Bamboo: breakable cover on three pilots. Planned: snow braking, marsh visibility, crosswind projectiles.', 1150, y, 39, 25)
        y = paragraph(sheet, 'ENCOUNTER STUDY', 1150, y + 10, 38, 26, ACCENT)
        contrast = next(e for e in plan['encounters'] if e['map_id'] == info['id'] and e['variant'] == 'contrast')
        families = sorted({a['family'] for a in contrast['assignments'] if a['family'] != 'practice_target'})
        y = paragraph(sheet, 'Isolation: ' + info['base_families'][0] + '. Contrast: ' + ' + '.join(families) + '. New AI and snow/marsh/wind effects are planned.', 1150, y, 39, 25)
        paragraph(sheet, 'S spawn / E exit / R refuge / numbered enemy anchors / orange gates / A-B routes / green rings: bamboo cover', 40, 1190, 130, 25)
        paragraph(sheet, 'Route regions are authoring alternatives, not a prescribed path. Full art bounds are not collision bounds.', 40, 1225, 135, 23, (161, 180, 183))
        pygame.image.save(sheet, OUT / 'maps' / f'{info["id"]}.png')
        variants = OUT / 'variants' / info['id']
        variants.mkdir(parents=True, exist_ok=True)
        for biome in BIOME_IDS:
            preview = pygame.Surface((1090, 1090)); preview.fill(INK)
            paragraph(preview, f'{data["name"]} / {BIOME_NAMES[biome]}', 20, 15, 90, 30)
            preview.blit(map_image(load_level(info['id'], biome)), (0, 60))
            pygame.image.save(preview, variants / f'{biome}.png')
        x, y = 30 + (index % 3) * 590, 125 + (index // 3) * 325
        overview.blit(map_image(data, (555, 260)), (x, y))
        paragraph(overview, f'{index + 1:02} {data["name"]}', x, y + 265, 48, 24)
        paragraph(overview, info['purpose'], x, y + 290, 52, 21, ACCENT)
    pygame.image.save(overview, OUT / 'overview.png')
    for family in ('chain', 'bell', 'iron', 'thorn'):
        sheet = pygame.Surface((1400, 800)); sheet.fill(INK)
        paragraph(sheet, family.upper() + ' / SOURCE POSES', 30, 20, 70, 36)
        paragraph(sheet, 'Filename order only. Generic states are unconfirmed; these are not playable animations.', 30, 65, 120, 23)
        for index, file in enumerate(sorted((ROOT / 'assets/characters/new_enemies' / family).glob('*.png'))):
            x, y = 25 + index % 4 * 345, 110 + index // 4 * 340
            sheet.blit(pygame.image.load(file), (x, y))
            paragraph(sheet, file.stem.replace('enemy_chain_duelist_', ''), x, y + 290, 32, 21)
        pygame.image.save(sheet, OUT / 'enemies' / f'{family}.png')
    pygame.quit()
    print('Exported 18 map sheets, 90 biome previews, overview and 4 enemy contact sheets into local/map_gallery/.')


if __name__ == '__main__':
    export()
