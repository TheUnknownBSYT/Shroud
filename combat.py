"""Shared health, attack geometry, projectiles, and damage resolution."""
from dataclasses import dataclass, field
from pygame import Vector2
import settings as S

@dataclass
class Entity:
    entity_id: int
    position: Vector2
    radius: float
    max_health: int
    health: int = field(init=False)
    flash: float = 0.0

    def __post_init__(self) -> None:
        self.health = self.max_health

    @property
    def alive(self) -> bool:
        return self.health > 0

    def receive_damage(self, amount: int) -> bool:
        if not self.alive or amount <= 0:
            return False
        self.health = max(0, self.health - amount)
        self.flash = 0.12
        return True


@dataclass
class Attack:
    kind: str
    damage: int
    direction: Vector2
    hit_entities: set[int] = field(default_factory=set)
    reach: float = S.SLASH_REACH


def make_slash(direction, charge=0.0):
    charge = max(0.0, min(1.0, charge))
    return Attack("slash", round(S.SLASH_DAMAGE * (1 + charge * (S.SLASH_CHARGE_DAMAGE - 1))),
                  direction.copy(), reach=S.SLASH_REACH * (1 + charge * (S.SLASH_CHARGE_REACH - 1)))


def slash_active(elapsed):
    return S.SLASH_ACTIVE_START <= elapsed < S.SLASH_ACTIVE_END


def parry_active(elapsed):
    # The same slash opens with a brief deflection window.
    return elapsed < S.PARRY_WINDOW


def circles_overlap(a: Vector2, ar: float, b: Vector2, br: float) -> bool:
    return a.distance_squared_to(b) <= (ar + br) ** 2


def in_arc(origin: Vector2, direction: Vector2, target: Vector2, radius: float, reach: float) -> bool:
    offset = target - origin
    if offset.length_squared() > (reach + radius) ** 2:
        return False
    # A generous front half-circle keeps close strikes forgiving, but rejects rear attacks.
    return offset.dot(direction) >= -radius * 0.3


def segment_circle(start: Vector2, end: Vector2, center: Vector2, radius: float) -> float | None:
    """Return first contact fraction along a swept projectile, including initial overlap."""
    delta, offset = end - start, start - center
    c = offset.length_squared() - radius * radius
    if c <= 0:
        return 0.0
    a = delta.length_squared()
    if a == 0:
        return None
    b = 2 * offset.dot(delta)
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return None
    t = (-b - discriminant ** 0.5) / (2 * a)
    return t if 0 <= t <= 1 else None


@dataclass
class Projectile:
    position: Vector2
    velocity: Vector2
    damage: int
    team: str
    max_range: float
    kind: str = "shuriken"
    radius: float = 7.0
    travelled: float = 0.0
    alive: bool = True
    owner: str = "player"
    previous: Vector2 = field(init=False)

    def __post_init__(self) -> None:
        self.previous = self.position.copy()

    def advance(self, dt: float) -> None:
        self.previous = self.position.copy()
        distance = min(self.velocity.length() * dt, max(0, self.max_range - self.travelled))
        if self.velocity.length_squared():
            self.position += self.velocity.normalize() * distance
        self.travelled += distance

    @property
    def expired(self) -> bool:
        return self.travelled >= self.max_range - 1e-8


def make_shuriken(position, direction, owner="player"):
    return Projectile(
        position + direction * 24, direction * S.SHURIKEN_SPEED,
        S.SHURIKEN_DAMAGE, "player", S.SHURIKEN_RANGE, owner=owner,
    )


def deal_damage(world, target: Entity, amount: int, kind: str) -> None:
    if not target.receive_damage(amount):
        return
    is_player = target is world.player
    world.events.emit("player_hit" if is_player else "enemy_hit", timestamp=world.time,
                      position=tuple(target.position), damage=amount, source=kind)
    world.impact(target.position, "hurt" if is_player else "hit")
    if not is_player and not target.alive:
        world.events.emit("enemy_defeated", timestamp=world.time, entity_id=target.entity_id,
                          position=tuple(target.position))
        world.impact(target.position, "defeat")


