"""Authored layouts and finite random runs, independent of biome and enemy plans."""
import json
import random
from pathlib import Path
from shroud import settings as S
from shroud.assets import BIOME_THEMES

LEVEL_ROOT = Path(__file__).resolve().parent.parent / "data" / "levels"
LEVEL_IDS = (
    "training_01",
    "temple_01", "temple_02", "temple_04",
    "rooftop_01", "rooftop_02", "rooftop_03",
    "misty_01", "misty_02", "misty_03",
    "autumn_02", "autumn_03", "autumn_04",
    "snow_01", "snow_02", "snow_04",
    "final_01", "final_02",
)
BIOME_IDS = tuple(BIOME_THEMES)
SELECTOR_ROWS = (len(LEVEL_IDS) + 1) // 2


def load_level(level_id, biome="grounds"):
    """Read fresh neutral layout data; explicitly choose a biome for tools/tests."""
    if level_id not in LEVEL_IDS:
        raise ValueError(f"Unknown level {level_id!r}. Use --list-levels.")
    if biome not in BIOME_IDS:
        raise ValueError(f"Unknown biome {biome!r}. Choose from {BIOME_IDS}.")
    data = json.loads((LEVEL_ROOT / f"{level_id}.json").read_text())
    if data["id"] != level_id:
        raise ValueError(f"Level ID does not match its filename: {level_id}")
    data["biome"] = biome
    return data


class Run:
    """A fixed-length sample without repeated layouts; biome is rolled on scene load."""

    def __init__(self, length=S.RUN_LENGTH, first=None, rng=None, biome=None):
        if not 1 <= length <= len(LEVEL_IDS):
            raise ValueError(f"Run length must be between 1 and {len(LEVEL_IDS)}.")
        if first is not None and first not in LEVEL_IDS:
            raise ValueError(f"Unknown starting level {first!r}.")
        if biome is not None and biome not in BIOME_IDS:
            raise ValueError(f"Unknown biome {biome!r}.")
        self.biome_override = biome
        self.rng = rng if rng is not None else random.Random()
        pool = [level_id for level_id in LEVEL_IDS if level_id != first]
        self.level_ids = tuple(([first] if first else []) + self.rng.sample(pool, length - (1 if first is not None else 0)))
        self.index = 0

    @property
    def current(self):
        return self.level_ids[self.index]

    @property
    def following(self):
        return self.level_ids[self.index + 1] if self.index + 1 < len(self.level_ids) else None

    def load_current(self):
        """Roll with Python's random library; independent draws may repeat a biome."""
        return load_level(self.current, self.biome_override or self.rng.choice(BIOME_IDS))
