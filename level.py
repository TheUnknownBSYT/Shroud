"""Handcrafted map data, world collision, and the scrolling camera."""
from dataclasses import dataclass
from math import ceil, exp, floor
import pygame
from pygame import Vector2
import settings as S

# Coordinates below are in floor tiles. Half a tile is the kit's 64px placement grid.
TRAINING_GROUNDS = {
    "size": (64, 40),
    "spawn": (4, 36),
    "exit": (5, 3, 2, 2),
    "floors": [
        ("earth", 1, 29, 15, 10),       # Entrance grounds
        ("stone", 16, 33, 3, 4),
        ("stone", 19, 25, 16, 14),     # Combat courtyard
        ("stone", 30, 22, 4, 3),
        ("earth", 30, 18, 6, 4),       # Fork
        ("stone", 36, 18, 14, 4),      # Direct crossing
        ("earth", 32, 12, 4, 6),       # Garden detour
        ("earth", 36, 12, 18, 4),
        ("earth", 50, 16, 4, 2),
        ("stone", 50, 18, 10, 8),      # Reunion yard
        ("stone", 54, 8, 4, 10),
        ("stone", 35, 1, 25, 7),       # Final challenge
        ("platform", 20, 3, 15, 4),
        ("earth", 3, 1, 17, 8),        # Exit garden
        ("platform", 3, 35, 3, 3),
        ("mat", 23, 29, 3, 3),
        ("mat", 28, 33, 3, 3),
        ("mat", 39, 3, 3, 3),
        ("mat", 51, 3, 3, 3),
    ],
    "areas": [
        ("Entrance grounds", (1, 29, 18, 10), "Follow the stone path to the courtyard"),
        ("Combat courtyard", (19, 22, 16, 17), "Clear the courtyard to open the north gate"),
        ("Training paths", (30, 12, 24, 10), "Find a way to the upper yard"),
        ("North approach", (50, 8, 10, 18), "Continue north to the final challenge"),
        ("Final challenge", (35, 1, 25, 7), "Clear the final yard, then head west"),
        ("Exit garden", (3, 1, 32, 8), "Reach the lantern gate to finish"),
    ],
    # asset, center x/y, rotation. Shapes live in SOLID_SHAPES, not in the image bounds.
    "props": [
        ("gate", 4.5, 35, 0), ("banner", 3, 35, 0), ("lantern", 6, 35, 0),
        ("weapon_rack", 3, 30.5, 0), ("crate", 8, 34, 0), ("crate", 9, 34, 0),
        ("rock_01", 11, 32, 0), ("rock_02", 12, 32, 0), ("tree", 14.5, 37, 0),
        ("tree", 2.5, 32, 0), ("post", 13, 35, 0), ("post", 13, 36, 0),
        ("banner", 16, 33.5, 0), ("lantern", 18.5, 36, 0),
        ("pillar", 23, 27.5, 0), ("pillar", 29, 27.5, 0),
        ("crate", 26, 32, 0), ("crate", 27, 32, 0),
        ("low_wall", 32, 35, 90), ("low_wall", 32, 36, 90),
        ("weapon_rack", 20.5, 37.5, 0), ("banner", 33.5, 26, 0),
        ("gate", 32, 25, 0), ("pillar", 30.5, 25, 0), ("pillar", 33.5, 25, 0),
        ("lantern", 31, 22.5, 0), ("lantern", 33, 22.5, 0),
        ("tree", 30.8, 19, 0), ("banner", 35, 20.5, 0),
        ("crate", 38.5, 19, 0), ("crate", 45, 21, 0),
        ("pillar", 42, 18.7, 0), ("pillar", 48, 20.8, 0),
        ("tree", 32.7, 16, 0), ("rock_01", 34.7, 14.5, 0),
        ("tree", 37, 12.8, 0), ("low_wall", 39, 14.5, 90),
        ("low_wall", 39, 15.5, 90), ("crate", 43, 12.7, 0),
        ("tree", 46, 15, 0), ("rock_02", 49, 13, 0),
        ("weapon_rack", 52.8, 12.8, 0), ("lantern", 52, 17, 0),
        ("crate", 54, 23, 0), ("crate", 55, 23, 0), ("pillar", 58, 21, 0),
        ("gate", 56, 10, 0), ("lantern", 54.5, 11, 0), ("banner", 57.5, 9, 0),
        ("pillar", 56, 6, 0), ("pillar", 50, 4, 0), ("pillar", 45, 6, 0),
        ("crate", 48, 2.5, 0), ("crate", 49, 2.5, 0),
        ("low_wall", 42, 4, 90), ("low_wall", 42, 5, 90),
        ("weapon_rack", 37, 2, 0), ("banner", 36, 6.5, 0),
        ("gate", 35, 5, 90), ("lantern", 34, 3.5, 0),
        ("lantern", 29, 4, 0), ("lantern", 25, 6, 0), ("banner", 21, 4, 0),
        ("tree", 17, 3, 0), ("tree", 12, 6.5, 0), ("rock_01", 10, 3, 0),
        ("gate", 6, 4, 0), ("lantern", 4.5, 4, 0), ("lantern", 7.5, 4, 0),
    ],
    "decorations": [
        ("practice_mark", 10, 36, 0), ("leaf_scatter", 14, 36, 0),
        ("grass", 2, 38, 0), ("grass", 14, 30, 0), ("rope", 5, 30.5, 0),
        ("practice_mark", 24.5, 30.5, 0), ("practice_mark", 29.5, 34.5, 0),
        ("grass", 31, 21, 0), ("leaf_scatter", 34, 17, 0),
        ("grass", 36.5, 15.5, 0), ("leaf_scatter", 41, 13, 0),
        ("shrub", 47, 12.7, 0), ("leaf_scatter", 51, 15, 0),
        ("practice_mark", 41, 20, 0), ("practice_mark", 47, 20, 0),
        ("practice_mark", 52.5, 4.5, 0), ("practice_mark", 40.5, 4.5, 0),
        ("grass", 18, 7, 0), ("leaf_scatter", 13, 3, 0), ("grass", 4, 7, 0),
    ],
    # group, sprite, x/y, shoots. All use the existing Enemy combat state machine.
    "enemies": [
        ("entrance", "target", 11, 36, False),
        ("courtyard", "target", 24.5, 30.5, False),
        ("courtyard", "straw_dummy", 29.5, 34.5, False),
        ("courtyard", "sentry", 22, 27, True),
        ("courtyard", "sentry", 31, 29, True),
        ("courtyard", "sentry", 29, 37, True),
        ("crossing", "sentry", 40.5, 20, True),
        ("crossing", "sentry", 44, 19, True),
        ("crossing", "sentry", 48.5, 20, True),
        ("garden", "sentry", 42, 14, True),
        ("garden", "stationary_target", 52, 14, False),
        ("approach", "sentry", 57, 23, True),
        ("final", "sentry", 57.5, 3.5, True),
        ("final", "sentry", 52.5, 4.5, True),
        ("final", "sentry", 47, 5.5, True),
        ("final", "sentry", 40.5, 4.5, True),
        ("final", "sword_dummy", 37.5, 5.5, False),
    ],
    "gates": [("courtyard", (30, 24.875, 4, .25)), ("final", (34.875, 3, .25, 4))],
    "signs": [("COURTYARD  >", 15, 34), ("UPPER YARD  ^", 56, 18), ("EXIT  <", 36, 4)],
}

