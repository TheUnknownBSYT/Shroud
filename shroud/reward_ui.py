"""Power-up presentation and shared hitboxes. Drawing never advances game state."""
import pygame
from shroud.assets import ROOT
from shroud.rewards import REWARDS, RANKS, nearby_cache

INK = (30, 39, 36)
PAPER = (238, 229, 210)
MINT = (139, 236, 200)
MUTED = (165, 183, 172)
CONFIRM_RECT = pygame.Rect(672, 638, 250, 44)
CANCEL_RECT = pygame.Rect(358, 638, 250, 44)
STAT_LABELS = {"slash_damage": "Slash damage", "slash_reach": "Slash reach",
               "charge_time": "Full charge", "dash_cooldown": "Dash cooldown",
               "throw_cooldown": "Throw cooldown", "shuriken_range": "Shuriken range",
               "echo_lifetime": "Echo wait", "parry_window": "Opening parry"}


def card_rects():
    return (pygame.Rect(256, 224, 336, 352), pygame.Rect(688, 224, 336, 352))


def value_text(key, value):
    stat = REWARDS[key].stat
    if stat == "slash_damage":
        return str(round(value))  # Matches the quick slash's integer damage.
    if stat in ("slash_reach", "shuriken_range"):
        return f"{value:g} px"
    return f"{value:.4f}".rstrip("0").rstrip(".") + " s"


def bonus_text(key, rank):
    reward = REWARDS[key]
    if not rank:
        return "Base"
    bonus = reward.bonuses[rank - 1]
    return f"{bonus:+g} s" if reward.additive else f"{bonus * 100:+g}%"


