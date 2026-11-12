"""Run-owned rewards, fixed cache offers, and effective values; no rendering."""
from dataclasses import dataclass, asdict
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
    additive: bool = False


REWARDS = {
    "sharpening": Reward("Sharpening", "technique", "slash_damage", (.15, .25, .30)),
    "reach": Reward("Reach", "technique", "slash_reach", (.10, .20, .25)),
    "quick_charge": Reward("Quick Charge", "technique", "charge_time", (-.15, -.25, -.30)),
    "footwork": Reward("Footwork", "technique", "dash_cooldown", (-.15, -.25, -.30)),
    "rapid_throw": Reward("Rapid Throw", "technique", "throw_cooldown", (-.15, -.25, -.30)),
    "long_throw": Reward("Long Throw", "technique", "shuriken_range", (.20, .35, .50)),
    "lingering_echo": Reward("Lingering Echo", "technique", "echo_lifetime", (1., 1.5, 2.), additive=True),
    "parry": Reward("Parry", "technique", "parry_window", (.05, .08, .10), additive=True),
    "smoke_veil": Reward("Smoke Veil", "burst", description="Stops new enemy targeting. Existing shots still hurt."),
    "haste": Reward("Haste", "burst", description="Normal movement x1.5. Dash and attack timing unchanged."),
    "frenzy": Reward("Frenzy", "burst", description="Slash/throw cooldowns -35%. Recovery halved; hit windows preserved."),
    "flow": Reward("Flow", "burst", description="Alternate accepted slashes and throws for +40% damage. First attack sets the sequence."),
}
RANKS = ("—", "I", "II", "III")
BURST_DURATION = 10.0
INTERACT_RADIUS = 100.0


@dataclass(frozen=True)
class ActionTiming:
    duration: float
    cooldown: float
    phase_end: float
    base_duration: float
    parry_window: float

    def animation_time(self, elapsed):
        """Keep startup/emission/hits at real time; compress only recovery frames."""
        if elapsed <= self.phase_end:
            return elapsed
        recovery = self.duration - self.phase_end
        fraction = min(1., (elapsed - self.phase_end) / recovery) if recovery > 0 else 1.
        return self.phase_end + fraction * (self.base_duration - self.phase_end)


def action_timing(kind, cooldown, parry_window, frenzy):
    base = S.SLASH_DURATION if kind == "slash" else S.THROW_DURATION
    phase = max(S.SLASH_ACTIVE_END, parry_window) if kind == "slash" else S.THROW_EMISSION_END
    phase = min(base, max(0., phase))
    duration = phase + (base - phase) * (S.FRENZY_RECOVERY_MULTIPLIER if frenzy else 1.)
    cooldown *= S.FRENZY_COOLDOWN_MULTIPLIER if frenzy else 1.
    return ActionTiming(duration, max(duration, cooldown), phase, base,
                        min(base, max(0., parry_window)) if kind == "slash" else 0.)


@dataclass(frozen=True)
class EffectiveValues:
    slash_damage: float
    slash_reach: float
    charge_time: float
    dash_cooldown: float
    move_speed: float
    throw_cooldown: float
    shuriken_range: float
    echo_lifetime: float
    parry_window: float
    slash_timing: ActionTiming
    throw_timing: ActionTiming


