"""Opt-in developer launcher for deterministic ranks, bursts and real cache choices."""
import argparse
import os
from unittest.mock import patch
import pygame
from shroud.game import Game
from shroud.rewards import Cache, REWARDS, RunRewards


def configure(game, ranks=None, burst=None, offers=None):
    draft = RunRewards()
    for key, rank in (ranks or {}).items():
        if key not in draft.eligible("technique") or rank not in range(4):
            raise ValueError("Use technique keys with ranks 0–3")
        if rank:
            draft.ranks[key] = rank
    if burst is not None and burst not in draft.eligible("burst"):
        raise ValueError("Unknown burst")
    if offers:
        if (len(offers) != 2 or len(set(offers)) != 2 or any(key not in REWARDS for key in offers)
                or REWARDS[offers[0]].category != REWARDS[offers[1]].category
                or any(key not in draft.eligible(REWARDS[key].category) for key in offers)):
            raise ValueError("Offers must be two distinct eligible rewards in one category")
    game.rewards.reset()
    game.rewards.ranks, game.rewards.stored = dict(draft.ranks), burst
    game.history.clear()
    game.history.developer = True
    game.world.events.emit("developer_setup", ranks=dict(draft.ranks), stored=burst)
    if offers:
        chest = Cache("developer-cache", REWARDS[offers[0]].category, game.world.player.position.copy())
        game.world.caches.insert(0, chest)
        # Exercise the actual offering/recording code without affecting subsequent RNG draws.
        with patch.object(game.rewards.rng, "sample", return_value=list(offers)):
            game.open_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rank", action="append", default=[], metavar="KEY=0..3")
    parser.add_argument("--all-ranks", type=int, choices=range(4), default=0)
    parser.add_argument("--burst", choices=RunRewards().eligible("burst"))
    parser.add_argument("--offers", nargs=2, choices=tuple(REWARDS))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    try:
        ranks = dict.fromkeys(RunRewards().eligible("technique"), args.all_ranks)
        ranks.update((key, int(rank)) for key, rank in (value.split("=") for value in args.rank))
        if args.frames is not None and args.frames < 1:
            raise ValueError("Frames must be positive")
        if args.headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
        pygame.display.init()
        pygame.font.init()
        game = Game("training_01", seed=7, biome="grounds")
        configure(game, ranks, args.burst, args.offers)
        game.run(args.frames, args.screenshot)
    except ValueError as error:
        parser.error(str(error))
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
