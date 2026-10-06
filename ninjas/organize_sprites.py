from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


SPRITE_NAME = re.compile(
    r"^ninja_(east|west|south|north)_(idle|dash|run|slash|throw)_\d+(?: \(\d+\))?\.png$",
    re.IGNORECASE,
)
DIRECTIONS = ("east", "west", "south", "north")
ACTIONS = ("idle", "dash", "run", "slash", "throw")


def organize_sprites(root: Path, dry_run: bool = False) -> None:
    for direction in DIRECTIONS:
        for action in ACTIONS:
            folder = root / direction / action
            if not dry_run:
                folder.mkdir(parents=True, exist_ok=True)

    moves = []
    for source in sorted(root.iterdir()):
        if not source.is_file():
            continue

        match = SPRITE_NAME.fullmatch(source.name)
        if not match:
            continue

        direction, action = (part.lower() for part in match.groups())
        destination = root / direction / action / source.name
        if destination.exists():
            print(f"Skipped (destination exists): {destination.relative_to(root)}")
            continue
        moves.append((source, destination))

    for source, destination in moves:
        print(f"{source.name} -> {destination.relative_to(root)}")
        if not dry_run:
            shutil.move(str(source), str(destination))

    if dry_run:
        print(f"Dry run: {len(moves)} sprite(s) would be moved.")
    else:
        print(f"Organized {len(moves)} sprite(s). ninja_shuriken.png remains at the root.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize ninja animation sprites into direction/action folders."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned moves without creating folders or moving files.",
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Sprite directory (defaults to the directory containing this script).",
    )
    args = parser.parse_args()
    organize_sprites(args.directory.expanduser().resolve(), args.dry_run)


if __name__ == "__main__":
    main()