# Source-pixel rectangles. A tree blocks at its trunk; leaves and markings do not block.
SOLID_SHAPES = {
    "crate": [(20, 26, 88, 68)], "pillar": [(10, 12, 44, 42)],
    "post": [(20, 20, 24, 24)], "tree": [(55, 82, 18, 28)],
    "rock_01": [(30, 52, 68, 34)], "rock_02": [(38, 51, 54, 29)],
    "wall": [(0, 16, 128, 32)], "low_wall": [(0, 28, 128, 32)],
    "fence": [(0, 10, 128, 34)], "weapon_rack": [(12, 76, 104, 28)],
    "gate": [(8, 36, 20, 72), (228, 36, 20, 72)],
}
ASSET_SIZES = {"gate": (256, 128), "pillar": (64, 64), "post": (64, 64),
               "lantern": (64, 64), "wall": (128, 64), "low_wall": (128, 64),
               "fence": (128, 64)}


@dataclass
class Prop:
    asset: str
    position: Vector2
    angle: int = 0

    @property
    def rect(self):
        width, height = ASSET_SIZES.get(self.asset, (128, 128))
        if self.angle % 180:
            width, height = height, width
        rect = pygame.FRect(0, 0, width * S.ENVIRONMENT_SCALE, height * S.ENVIRONMENT_SCALE)
        rect.center = self.position
        return rect

    def colliders(self):
        width, height = ASSET_SIZES.get(self.asset, (128, 128))
        result = []
        for shape in SOLID_SHAPES.get(self.asset, []):
            rect = pygame.FRect(shape)
            offset = (Vector2(rect.center) - Vector2(width / 2, height / 2)) * S.ENVIRONMENT_SCALE
            size = Vector2(rect.size) * S.ENVIRONMENT_SCALE
            if self.angle % 180:
                size = Vector2(size.y, size.x)
            body = pygame.FRect(0, 0, *size)
            body.center = self.position + offset.rotate(-self.angle)
            result.append(body)
        return result


