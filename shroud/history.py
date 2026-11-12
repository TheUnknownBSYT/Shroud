"""Bounded, detached per-run observations. No scoring, persistence or network IO."""
from collections import deque
from copy import deepcopy
from shroud import settings as S

EVENT_KINDS = {
    "developer_setup": "setup",
    "room_entered": "progress", "run_ended": "progress",
    "reward_offered": "opportunity", "reward_reopened": "opportunity", "reward_confirmed": "choice",
    "burst_activated": "use", "burst_expired": "use", "flow_transition": "use",
    "player_slash": "use", "player_throw_shuriken": "use", "player_dash": "use",
    "echo_attack": "use", "enemy_hit": "performance", "player_hit": "performance", "enemy_defeated": "performance",
    "player_parry": "performance", "echo_parry": "performance",
}


class RunHistory:
    def __init__(self, limit=S.HISTORY_LIMIT):
        if limit < 1:
            raise ValueError("History limit must be positive")
        self.limit = limit
        self.clear()

    def clear(self):
        self._records = deque(maxlen=self.limit)
        self.elapsed = 0.0
        self.sequence = self.action_serial = self.dropped = 0
        self.status = "playing"
        self.developer = False

    @property
    def records(self):
        # Callers may serialize/edit their copy without corrupting the stored evidence.
        return deepcopy(list(self._records))

    def next_action(self):
        self.action_serial += 1
        return self.action_serial

    def attach(self, world):
        for event in EVENT_KINDS:
            world.events.subscribe(event, lambda payload, event=event: self.record(world, event, payload))

    def record(self, world, event, payload):
        if self.status != "playing":
            return
        self.sequence += 1
        self.dropped += len(self._records) == self.limit
        area, objective = world.room.area_at(world.player.position)
        context = dict(level=world.room.data["id"] if world.room.data else "arena",
                       biome=world.room.biome, difficulty=world.difficulty, level_number=world.run_position,
                       run_length=world.run_length, area=area, objective=objective,
                       open_gates=sorted(world.room.open_gates), health=world.player.health,
                       max_health=world.player.max_health, counters=dict(world.stats),
                       modifiers=world.rewards.snapshot())
        self._records.append(deepcopy(dict(schema_version=1, sequence=self.sequence,
                                          timestamp=self.elapsed, event=event,
                                          kind=EVENT_KINDS[event], developer=self.developer,
                                          context=context, details=payload)))

    def finish(self, world, reason):
        if self.status == "playing":
            world.events.emit("run_ended", reason=reason)
            self.status = reason
