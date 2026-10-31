"""Offline authoring checks using the game's real swept collision. Never imported by play."""
from collections import deque
import pygame
from pygame import Vector2
from shroud import settings as S
from shroud.assets import CATALOG, asset_path
from shroud.campaign import LEVEL_IDS, load_level
from shroud.level import Room

SPACING = S.TILE_SIZE / 2


def reachable(room, start, excluded=None):
    """Flood half-tile nodes with player clearance; return parents for reconstructing routes."""
    origin = tuple(round(value / SPACING) for value in start)
    parents = {origin: None}
    queue = deque([origin])
    while queue:
        cell = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            other = cell[0] + dx, cell[1] + dy
            if other in parents:
                continue
            point = Vector2(other) * SPACING
            tile = int(point.x // S.TILE_SIZE), int(point.y // S.TILE_SIZE)
            if tile not in room.tiles or (excluded is not None and excluded.collidepoint(point)):
                continue
            if not room.projectile_blocked(Vector2(cell) * SPACING, point, S.PLAYER_RADIUS):
                parents[other] = cell
                queue.append(other)
    return parents


def path_to(parents, destination):
    cell = tuple(round(value / SPACING) for value in destination)
    if cell not in parents:
        return None
    path = []
    while cell is not None:
        path.append(Vector2(cell) * SPACING)
        cell = parents[cell]
    return path[::-1]


def validate_level(data):
    """Report bad assets, placements, deadlocked stages, exits, refuges, and route alternatives."""
    room = Room(data)
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)

    names = set(room.tiles.values()) | {p.asset for p in room.props + room.decorations}
    names.update(enemy[1] for enemy in data["enemies"])
    for name in sorted(names):
        require(name in CATALOG, f"unknown asset {name}")
        if name in CATALOG:
            require(asset_path(name).is_file(), f"missing asset {name}")
    for name in room.tiles.values():
        require(CATALOG[name]["size"] == [128, 128], f"non-tile floor {name}")
    placements = [("spawn", room.spawn, S.PLAYER_RADIUS), ("exit", Vector2(room.exit_rect.center), S.PLAYER_RADIUS)]
    placements += [(f"enemy {i} ({group})", Vector2(x, y) * S.TILE_SIZE, S.ENEMY_RADIUS)
                   for i, (group, _, x, y, _) in enumerate(data["enemies"])]
    placements += [(f"refuge {c['name']}", Vector2(c["spawn"]) * S.TILE_SIZE, S.PLAYER_RADIUS)
                   for c in data.get("checkpoints", [])]
    for name, point, radius in placements:
        body = pygame.FRect(point.x - radius, point.y - radius, radius * 2, radius * 2)
        require((int(point.x // S.TILE_SIZE), int(point.y // S.TILE_SIZE)) in room.tiles, f"{name} off floor")
        require(not any(body.colliderect(wall) for wall in room.walls_near(body)), f"{name} overlaps solid")
    for i, a in enumerate(room.enemy_spawns):
        require(a.distance_to(room.spawn) > S.ENEMY_RADIUS + S.PLAYER_RADIUS, f"enemy {i} overlaps player spawn")
        for b in room.enemy_spawns[i + 1:]:
            require(a.distance_to(b) >= S.ENEMY_RADIUS * 2, f"enemy {i} overlaps another enemy")
    groups = {name for name, _ in room.gates}
    require(groups <= {e[0] for e in data["enemies"]}, "gate refers to empty enemy group")
    # Fixed point: only open a gate if every defender is reachable with CURRENT gates.
    for _ in range(len(groups) + 1):
        parents = reachable(room, room.spawn)
        ready = {group for group in groups if all(path_to(parents, point) for entry, point in zip(data["enemies"], room.enemy_spawns) if entry[0] == group)}
        newly_open = ready - room.open_gates
        if not newly_open:
            break
        room.open_gates.update(newly_open)
        room.refresh_gates([])
    require(room.open_gates == groups, f"deadlocked groups: {sorted(groups - room.open_gates)}")
    parents = reachable(room, room.spawn)
    for name, point, _ in placements:
        path = path_to(parents, point)
        require(path is not None, f"{name} unreachable after clearing gates")
    # Check both authored routes independently with the OTHER branch cut away.
    for choice in data.get("choices", []):
        start, end = (Vector2(choice[key]) * S.TILE_SIZE for key in ("start", "end"))
        for index, rect in enumerate(choice["branches"]):
            excluded = pygame.FRect(*(value * S.TILE_SIZE for value in rect))
            path = path_to(reachable(room, start, excluded), end)
            require(path is not None, f"choice {choice['name']} blocked with branch {index} excluded")
            if path:
                require(all(room.move(a, b - a, S.PLAYER_RADIUS).distance_to(b) < .01 for a, b in zip(path, path[1:])), f"choice {choice['name']} fails movement clearance")
    for checkpoint in data.get("checkpoints", []):
        require(set(checkpoint["requires"]) <= groups, f"refuge {checkpoint['name']} references unknown group")
        room.open_gates = set(checkpoint["requires"])
        room.refresh_gates([])
        require(path_to(reachable(room, room.spawn), Vector2(checkpoint["spawn"]) * S.TILE_SIZE) is not None, f"refuge {checkpoint['name']} requires a later gate")
    return errors


def main():
    failed = False
    for level_id in LEVEL_IDS:
        errors = validate_level(load_level(level_id))
        print(f"{level_id}: " + ("; ".join(errors) if errors else "OK"))
        failed |= bool(errors)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
