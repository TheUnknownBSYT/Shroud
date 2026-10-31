import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="SHROUD — Handcrafted Journeys")
    from shroud.campaign import LEVEL_IDS, load_level
    from shroud.settings import RUN_LENGTH
    parser.add_argument("--level", choices=LEVEL_IDS, default=None, help="Pin the first layout; remaining layouts are random")
    parser.add_argument("--list-levels", action="store_true", help="List available layouts and exit")
    parser.add_argument("--levels", type=int, default=RUN_LENGTH, help="Layouts per run (1–18; default: %(default)s)")
    parser.add_argument("--seed", type=int, help="Reproduce layout and biome choices")
    parser.add_argument("--headless", action="store_true", help="Use SDL's dummy display for smoke checks")
    parser.add_argument("--frames", type=int, help="Exit after this many rendered frames")
    parser.add_argument("--screenshot", help="Save the final rendered frame as a PNG")
    args = parser.parse_args()
    if args.list_levels:
        for index, level_id in enumerate(LEVEL_IDS, 1):
            data = load_level(level_id)
            print(f"{index:02}  {level_id:14}  {data['name']}")
        return
    if not 1 <= args.levels <= len(LEVEL_IDS):
        parser.error("--levels must be between 1 and 18")
    if args.frames is not None and args.frames < 1:
        parser.error("--frames must be positive")
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    import pygame
    from shroud.game import Game
    try:
        pygame.display.init()
        pygame.font.init()
        Game(args.level, run_length=args.levels, seed=args.seed).run(args.frames, args.screenshot)
    except (FileNotFoundError, ValueError, pygame.error) as error:
        parser.exit(1, f"SHROUD could not start: {error}\nCheck the named asset or level file and display availability.\n")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
