"""Verified export catalogue and small biome palettes. Geometry is in source pixels."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "assets"
CATALOG = json.loads((ROOT / "catalog.json").read_text())

# earth / stone / platform / mat are authoring materials, not different physics.
PALETTES = {
    "training": {
        "floors": ("floor_earth_01", "floor_stone_01", "platform", "mat"),
        "wall": "wall", "fence": "fence", "outside": "floor_earth_01",
        "tint": (140, 165, 145), "accent": (139, 236, 200),
    },
    "temple": {
        "floors": ("temple_floor_wood", "temple_floor_stone", "temple_floor_wood", "temple_floor_tatami"),
        "wall": "temple_platform_edge", "fence": "temple_sliding_wall", "outside": "temple_floor_wood",
        "tint": (75, 90, 85), "accent": (220, 207, 146),
    },
    "rooftop": {
        "floors": ("roof_tile", "roof_tile", "roof_balcony", "temple_floor_wood"),
        "wall": "roof_edge", "fence": "roof_ridge", "outside": "roof_tile",
        "tint": (42, 57, 69), "accent": (161, 206, 229),
    },
    "misty": {
        "floors": ("marsh_floor_damp", "marsh_boardwalk", "marsh_boardwalk", "marsh_bank_junction"),
        "wall": "marsh_boardwalk_edge", "fence": "fence", "outside": "marsh_water_shallow",
        "tint": (140, 170, 175), "accent": (159, 212, 202),
    },
    "autumn": {
        "floors": ("autumn_floor_earth", "autumn_floor_leaves", "autumn_path_straight", "autumn_path_junction"),
        "wall": "low_wall", "fence": "fence", "outside": "autumn_floor_leaves",
        "tint": (100, 100, 70), "accent": (236, 183, 105),
    },
    "snow": {
        "floors": ("snow_floor_packed_01", "snow_floor_icy_stone", "snow_path_straight", "snow_floor_packed_02"),
        "wall": "snow_wall_straight", "fence": "snow_fence", "outside": "snow_pond_frozen",
        "tint": (110, 140, 160), "accent": (211, 237, 249),
    },
}


# Runtime conditions are independent of each layout's authored cover/style.
BIOME_THEMES = {"grounds": "training", "snow": "snow", "marsh": "misty", "wind": "rooftop"}
BIOME_NAMES = {"grounds": "Training grounds", "snow": "Snow", "marsh": "Marsh", "wind": "Crosswind"}


def floor_asset(biome, material, x, y):
    if biome == "training" and material in ("earth", "stone"):
        return f"floor_{material}_0{1 + (x + y) % 2}"
    if biome == "snow" and material == "earth":
        return f"snow_floor_packed_0{1 + (x + y) % 2}"
    if material in ("earth", "stone", "platform", "mat"):
        return PALETTES[biome]["floors"][("earth", "stone", "platform", "mat").index(material)]
    if material not in CATALOG:
        raise ValueError(f"Unknown floor asset: {material}")
    return material


def asset_path(name):
    if name not in CATALOG:
        raise ValueError(f"Unknown asset key: {name}")
    path = ROOT / CATALOG[name]["path"]
    if not path.is_file():
        raise FileNotFoundError(f"Missing exported asset: {path}")
    return path
