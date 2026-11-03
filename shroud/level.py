"""Interpret authored maps, resolve world collision, and follow with a scrolling camera."""
from dataclasses import dataclass
from math import ceil, exp, floor
import pygame
from pygame import Vector2
from shroud import settings as S
from shroud.assets import CATALOG, PALETTES, BIOME_THEMES, floor_asset
from shroud.combat import segment_rect

# One authoritative catalogue: source canvas sizes and base-only collision shapes.
ASSET_SIZES = {name: tuple(info["size"]) for name, info in CATALOG.items()}
SOLID_SHAPES = {name: info["solids"] for name, info in CATALOG.items()}


@dataclass
class Prop:
    asset: str
    position: Vector2
    angle: int = 0
    collision_asset: str | None = None

    @property
    def rect(self):
        width, height = ASSET_SIZES.get(self.asset, (128, 128))
        if self.angle % 180:
            width, height = height, width
        rect = pygame.FRect(0, 0, width * S.ENVIRONMENT_SCALE, height * S.ENVIRONMENT_SCALE)
        rect.center = self.position
        return rect

    def colliders(self):
        source = self.collision_asset or self.asset
        width, height = ASSET_SIZES.get(source, (128, 128))
        result = []
        for shape in SOLID_SHAPES.get(source, []):
            rect = pygame.FRect(shape)
            offset = (Vector2(rect.center) - Vector2(width / 2, height / 2)) * S.ENVIRONMENT_SCALE
            size = Vector2(rect.size) * S.ENVIRONMENT_SCALE
            if self.angle % 180:
                size = Vector2(size.y, size.x)
            body = pygame.FRect(0, 0, *size)
            body.center = self.position + offset.rotate(-self.angle)
            result.append(body)
        return result


@dataclass
class BambooScreen:

    position: Vector2
    broken: bool = False
    shots_taken: int = 0

    @property
    def prop(self):
        asset = "bamboo_cut" if self.broken else "bamboo_cluster"
        # Align the cluster's source-space base (y=104) with its ground anchor.
        return Prop(asset, self.position - Vector2(0, 40 * S.ENVIRONMENT_SCALE))

    def _shape(self, key):
        x, y, width, height = CATALOG["bamboo_cluster"][key]
        return pygame.FRect(self.prop.position.x + (x - 64) * S.ENVIRONMENT_SCALE,
                            self.prop.position.y + (y - 64) * S.ENVIRONMENT_SCALE,
                            width * S.ENVIRONMENT_SCALE, height * S.ENVIRONMENT_SCALE)

    @property
    def hitbox(self):
        """Shots hit the visible cluster, including stems above its ground footprint."""
        return self._shape("projectile_shape")

    @property
    def footprint(self):
        return self._shape("footprint_shape")


