"""Per-room biome rules; no global mutation, random placement or player profiling."""
from dataclasses import dataclass
from math import isfinite
from pygame import Vector2
from shroud import settings as S


@dataclass(frozen=True)
class BiomeRules:
    acceleration: float = S.ACCELERATION
    friction: float = S.FRICTION
    clear_radius: float = 0.0
    fade_radius: float = 0.0
    wind_acceleration: float = 0.0
    wind_direction: tuple = (3, 0)
    gust_seconds: float = 8.0
    period_seconds: float = 12.0
    warning_seconds: float = 1.0

    @classmethod
    def from_level(cls, data):
        """Merge only supported overrides, validating even currently inactive biomes."""
        data = data or {}
        overrides = data.get("biome_settings", {})
        if set(overrides) - S.BIOME_SETTINGS.keys():
            raise ValueError("Unknown biome in biome_settings")
        for biome, values in overrides.items():
            if set(values) - S.BIOME_SETTINGS[biome].keys():
                raise ValueError(f"Unsupported {biome} biome setting")
            cls(**(S.BIOME_SETTINGS[biome] | values)).validate()
        biome = data.get("biome", "grounds")
        values = S.BIOME_SETTINGS[biome] | overrides.get(biome, {})
        if "wind_direction" in values:
            values["wind_direction"] = tuple(values["wind_direction"])
        rules = cls(**values)
        rules.validate()
        return rules

    def validate(self):
        for name in ("acceleration", "friction", "clear_radius", "fade_radius", "wind_acceleration",
                     "gust_seconds", "period_seconds", "warning_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(f"Invalid biome setting: {name}")
        if self.fade_radius and not 0 < self.clear_radius < self.fade_radius:
            raise ValueError("Marsh needs 0 < clear_radius < fade_radius")
        if self.clear_radius and not self.fade_radius:
            raise ValueError("Marsh needs a fade_radius")
        if not (self.gust_seconds > 0 and self.warning_seconds > 0
                and self.period_seconds > self.gust_seconds + self.warning_seconds):
            raise ValueError("Wind needs a calm interval, warning and gust")
        direction = self.wind_direction
        if (len(direction) != 2 or not all(isinstance(v, (int, float)) and isfinite(v) for v in direction)
                or not Vector2(direction).length_squared()):
            raise ValueError("Wind direction must be a nonzero finite pair")

    def visible_enemy(self, origin, target):
        """Enemies only acquire/retain a target inside the fully clear mist circle."""
        return not self.clear_radius or origin.distance_squared_to(target) <= self.clear_radius ** 2

    def wind_phase(self, elapsed):
        phase = elapsed % self.period_seconds
        gust_start = self.period_seconds - self.gust_seconds
        warning_start = gust_start - self.warning_seconds
        if phase >= gust_start:
            return "gust", self.period_seconds - phase
        if phase >= warning_start:
            return "warning", gust_start - phase
        return "calm", warning_start - phase

    def wind_force(self, elapsed):
        if self.wind_acceleration and self.wind_phase(elapsed)[0] == "gust":
            return Vector2(self.wind_direction).normalize() * self.wind_acceleration
        return Vector2()
