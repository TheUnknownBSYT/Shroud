"""Run-owned rewards, fixed cache offers, and effective values; no rendering."""
from dataclasses import dataclass
import random
from pygame import Vector2
from shroud import settings as S


@dataclass(frozen=True)
class Reward:
    name: str
    category: str
    stat: str = ""
    bonuses: tuple = ()
    description: str = ""


REWARDS = {
    "sharpening": Reward("Sharpening", "technique", "slash_damage", (.15, .25, .30)),
    "reach": Reward("Reach", "technique", "slash_reach", (.10, .20, .25)),
    "quick_charge": Reward("Quick Charge", "technique", "charge_time", (-.15, -.25, -.30)),
    "footwork": Reward("Footwork", "technique", "dash_cooldown", (-.15, -.25, -.30)),
    "smoke_veil": Reward("Smoke Veil", "burst", description="Stops new enemy targeting. Existing shots still hurt."),
    "haste": Reward("Haste", "burst", description="Normal movement x1.5. Dash and attack timing unchanged."),
}
RANKS = ("—", "I", "II", "III")
BURST_DURATION = 10.0
INTERACT_RADIUS = 100.0


@dataclass(frozen=True)
class EffectiveValues:
    slash_damage: float
    slash_reach: float
    charge_time: float
    dash_cooldown: float
    move_speed: float


class RunRewards:
    def __init__(self, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    def reset(self):
        self.ranks = {}
        self.stored = self.active = None
        self.remaining = self.expired_time = 0.0
        self.expired = None

    def effective(self, ranks=None):
        """Every bonus is a total relative to base, never compounded or undone."""
        ranks = self.ranks if ranks is None else ranks
        values = dict(slash_damage=S.SLASH_DAMAGE, slash_reach=S.SLASH_REACH,
                      charge_time=S.SLASH_CHARGE_TIME, dash_cooldown=S.DASH_COOLDOWN)
        for key, rank in ranks.items():
            reward = REWARDS[key]
            values[reward.stat] *= 1 + reward.bonuses[rank - 1]
        return EffectiveValues(**values, move_speed=S.PLAYER_SPEED * (1.5 if self.active == "haste" else 1))

    def eligible(self, category):
        return [key for key, value in REWARDS.items() if value.category == category
                and (category == "burst" or self.ranks.get(key, 0) < 3)]

    def upgrade(self, key):
        if key not in self.eligible("technique"):
            return False
        self.ranks[key] = self.ranks.get(key, 0) + 1
        return True

    def preview(self, key):
        ranks = dict(self.ranks)
        ranks[key] = min(3, ranks.get(key, 0) + 1)
        stat = REWARDS[key].stat
        return getattr(self.effective(), stat), getattr(self.effective(ranks), stat)

    def activate(self, events):
        if self.active or self.stored is None:
            return False
        self.active, self.stored = self.stored, None
        self.remaining = BURST_DURATION
        self.expired = None
        self.expired_time = 0.0
        events.emit("burst_activated", reward=self.active, duration=BURST_DURATION)
        return True

    def tick(self, dt, events):
        self.expired_time = max(0.0, self.expired_time - dt)
        if self.active:
            self.remaining = max(0.0, self.remaining - dt)
            if self.remaining < 1e-8:
                self.expired, self.active = self.active, None
                self.remaining, self.expired_time = 0.0, 1.5
                events.emit("burst_expired", reward=self.expired)


@dataclass
class Cache:
    key: str
    category: str
    position: Vector2
    requires: tuple = ()
    offers: tuple | None = None
    claimed: bool = False
    opening: float = 0.0

    def available(self, world):
        return not self.claimed and set(self.requires) <= world.room.open_gates

    def offer(self, rewards, events):
        if self.claimed:
            return None
        if self.offers is None:
            pool = rewards.eligible(self.category)
            if len(pool) < 2:
                return None  # Leave the cache usable if eligibility changes later.
            self.offers = tuple(rewards.rng.sample(pool, 2))
            events.emit("reward_offered", cache=self.key, category=self.category, offers=self.offers)
        self.opening = .4
        return self.offers


@dataclass
class Choice:
    cache: Cache
    selected: int | None = None
    replacing: bool = False
    message: str = ""

    def select(self, index):
        if index in (0, 1) and not self.replacing:
            self.selected = index
            self.message = ""

    def confirm(self, rewards, events):
        """Two deliberate confirmations are needed to discard a stored burst."""
        if self.cache.claimed or self.selected is None or self.cache.offers is None:
            return False
        key = self.cache.offers[self.selected]
        definition = REWARDS[key]
        if definition.category == "technique":
            if not rewards.upgrade(key):
                self.message = "This technique is already capped. Choose the other scroll or close."
                return False
        elif rewards.stored is not None and not self.replacing:
            self.replacing = True
            return False
        else:
            rewards.stored = key
        self.cache.claimed = True
        events.emit("reward_confirmed", cache=self.cache.key, reward=key,
                    rank=rewards.ranks.get(key, 0))
        return True

    def cancel(self):
        if self.replacing:
            self.replacing = False
            return False  # Back to cards, preserving deliberate selection.
        return True


def load_caches(data):
    return [Cache(item["id"], item["category"], Vector2(item["position"]) * S.TILE_SIZE,
                  tuple(item.get("requires", []))) for item in (data or {}).get("caches", [])]


def nearby_cache(world):
    if not world.player.alive or world.complete:
        return None
    candidates = [cache for cache in world.caches if cache.available(world)
                  and cache.position.distance_to(world.player.position) <= INTERACT_RADIUS
                  and not world.room.movement_blocked(world.player.position, cache.position, 0)]
    return min(candidates, key=lambda cache: cache.position.distance_squared_to(world.player.position), default=None)