def bamboo_positions(data):
    """Expand authored axis-aligned walls into touching clusters, without random placement."""
    points = [tuple(point) for point in data.get("bamboo_screens", [])]
    shape = CATALOG["bamboo_cluster"]["footprint_shape"]
    for wall in data.get("bamboo_walls", []):
        start, end = Vector2(wall["start"]), Vector2(wall["end"])
        delta = end - start
        if delta.x and delta.y:
            raise ValueError("Bamboo walls must be horizontal or vertical")
        axis = 0 if delta.x else 1
        spacing = shape[2 + axis] * S.ENVIRONMENT_SCALE / S.TILE_SIZE
        steps = ceil(abs(delta[axis]) / spacing)
        points.extend(tuple(start.lerp(end, i / steps)) if steps else tuple(start)
                      for i in range(steps + 1))
    # Shared endpoints in adjoining walls are one cluster, not stacked hit points.
    return [Vector2(point) * S.TILE_SIZE for point in dict.fromkeys(points)]


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
        self.biome = data.get("biome", "grounds") if data else "grounds"
        self.theme = BIOME_THEMES[self.biome]
        self.palette = PALETTES[self.theme]
        self.tiles = {}
        self.props = []
        self.decorations = []
        self.bamboo = []
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
                    self.tiles[column, row] = floor_asset(self.theme, material, column, row)
        for name in ("props", "decorations"):
            setattr(self, name, [Prop(asset, Vector2(x, y) * tile, angle)
                                for asset, x, y, angle in data[name]])
        # Only exposed tile edges get walls; adjacent floor rectangles stay connected.
        for x, y in self.tiles:
            for dx, dy, angle in ((0, -1, 0), (0, 1, 0), (-1, 0, 90), (1, 0, 90)):
                if (x + dx, y + dy) not in self.tiles:
                    center = Vector2(x + .5 + dx / 2, y + .5 + dy / 2) * tile
                    self.props.append(Prop(self.palette["wall"], center, angle,
                                           PALETTES[data.get("layout_style", "training")]["wall"]))
                    if self.biome == "bamboo" and (x * 7 + y * 11) % 4 == 0:
                        # Decorative stems stay outside walkable cells; screens are authored below.
                        outside = center + Vector2(dx, dy) * tile * .65
                        self.decorations.append(Prop("bamboo_stem", outside))
                        self.decorations.append(Prop("bamboo_canopy", outside - Vector2(0, tile * .35)))
        self.walls = []
        for prop in self.props:
            self.walls.extend(prop.colliders())
        self.enemy_spawns = [Vector2(x, y) * tile for _, _, x, y, _ in data["enemies"]]
        self.gates = [(name, pygame.FRect(*(value * tile for value in rect)))
                      for name, rect in data["gates"]]
        if self.biome == "bamboo":
            self.bamboo = [BambooScreen(point) for point in bamboo_positions(data)]

    def refresh_gates(self, enemies):
        if enemies:
            self.open_gates = {name for name, _ in self.gates
                               if not any(e.alive and e.group == name for e in enemies)}
        self.walls = self.static_walls + [rect for name, rect in self.gates if name not in self.open_gates]
        self.collision_cells = {}
        for index, wall in enumerate(self.walls):
            for cell in self._cells(wall):
                self.collision_cells.setdefault(cell, []).append(index)

    @property
    def gates_cleared(self):
        return all(name in self.open_gates for name, _ in self.gates)

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

    def movement_walls_near(self, rect):
        walls = self.walls_near(rect)
        for cover in self.bamboo:
            if not cover.broken:
                footprint = cover.footprint
                if rect.colliderect(footprint):
                    walls.append(footprint)
        return walls

    def movement_blocked(self, start, end, radius):
        """Authoring clearance uses the same intact bamboo footprints as actual movement."""
        if self.projectile_blocked(start, end, radius):
            return True
        return any(not cover.broken and segment_rect(start, end, cover.footprint.inflate(radius * 2, radius * 2)) is not None
                   for cover in self.bamboo)

    def move(self, position, displacement, radius):
        steps = max(1, ceil(displacement.length() / max(radius * .5, 1)))
        step = displacement / steps
        result = position.copy()
        for _ in range(steps):
            for axis in (0, 1):
                result[axis] += step[axis]
                body = pygame.FRect(result.x - radius, result.y - radius, radius * 2, radius * 2)
                for wall in self.movement_walls_near(body):
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
        """Static obstruction for sight and melee; bamboo is see-through."""
        if not self.bounds.inflate(-radius * 2, -radius * 2).collidepoint(end):
            return True
        area = pygame.FRect(min(start.x, end.x), min(start.y, end.y),
                            abs(end.x - start.x), abs(end.y - start.y)).inflate(radius * 2 + 2, radius * 2 + 2)
        return any(wall.inflate(radius * 2, radius * 2).clipline(start, end) for wall in self.walls_near(area))

    def projectile_contact(self, start, end, radius):
        """Nearest shot obstruction as (fraction, bamboo or None); walls win ties."""
        allowed = self.bounds.inflate(-radius * 2, -radius * 2)
        nearest = None
        if not allowed.collidepoint(start):
            nearest = (0.0, None)
        elif not allowed.collidepoint(end):
            delta = end - start
            exits = []
            for axis, low, high in ((0, allowed.left, allowed.right), (1, allowed.top, allowed.bottom)):
                if delta[axis]:
                    exits.append(((high if delta[axis] > 0 else low) - start[axis]) / delta[axis])
            # FRect containment rounds to float32; Vector2 keeps double precision.
            nearest = (max(0.0, min(1.0, min(exits))), None)
        area = pygame.FRect(min(start.x, end.x), min(start.y, end.y),
                            abs(end.x - start.x), abs(end.y - start.y)).inflate(radius * 2 + 2, radius * 2 + 2)
        for wall in self.walls_near(area):
            contact = segment_rect(start, end, wall.inflate(radius * 2, radius * 2))
            if contact is not None and (nearest is None or contact < nearest[0]):
                nearest = (contact, None)
        for screen in self.bamboo:
            if screen.broken:
                continue
            contact = segment_rect(start, end, screen.hitbox.inflate(radius * 2, radius * 2))
            if contact is not None and (nearest is None or contact < nearest[0]):
                nearest = (contact, screen)
        return nearest

    def area_at(self, position):
        if self.data:
            for name, rect, objective in self.data["areas"]:
                area = pygame.FRect(*(value * S.TILE_SIZE for value in rect))
                if area.collidepoint(position):
                    return name, objective
        if self.data:
            return self.data["name"], "Clear gold-marked seal targets; TAB shows paths and exit."
        return "Training grounds", "Follow the path"
