import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="SHROUD — Phase 1 combat sandbox")
    parser.add_argument("--headless", action="store_true", help="Use SDL's dummy display for smoke checks")
    parser.add_argument("--frames", type=int, help="Exit after this many rendered frames")
    parser.add_argument("--screenshot", help="Save the final rendered frame as a PNG")
    args = parser.parse_args()
    if args.frames is not None and args.frames < 1:
        parser.error("--frames must be positive")
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    import pygame
    from game import Game
    try:
        pygame.display.init()
        pygame.font.init()
        Game().run(args.frames, args.screenshot)
    except (FileNotFoundError, pygame.error) as error:
        parser.exit(1, f"SHROUD could not start: {error}\nCheck the ninjas/ assets and display availability.\n")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