class RunRewards:
    def __init__(self, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    def reset(self):
        self.ranks = {}
        self.stored = self.active = None
        self.remaining = self.expired_time = 0.0
        self.expired = None
        self.flow_previous = None
        self.offer_serial = 0

    def snapshot(self):
        return dict(ranks=dict(self.ranks), stored=self.stored, active=self.active,
                    remaining=self.remaining, flow_previous=self.flow_previous,
                    effective=asdict(self.effective()))

    def effective(self, ranks=None):
        """Every bonus is a total relative to base, never compounded or undone."""
        ranks = self.ranks if ranks is None else ranks
        values = dict(slash_damage=S.SLASH_DAMAGE, slash_reach=S.SLASH_REACH,
                      charge_time=S.SLASH_CHARGE_TIME, dash_cooldown=S.DASH_COOLDOWN,
                      throw_cooldown=S.SHURIKEN_COOLDOWN, shuriken_range=S.SHURIKEN_RANGE,
                      echo_lifetime=S.ECHO_LIFETIME, parry_window=S.PARRY_WINDOW)
        for key, rank in ranks.items():
            reward = REWARDS[key]
            bonus = reward.bonuses[rank - 1]
            values[reward.stat] = values[reward.stat] + bonus if reward.additive else values[reward.stat] * (1 + bonus)
        values["parry_window"] = min(S.SLASH_DURATION, max(0., values["parry_window"]))
        slash = action_timing("slash", S.SLASH_COOLDOWN, values["parry_window"], self.active == "frenzy")
        throw = action_timing("throw", values["throw_cooldown"], 0., self.active == "frenzy")
        values["throw_cooldown"] = throw.cooldown
        return EffectiveValues(**values, slash_timing=slash, throw_timing=throw,
                               move_speed=S.PLAYER_SPEED * (1.5 if self.active == "haste" else 1))

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
        prior = self.snapshot()
        self.active, self.stored = self.stored, None
        self.flow_previous = None
        self.remaining = BURST_DURATION
        self.expired = None
        self.expired_time = 0.0
        events.emit("burst_activated", reward=self.active, duration=BURST_DURATION, prior=prior)
        return True

    def tick(self, dt, events):
        self.expired_time = max(0.0, self.expired_time - dt)
        if self.active:
            self.remaining = max(0.0, self.remaining - dt)
            if self.remaining < 1e-8:
                self.expired, self.active = self.active, None
                self.remaining, self.expired_time = 0.0, 1.5
                previous = self.flow_previous
                self.flow_previous = None
                events.emit("burst_expired", reward=self.expired, flow_previous=previous)

    def accept_attack(self, action):
        if self.active != "flow" or action not in ("slash", "throw"):
            return None
        previous, self.flow_previous = self.flow_previous, action
        return dict(previous=previous, current=action, earned=previous is not None and previous != action)

    def describe_offer(self, key):
        reward = REWARDS[key]
        if reward.category == "technique":
            rank = self.ranks.get(key, 0)
            before, after = self.preview(key)
            return dict(reward=key, next_rank=min(3, rank + 1), current_rank=rank,
                        stat=reward.stat, before=before, after=after,
                        total_bonus=reward.bonuses[min(2, rank)], additive=reward.additive)
        effects = {
            "smoke_veil": dict(new_targeting=False, damage_immunity=False),
            "haste": dict(walk_multiplier=1.5),
            "frenzy": dict(cooldown_multiplier=S.FRENZY_COOLDOWN_MULTIPLIER,
                           recovery_multiplier=S.FRENZY_RECOVERY_MULTIPLIER),
            "flow": dict(alternating_damage_multiplier=S.FLOW_DAMAGE_MULTIPLIER),
        }
        return dict(reward=key, next_rank=None, duration=BURST_DURATION, effects=effects[key])


@dataclass
class Cache:
    key: str
    category: str
    position: Vector2
    requires: tuple = ()
    offers: tuple | None = None
    claimed: bool = False
    opening: float = 0.0
    offer_id: int | None = None
    offer_details: tuple | None = None

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
            rewards.offer_serial += 1
            self.offer_id = rewards.offer_serial
            self.offer_details = tuple(rewards.describe_offer(key) for key in self.offers)
            events.emit("reward_offered", cache=self.key, offer_id=self.offer_id,
                        category=self.category, offers=self.offers, effects=self.offer_details)
        else:
            events.emit("reward_reopened", cache=self.key, offer_id=self.offer_id,
                        category=self.category, offers=self.offers,
                        effects=tuple(rewards.describe_offer(key) for key in self.offers))
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
        prior = rewards.snapshot()
        displayed = tuple(rewards.describe_offer(offer) for offer in self.cache.offers)
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
                    rank=rewards.ranks.get(key, 0), offer_id=self.cache.offer_id,
                    category=self.cache.category, offers=self.cache.offers,
                    offered_effects=self.cache.offer_details, selected=self.selected,
                    displayed_effects=displayed,
                    replacement=definition.category == "burst" and prior["stored"] is not None,
                    prior=prior, applied=rewards.describe_offer(key) if definition.category == "burst"
                    else dict(stat=definition.stat, value=getattr(rewards.effective(), definition.stat)))
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