def resolve_melee(world, attacker) -> None:
    attack = attacker.attack
    if attack is None or not attacker.damage_active:
        return
    for enemy in world.enemies:
        if not enemy.alive or enemy.entity_id in attack.hit_entities:
            continue
        if attack.kind == "dash":
            hit = circles_overlap(attacker.position, attacker.radius + 10, enemy.position, enemy.radius)
        else:
            hit = in_arc(attacker.position, attack.direction, enemy.position, enemy.radius, attack.reach)
        if hit and not world.room.projectile_blocked(attacker.position, enemy.position, 0):
            attack.hit_entities.add(enemy.entity_id)
            deal_damage(world, enemy, attack.damage, attack.kind)


def parry_contact(attacker, projectile):
    if not attacker.parry_active or projectile.velocity.dot(attacker.facing) >= 0:
        return None
    contact = segment_circle(
        projectile.previous, projectile.position, attacker.position,
        S.PARRY_REACH + projectile.radius,
    )
    if contact is None:
        return None
    point = projectile.previous.lerp(projectile.position, contact)
    if in_arc(attacker.position, attacker.facing, point, projectile.radius, S.PARRY_REACH):
        return contact
    return None


def resolve_enemy_projectile(world, projectile):
    player = world.player
    defenders = []
    if player.alive:
        defenders.append(player)
    if world.echo is not None:
        defenders.append(world.echo)
    defender = None
    first_contact = 2.0
    for candidate in defenders:
        contact = parry_contact(candidate, projectile)
        if contact is not None and contact < first_contact:
            defender = candidate
            first_contact = contact

    body_contact = None
    if player.alive:
        body_contact = segment_circle(
            projectile.previous, projectile.position, player.position,
            player.radius + projectile.radius,
        )
    # An Echo farther along the bolt's path cannot undo an earlier player hit.
    if body_contact is not None and body_contact < first_contact:
        deal_damage(world, player, projectile.damage, projectile.kind)
        projectile.alive = False
    elif defender is not None:
        projectile.position = projectile.previous.lerp(projectile.position, first_contact)
        projectile.velocity *= -1.8
        projectile.team = "player"
        projectile.kind = "reflected"
        projectile.owner = "player" if defender is player else "echo"
        projectile.damage = S.REFLECTED_DAMAGE
        projectile.travelled = 0.0
        projectile.max_range = 1500
        world.events.emit(f"{projectile.owner}_parry", timestamp=world.time,
                          position=tuple(defender.position))
        world.impact(projectile.position, "parry")


def resolve_friendly_projectile(world, projectile):
    nearest_enemy = None
    first_contact = 2.0
    for enemy in world.enemies:
        if not enemy.alive:
            continue
        contact = segment_circle(
            projectile.previous, projectile.position, enemy.position,
            enemy.radius + projectile.radius,
        )
        if contact is not None and contact < first_contact:
            nearest_enemy = enemy
            first_contact = contact
    if nearest_enemy is not None:
        deal_damage(world, nearest_enemy, projectile.damage, projectile.kind)
        projectile.alive = False


def resolve_projectiles(world, dt: float) -> None:
    for projectile in world.projectiles:
        if not projectile.alive:
            continue
        projectile.advance(dt)
        start, end = projectile.previous, projectile.position
        if world.room.projectile_blocked(start, end, projectile.radius):
            projectile.alive = False
            world.impact(end, "wall")
            continue
        if projectile.team == "enemy":
            resolve_enemy_projectile(world, projectile)
        elif projectile.team == "player":
            resolve_friendly_projectile(world, projectile)
        if projectile.expired:
            projectile.alive = False
    world.projectiles = [projectile for projectile in world.projectiles if projectile.alive]
