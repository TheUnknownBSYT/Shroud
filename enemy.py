"""The courtyard's stationary training sentry."""
from enum import Enum, auto
from pygame import Vector2
import settings as S
from combat import Entity, Projectile

class EnemyState(Enum):
    IDLE = auto()
    ATTACK = auto()
    COOLDOWN = auto()
    DEAD = auto()


class Enemy(Entity):
    """Stationary training sentry; locks its aim when the telegraph begins."""
    def __init__(self, entity_id: int, position: Vector2, delay: float) -> None:
        super().__init__(entity_id, position, S.ENEMY_RADIUS, S.ENEMY_HEALTH)
        self.state = EnemyState.IDLE
        self.timer = delay
        self.aim = Vector2(-1, 0)

    def tick(self, dt: float, target: Vector2, target_alive: bool) -> Projectile | None:
        self.flash = max(0.0, self.flash - dt)
        self.timer = max(0.0, self.timer - dt)
        if self.state == EnemyState.DEAD:
            if self.timer <= 0:
                self.health = self.max_health
                self.state, self.timer = EnemyState.IDLE, 1.0
            return None
        if not target_alive:
            self.state, self.timer = EnemyState.IDLE, 1.0
            return None
        if self.timer > 0:
            return None
        if self.state in (EnemyState.IDLE, EnemyState.COOLDOWN):
            delta = target - self.position
            if delta.length_squared():
                self.aim = delta.normalize()
            self.state, self.timer = EnemyState.ATTACK, S.ENEMY_TELEGRAPH
        elif self.state == EnemyState.ATTACK:
            self.state, self.timer = EnemyState.COOLDOWN, S.ENEMY_COOLDOWN
            return Projectile(self.position + self.aim * 30, self.aim * S.ENEMY_PROJECTILE_SPEED,
                              1, "enemy", 1500, "bolt", 6)
        return None

    def receive_damage(self, amount: int) -> bool:
        accepted = super().receive_damage(amount)
        if accepted and not self.alive:
            self.state, self.timer = EnemyState.DEAD, S.ENEMY_RESPAWN
        return accepted