class Camera:
    def __init__(self, bounds, viewport=None):
        self.bounds = pygame.FRect(bounds)
        self.viewport = pygame.FRect(viewport or S.WORLD_VIEW)
        self.offset = Vector2()

    def follow(self, position, dt, snap=False):
        target = position - Vector2(self.viewport.size) / 2
        maximum = Vector2(max(self.bounds.left, self.bounds.right - self.viewport.width),
                          max(self.bounds.top, self.bounds.bottom - self.viewport.height))
        target.x = max(self.bounds.left, min(maximum.x, target.x))
        target.y = max(self.bounds.top, min(maximum.y, target.y))
        self.offset = target if snap else self.offset.lerp(target, 1 - exp(-S.CAMERA_RESPONSE * dt))
        self.offset.x = max(self.bounds.left, min(maximum.x, self.offset.x))
        self.offset.y = max(self.bounds.top, min(maximum.y, self.offset.y))

    def world_to_screen(self, position):
        return Vector2(position) - self.offset + Vector2(self.viewport.topleft)

    def screen_to_world(self, position):
        return Vector2(position) + self.offset - Vector2(self.viewport.topleft)

    @property
    def visible_rect(self):
        return pygame.FRect(self.offset, self.viewport.size)


class Room:
    def __init__(self, data=None):
        self.data = data
        self.tiles = {}
        self.props = []
        self.decorations = []
        self.gates = []
        self.open_gates = set()
        if data is None:
            # The original tiny arena remains a fixture for the existing combat tests.
            self.bounds = pygame.FRect(48, 140, S.WIDTH - 96, S.HEIGHT - 218)
            self.walls = [pygame.FRect(440, 295, 58, 112), pygame.FRect(744, 465, 58, 112)]
            self.spawn = Vector2(250, 435)
            self.enemy_spawns = [Vector2(880, 300), Vector2(1030, 505), Vector2(550, 605)]
        else:
            self._build(data)
        self.static_walls = list(self.walls)
        self.refresh_gates([])

    def _build(self, data):
        tile = S.TILE_SIZE
        self.bounds = pygame.FRect(0, 0, data["size"][0] * tile, data["size"][1] * tile)
        self.spawn = Vector2(data["spawn"]) * tile
        self.exit_rect = pygame.FRect(*(value * tile for value in data["exit"]))
        for material, x, y, width, height in data["floors"]:
            for row in range(y, y + height):
                for column in range(x, x + width):
                    if material in ("earth", "stone"):
                        asset = f"floor_{material}_0{1 + (column + row) % 2}"
                    else:
                        asset = material
                    self.tiles[column, row] = asset
        for name in ("props", "decorations"):
            setattr(self, name, [Prop(asset, Vector2(x, y) * tile, angle)
                                for asset, x, y, angle in data[name]])
        # Only exposed tile edges get walls; adjacent floor rectangles stay connected.
        for x, y in self.tiles:
            for dx, dy, angle in ((0, -1, 0), (0, 1, 0), (-1, 0, 90), (1, 0, 90)):
                if (x + dx, y + dy) not in self.tiles:
                    center = Vector2(x + .5 + dx / 2, y + .5 + dy / 2) * tile
                    self.props.append(Prop("wall", center, angle))
        self.walls = []
        for prop in self.props:
            self.walls.extend(prop.colliders())
        self.enemy_spawns = [Vector2(x, y) * tile for _, _, x, y, _ in data["enemies"]]
        self.gates = [(name, pygame.FRect(*(value * tile for value in rect)))
                      for name, rect in data["gates"]]

    def refresh_gates(self, enemies):
        if enemies:
            self.open_gates = {name for name, _ in self.gates
                               if not any(e.alive and e.group == name for e in enemies)}
        self.walls = self.static_walls + [rect for name, rect in self.gates if name not in self.open_gates]
        self.collision_cells = {}
        for index, wall in enumerate(self.walls):
            for cell in self._cells(wall):
                self.collision_cells.setdefault(cell, []).append(index)

    @staticmethod
    def _cells(rect):
        size = S.TILE_SIZE * 2
        for y in range(floor(rect.top / size), floor(rect.bottom / size) + 1):
            for x in range(floor(rect.left / size), floor(rect.right / size) + 1):
                yield x, y

    def walls_near(self, rect):
        indices = set()
        for cell in self._cells(rect):
            indices.update(self.collision_cells.get(cell, []))
        return [self.walls[index] for index in sorted(indices)]

    def move(self, position, displacement, radius):
        steps = max(1, ceil(displacement.length() / max(radius * .5, 1)))
        step = displacement / steps
        result = position.copy()
        for _ in range(steps):
            for axis in (0, 1):
                result[axis] += step[axis]
                body = pygame.FRect(result.x - radius, result.y - radius, radius * 2, radius * 2)
                for wall in self.walls_near(body):
                    if body.colliderect(wall):
                        if step[axis] > 0:
                            result[axis] = (wall.left if axis == 0 else wall.top) - radius
                        elif step[axis] < 0:
                            result[axis] = (wall.right if axis == 0 else wall.bottom) + radius
                        body.center = result
                result.x = max(self.bounds.left + radius, min(self.bounds.right - radius, result.x))
                result.y = max(self.bounds.top + radius, min(self.bounds.bottom - radius, result.y))
        return result

    def projectile_blocked(self, start, end, radius):
        if not self.bounds.inflate(-radius * 2, -radius * 2).collidepoint(end):
            return True
        area = pygame.FRect(min(start.x, end.x), min(start.y, end.y),
                            abs(end.x - start.x), abs(end.y - start.y)).inflate(radius * 2 + 2, radius * 2 + 2)
        return any(wall.inflate(radius * 2, radius * 2).clipline(start, end) for wall in self.walls_near(area))

    def area_at(self, position):
        if self.data:
            for name, rect, objective in self.data["areas"]:
                area = pygame.FRect(*(value * S.TILE_SIZE for value in rect))
                if area.collidepoint(position):
                    return name, objective
        return "Training grounds", "Follow the path"