class RewardUI:
    def __init__(self):
        self.font = pygame.font.Font(None, 24)
        self.small = pygame.font.Font(None, 20)
        self.title = pygame.font.Font(None, 40)
        self.images = {}
        sizes = {"ui_scroll_card_background": (336, 352), "ui_selection_border": (352, 368),
                 "interaction_indicator": (24, 24), "scroll_technique_sealed": (18, 18),
                 "scroll_burst_sealed": (18, 18)}
        sizes.update({f"icon_{key}": (72, 72) for key in REWARDS})
        sizes.update({name: (64, 64) for name in (
            "cache_closed", "cache_available", "cache_empty", "cache_shadow",
            *(f"cache_opening_{i:02}" for i in range(1, 5)))})
        for name, size in sizes.items():
            source = pygame.image.load(ROOT / "powerups" / f"{name}.png").convert_alpha()
            self.images[name] = pygame.transform.smoothscale(source, size)
        self.small_icons = {key: pygame.transform.smoothscale(self.images[f"icon_{key}"], (24, 24)) for key in REWARDS}

    def text(self, screen, text, position, color=PAPER, font=None, center=False):
        image = (font or self.font).render(text, True, color)
        rect = image.get_rect(center=position) if center else image.get_rect(topleft=position)
        screen.blit(image, rect)

    def wrapped(self, screen, text, rect, color=INK):
        line, y = "", rect.y
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if self.font.size(candidate)[0] > rect.width and line:
                self.text(screen, line, (rect.x, y), color)
                y += 23
                line = word
            else:
                line = candidate
        self.text(screen, line, (rect.x, y), color)

    def cache(self, screen, cache, world, camera):
        point = camera.world_to_screen(cache.position)
        # All 256-square exports keep their full canvas and exactly this anchor.
        rect = self.images["cache_closed"].get_rect(center=(point.x, point.y - 15))
        screen.blit(self.images["cache_shadow"], rect)
        if cache.claimed:
            name = "cache_empty"
        elif cache.opening > 0:
            frame = min(4, 1 + int((.4 - cache.opening) / .1))
            name = f"cache_opening_{frame:02}"
        elif cache.offers:
            name = "cache_opening_04"
        else:
            name = "cache_available" if cache.available(world) else "cache_closed"
        screen.blit(self.images[name], rect)
        if not cache.claimed:
            seal = self.images[f"scroll_{cache.category}_sealed"]
            screen.blit(seal, seal.get_rect(center=(point.x, point.y + 12)))
        if cache is nearby_cache(world):
            cue = self.images["interaction_indicator"]
            screen.blit(cue, cue.get_rect(center=(point.x - 38, point.y - 18)))
            self.text(screen, "E  Open cache", (point.x, point.y + 30), MINT, self.small, True)

    def status(self, screen, world, paused=False, notice=""):
        rewards = world.rewards
        # Fixed rows leave the existing objective and controls in their own space.
        pygame.draw.rect(screen, INK, (0, 688, 1280, 49))
        x, hover = 32, ""
        values = rewards.effective()
        for key, definition in REWARDS.items():
            if definition.category != "technique":
                continue
            rank = rewards.ranks.get(key, 0)
            pygame.draw.rect(screen, PAPER if rank else MUTED, (x, 691, 24, 24))
            screen.blit(self.small_icons[key], (x, 691))
            self.text(screen, RANKS[rank], (x + 28, 697), PAPER, self.small)
            if pygame.Rect(x, 691, 60, 24).collidepoint(pygame.mouse.get_pos()):
                hover = f"{definition.name} {RANKS[rank]} / {STAT_LABELS[definition.stat]}: {value_text(key, getattr(values, definition.stat))}"
            x += 66
        self.text(screen, "P Details", (575, 697), MUTED, self.small)
        if rewards.active:
            state = f"{'PAUSED' if paused else 'ACTIVE'}  {REWARDS[rewards.active].name}  {rewards.remaining:.1f}s"
        elif rewards.expired_time > 0:
            state = f"EXPIRED  {REWARDS[rewards.expired].name}"
        else:
            state = "STORED" if rewards.stored else "BURST"
        stored = f"Q  {REWARDS[rewards.stored].name}" if rewards.stored else "Q  Empty slot"
        if rewards.active and rewards.stored:
            stored += " (waiting)"
        icon_key = rewards.active or rewards.stored
        if icon_key:
            pygame.draw.rect(screen, PAPER, (640, 691, 24, 24))
            screen.blit(self.small_icons[icon_key], (640, 691))
        self.text(screen, state + "  |  " + stored, (670, 697), MINT, self.small)
        cache = nearby_cache(world)
        message = hover or notice or (f"E  Open {cache.category} cache / choose one scroll" if cache else "E  Interact with caches   /   Q  Use stored burst   /   P  Technique details")
        self.text(screen, message, (32, 719), MUTED, self.small)
        if rewards.active == "flow":
            next_action = "throw" if rewards.flow_previous == "slash" else "slash"
            hint = f"FLOW: next {next_action.upper()} +40%" if rewards.flow_previous else "FLOW: first attack sets sequence"
            self.text(screen, hint, (936, 719), MINT, self.small)

    def button(self, screen, rect, text, enabled=True):
        pygame.draw.rect(screen, MINT if enabled else (76, 91, 83), rect, border_radius=4)
        self.text(screen, text, rect.center, INK if enabled else PAPER, center=True)

    def overlay(self, screen, world, choice):
        shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        shade.fill((12, 22, 23, 225))
        screen.blit(shade, (0, 0))
        rewards = world.rewards
        self.text(screen, "CHOOSE ONE SCROLL", (640, 142), font=self.title, center=True)
        self.text(screen, "Time is paused. Take one; leave the other behind.", (640, 184), MUTED, center=True)
        for index, (key, rect) in enumerate(zip(choice.cache.offers, card_rects())):
            definition = REWARDS[key]
            screen.blit(self.images["ui_scroll_card_background"], rect)
            if choice.selected == index:
                screen.blit(self.images["ui_selection_border"], rect.inflate(16, 16))
            icon = self.images[f"icon_{key}"]
            screen.blit(icon, icon.get_rect(center=(rect.centerx, rect.y + 84)))
            self.text(screen, f"{index + 1}  {definition.name}", (rect.centerx, rect.y + 145), INK, center=True)
            if definition.category == "technique":
                rank = rewards.ranks.get(key, 0)
                current, upgraded = rewards.preview(key)
                lines = [f"Rank {RANKS[rank]}  ->  {RANKS[min(3, rank + 1)]}",
                         f"{STAT_LABELS[definition.stat]} {bonus_text(key, min(3, rank + 1))} total",
                         f"{value_text(key, current)}  ->  {value_text(key, upgraded)}",
                         "Lasts this run"]
                if key == "sharpening":
                    lines[2] = "Quick slash: " + lines[2]
                for offset, line in enumerate(lines):
                    self.text(screen, line, (rect.centerx, rect.y + 185 + offset * 30), INK, self.small, True)
            else:
                self.text(screen, "One charge  /  10 seconds", (rect.centerx, rect.y + 185), INK, self.small, True)
                self.wrapped(screen, definition.description, pygame.Rect(rect.x + 34, rect.y + 212, 268, 90))
                self.text(screen, "Store now; activate with Q", (rect.centerx, rect.y + 309), INK, self.small, True)
            if definition.category == "technique":
                label = "SELECTED" if choice.selected == index else "Click to select"
                self.text(screen, label, (rect.centerx, rect.y + 309), INK, self.small, True)
        message = choice.message or "Click a card or press 1 / 2, then confirm."
        if choice.replacing:
            selected = REWARDS[choice.cache.offers[choice.selected]].name
            pygame.draw.rect(screen, INK, (300, 330, 680, 240), border_radius=6)
            pygame.draw.rect(screen, PAPER, (300, 330, 680, 240), width=2, border_radius=6)
            self.text(screen, "REPLACE STORED BURST?", (640, 375), font=self.title, center=True)
            self.text(screen, f"Discard {REWARDS[rewards.stored].name} and store {selected}?", (640, 435), center=True)
            self.text(screen, "This does not activate it. Your active burst stays unchanged.", (640, 480), MUTED, center=True)
            self.text(screen, "Cancel returns to the two scrolls without losing anything.", (640, 520), MUTED, self.small, True)
            message = "Confirm replacement, or cancel to keep your stored burst."
        self.text(screen, message, (640, 608), MINT, self.small, True)
        self.button(screen, CANCEL_RECT, "Cancel replacement" if choice.replacing else "Esc  Close unclaimed")
        self.button(screen, CONFIRM_RECT, "Enter  Replace stored" if choice.replacing else "Enter  Confirm scroll", choice.selected is not None)
        self.text(screen, "Burst timer frozen" if rewards.active else "Offers stay the same if you close this screen", (640, 712), MUTED, self.small, True)

    def details(self, screen, world):
        rewards = world.rewards
        values = rewards.effective()
        self.text(screen, "TECHNIQUES / THIS RUN", (640, 460), MINT, center=True)
        for index, (key, definition) in enumerate((item for item in REWARDS.items() if item[1].category == "technique")):
            rank = rewards.ranks.get(key, 0)
            value = value_text(key, getattr(values, definition.stat))
            x, y = 130 + (index // 4) * 600, 489 + (index % 4) * 45
            pygame.draw.rect(screen, PAPER, (x - 35, y, 24, 24))
            screen.blit(self.small_icons[key], (x - 35, y))
            self.text(screen, f"{definition.name} {RANKS[rank]} / {bonus_text(key, rank)}", (x, y))
            self.text(screen, f"{STAT_LABELS[definition.stat]}: {value}", (x, y + 22), MUTED, self.small)
        self.text(screen, "Live values include the active burst. Cooldowns cannot end before their action.", (640, 667), MUTED, self.small, True)
