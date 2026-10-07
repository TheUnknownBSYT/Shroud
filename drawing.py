"""Arena artwork, HUD, effects, and debug drawing; no gameplay decisions."""
import math
import random
import pygame
from pygame import Vector2
import settings as S
from player import PlayerState, AnimationController, SpriteLibrary
from enemy import EnemyState

INK = (20, 31, 32)


PAPER = (231, 235, 220)


MUTED = (150, 171, 160)


RED = (235, 78, 72)


GOLD = (255, 221, 133)


MINT = (139, 236, 200)


class Renderer:
    def __init__(self, world) -> None:
        self.sprites = SpriteLibrary()
        self.animation = AnimationController(self.sprites.animations)
        self.last_action = -1
        self.font = pygame.font.Font(None, 24)
        self.small = pygame.font.Font(None, 20)
        self.title = pygame.font.Font(None, 44)
        self.large = pygame.font.Font(None, 62)
        # Opaque layers prevent transparent sprite pixels making holes in the pause overlay.
        self.scene = pygame.Surface((S.WIDTH, S.HEIGHT), depth=24)
        self.backdrop = self._make_backdrop(world)
        self.trails = []
        self.trail_timer = 0.0
        self.rng = random.Random(6)

    def text(self, surface: pygame.Surface, text: str, position: tuple[float, float],
             color: tuple = PAPER, font: pygame.font.Font | None = None) -> None:
        surface.blit((font or self.font).render(text, True, color), position)

    def reset(self) -> None:
        self.trails.clear()
        self.last_action = -1
        self.animation.elapsed = 0

    def update(self, world, dt: float) -> None:
        player = world.player
        self.animation.play(player.animation_name, restart=player.action_serial != self.last_action)
        self.last_action = player.action_serial
        # Action visuals share the simulation's clock, including startup and active frames.
        if player.state in (PlayerState.DASHING, PlayerState.ATTACKING, PlayerState.THROWING):
            self.animation.elapsed = player.state_time
        else:
            self.animation.update(dt)
        self.trails = [(pos, frame, age - dt) for pos, frame, age in self.trails if age > dt]
        self.trail_timer -= dt
        if player.state == PlayerState.DASHING and self.trail_timer <= 0:
            self.trails.append((player.position.copy(), self.frame.copy(), 0.16))
            self.trail_timer = 0.025

    @property
    def frame(self) -> pygame.Surface:
        return self.sprites.frames[self.animation.name][self.animation.frame_index]

    def _make_backdrop(self, world) -> pygame.Surface:
        surface = pygame.Surface((S.WIDTH, S.HEIGHT), depth=24)
        surface.fill(INK)
        pygame.draw.rect(surface, (45, 61, 57), world.room.bounds.inflate(16, 16), border_radius=12)
        pygame.draw.rect(surface, (140, 154, 140), world.room.bounds, border_radius=5)
        bounds = world.room.bounds
        for y in range(int(bounds.top) + 32, int(bounds.bottom), 64):
            for x in range(int(bounds.left) + 32, int(bounds.right), 64):
                pygame.draw.circle(surface, (119, 138, 124), (x, y), 1)
        for radius in (114, 120):
            pygame.draw.circle(surface, (124, 144, 128), (640, 425), radius, 1)
        pygame.draw.line(surface, (124, 144, 128), (620, 425), (660, 425), 1)
        pygame.draw.line(surface, (124, 144, 128), (640, 405), (640, 445), 1)
        for position in world.room.enemy_spawns:
            pygame.draw.circle(surface, (121, 138, 125), position, 49, 1)
            for angle in range(0, 360, 90):
                direction = Vector2(1, 0).rotate(angle)
                pygame.draw.line(surface, (108, 128, 116), position + direction * 44, position + direction * 53, 2)
        self.text(surface, "01  /  THE COURTYARD", (70, 157), (75, 96, 83), self.small)
        self.text(surface, "TRAINING SENTRIES  /  AUTO RESET", (952, 690), (75, 96, 83), self.small)
        return surface

    def draw(self, screen: pygame.Surface, world, debug: bool, fps: float, paused: bool) -> None:
        self.scene.blit(self.backdrop, (0, 0))
        for enemy in world.enemies:
            if enemy.state == EnemyState.ATTACK:
                tip = enemy.position + enemy.aim * 220
                pygame.draw.line(self.scene, (157, 119, 92), enemy.position, tip, 1)
                progress = 1 - enemy.timer / S.ENEMY_TELEGRAPH
                pygame.draw.circle(self.scene, GOLD, enemy.position, int(42 - progress * 10), 2)
        for pos, frame, age in self.trails:
            ghost = frame.copy()
            ghost.set_alpha(int(100 * age / 0.16))
            self.scene.blit(ghost, (pos.x - S.SPRITE_SIZE / 2, pos.y - S.SPRITE_SIZE / 2))
        # Floor-contact ordering keeps characters behind foreground cover.
        objects = [(wall.bottom, "wall", wall) for wall in world.room.walls]
        objects += [(enemy.position.y, "enemy", enemy) for enemy in world.enemies]
        objects.append((world.player.position.y, "player", world.player))
        if world.echo is not None:
            objects.append((world.echo.position.y, "echo", world.echo))
        for _, kind, entity in sorted(objects, key=lambda item: item[0]):
            if kind == "wall":
                self._wall(entity)
            elif kind == "enemy":
                self._enemy(entity)
            elif kind == "echo":
                self._echo(entity)
            else:
                self._player(world)
        for projectile in world.projectiles:
            if projectile.kind == "shuriken":
                star = pygame.transform.rotate(self.sprites.shuriken, -world.time * 950)
                self.scene.blit(star, star.get_rect(center=projectile.position))
            else:
                color = MINT if projectile.team == "player" else GOLD
                tail = projectile.position - projectile.velocity.normalize() * 17
                pygame.draw.line(self.scene, (84, 100, 83), tail, projectile.position, 7)
                pygame.draw.line(self.scene, color, tail, projectile.position, 3)
                pygame.draw.circle(self.scene, PAPER, projectile.position, 4)
        self._impacts(world)
        screen.fill(INK)
        offset = (self.rng.uniform(-world.shake, world.shake), self.rng.uniform(-world.shake, world.shake))
        screen.blit(self.scene, offset)
        self._hud(screen, world)
        if debug:
            draw_debug(screen, world, self.small, fps)
        if paused or not world.player.alive:
            shade = pygame.Surface((S.WIDTH, S.HEIGHT), pygame.SRCALPHA)
            shade.fill((12, 22, 23, 170))
            screen.blit(shade, (0, 0))
            title = "PAUSED" if paused else "BACK TO THE SHADOWS"
            subtitle = "P to resume  /  R to reset" if paused else "R to reset the courtyard"
            for text, font, y, color in ((title, self.large, 343, PAPER), (subtitle, self.font, 404, MINT)):
                label = font.render(text, True, color)
                screen.blit(label, label.get_rect(center=(S.WIDTH / 2, y)))

    def _wall(self, wall: pygame.FRect) -> None:
        pygame.draw.rect(self.scene, (103, 120, 106), wall.move(7, 9), border_radius=5)
        pygame.draw.rect(self.scene, (61, 81, 73), wall, border_radius=5)
        cap = wall.inflate(-8, -8).move(0, -5)
        pygame.draw.rect(self.scene, (84, 108, 92), cap, border_radius=3)
        pygame.draw.line(self.scene, (123, 142, 121), cap.topleft, cap.topright, 2)
        for y in range(int(cap.top) + 24, int(cap.bottom), 26):
            pygame.draw.line(self.scene, (67, 90, 78), (cap.left, y), (cap.right, y), 1)

    def _enemy(self, enemy) -> None:
        pos = enemy.position
        if not enemy.alive:
            pygame.draw.circle(self.scene, (105, 125, 109), pos, 18, 2)
            label = self.small.render(f"{enemy.timer:.1f}", True, (63, 88, 73))
            self.scene.blit(label, label.get_rect(center=pos))
            return
        pygame.draw.ellipse(self.scene, (105, 123, 107), (pos.x - 26, pos.y + 16, 52, 16))
        pygame.draw.line(self.scene, (72, 69, 55), (pos.x, pos.y), (pos.x, pos.y + 25), 9)
        pygame.draw.circle(self.scene, PAPER if enemy.flash > 0 else (73, 66, 56), pos, 25)
        pygame.draw.circle(self.scene, (167, 127, 86), pos, 20, 3)
        pygame.draw.circle(self.scene, (115, 89, 65), pos, 11, 2)
        pygame.draw.circle(self.scene, GOLD if enemy.state == EnemyState.ATTACK else RED, pos, 5)
        muzzle = pos + enemy.aim * 25
        pygame.draw.line(self.scene, (52, 59, 52), pos + enemy.aim * 11, muzzle, 6)
        pygame.draw.rect(self.scene, (86, 105, 90), (pos.x - 25, pos.y - 40, 50, 4), border_radius=2)
        pygame.draw.rect(self.scene, RED, (pos.x - 25, pos.y - 40, 50 * enemy.health / enemy.max_health, 4), border_radius=2)

    def _player(self, world) -> None:
        player, pos = world.player, world.player.position
        pygame.draw.ellipse(self.scene, (98, 119, 102), (pos.x - 23, pos.y + 20, 46, 14))
        frame = self.frame
        if player.flash > 0:
            frame = frame.copy()
            frame.fill((180, 180, 150, 0), special_flags=pygame.BLEND_RGBA_ADD)
        elif player.invulnerability > 0 and int(world.time * 18) % 2:
            frame = frame.copy()
            frame.set_alpha(125)
        if not player.alive:
            frame = pygame.transform.rotate(frame, 90)
        self.scene.blit(frame, frame.get_rect(center=pos))
        marker = pos + player.facing * 37
        perpendicular = Vector2(-player.facing.y, player.facing.x)
        pygame.draw.polygon(self.scene, (226, 235, 211), [marker + player.facing * 5,
                            marker - player.facing * 3 + perpendicular * 3,
                            marker - player.facing * 3 - perpendicular * 3])
        if player.parry_active:
            angle = math.atan2(-player.facing.y, player.facing.x)
            rect = pygame.Rect(0, 0, S.PARRY_REACH * 2, S.PARRY_REACH * 2)
            rect.center = pos
            pygame.draw.arc(self.scene, GOLD, rect, angle - math.pi / 2, angle + math.pi / 2, 3)

    def _echo(self, echo):
        frames = self.sprites.frames[echo.animation_name]
        animation = self.sprites.animations[echo.animation_name]
        index = int(echo.state_time / animation.frame_duration)
        if animation.looping:
            index %= len(frames)
        else:
            index = min(index, len(frames) - 1)
        frame = frames[index].copy()
        frame.fill((25, 52, 58, 0), special_flags=pygame.BLEND_RGBA_ADD)
        frame.fill((100, 155, 165, 255), special_flags=pygame.BLEND_RGBA_MULT)
        frame.set_alpha(echo.alpha)
        self.scene.blit(frame, frame.get_rect(center=echo.position))
        marker = pygame.Surface((76, 24), pygame.SRCALPHA)
        pygame.draw.ellipse(marker, (*MINT, echo.alpha), (1, 1, 74, 22), 1)
        self.scene.blit(marker, (echo.position.x - 38, echo.position.y + 16))
        if echo.parry_active:
            angle = math.atan2(-echo.facing.y, echo.facing.x)
            rect = pygame.Rect(0, 0, S.PARRY_REACH * 2, S.PARRY_REACH * 2)
            rect.center = echo.position
            pygame.draw.arc(self.scene, MINT, rect, angle - math.pi / 2, angle + math.pi / 2, 2)

    def _impacts(self, world) -> None:
        for effect in world.impacts:
            progress = 1 - effect.remaining / 0.32
            color = {"parry": MINT, "echo": MINT, "hurt": RED, "defeat": GOLD}.get(effect.kind, PAPER)
            radius = int(8 + progress * (44 if effect.kind == "parry" else 24))
            pygame.draw.circle(self.scene, color, effect.position, radius, max(1, int(3 * (1 - progress))))
            if effect.kind != "wall":
                for i in range(6):
                    direction = Vector2(1, 0).rotate(i * 60 + 20)
                    pygame.draw.line(self.scene, color, effect.position + direction * radius,
                                     effect.position + direction * (radius + 9 * (1 - progress)), 2)
            if effect.kind == "parry":
                label = self.font.render("DEFLECT", True, INK)
                rect = label.get_rect(center=(effect.position.x, effect.position.y - 42 - progress * 12))
                pygame.draw.rect(self.scene, MINT, rect.inflate(16, 8), border_radius=3)
                self.scene.blit(label, rect)

    def _hud(self, screen: pygame.Surface, world) -> None:
        pygame.draw.rect(screen, INK, (0, 0, S.WIDTH, 127))
        pygame.draw.rect(screen, INK, (0, 737, S.WIDTH, 63))
        pygame.draw.rect(screen, RED, (48, 30, 6, 37), border_radius=2)
        self.text(screen, "SHROUD", (69, 26), PAPER, self.title)
        self.text(screen, "SHADOW ECHO   /   PROTOTYPE", (71, 72), MUTED, self.small)
        self.text(screen, "VITALITY", (375, 32), MUTED, self.small)
        for i in range(S.PLAYER_HEALTH):
            pygame.draw.rect(screen, RED if i < world.player.health else (57, 72, 66), (376 + i * 23, 57, 17, 8), border_radius=3)
        for x, name, key, duration in ((575, "dash", "SPACE", S.DASH_COOLDOWN),
                                      (782, "slash", "J / LMB", S.SLASH_COOLDOWN),
                                      (1000, "throw", "K / RMB", S.SHURIKEN_COOLDOWN)):
            cooldown = world.player.cooldowns[name]
            self.text(screen, {"dash": "DASH", "slash": "SLASH / DEFLECT", "throw": "SHURIKEN"}[name], (x, 32), PAPER, self.small)
            self.text(screen, key, (x, 55), MUTED, self.small)
            pygame.draw.rect(screen, (51, 70, 63), (x, 80, 170, 3), border_radius=1)
            pygame.draw.rect(screen, MINT if cooldown <= 0 else RED, (x, 80, 170 * max(0, 1 - cooldown / duration), 3), border_radius=1)
        self.text(screen, "Dash leaves a shadow. Your next slash or shuriken repeats from there after a short delay.", (48, 108), MUTED, self.small)
        self.text(screen, "WASD / ARROWS   Move", (48, 758), PAPER, self.small)
        self.text(screen, "Mouse attacks aim at cursor  /  J + K use facing", (306, 758), MUTED, self.small)
        self.text(screen, "R  Reset     P  Pause     F1  Debug     ESC  Quit", (899, 758), PAPER, self.small)


def draw_debug(surface: pygame.Surface, world, font: pygame.font.Font, fps: float) -> None:
    player = world.player
    for entity in [player, *world.enemies]:
        if entity.alive:
            pygame.draw.circle(surface, (85, 245, 209), entity.position, entity.radius, 1)
    for wall in world.room.walls:
        pygame.draw.rect(surface, (255, 194, 74), wall, 1)
    if player.damage_active:
        reach = S.SLASH_REACH if player.attack.kind == "slash" else player.radius + 10
        pygame.draw.circle(surface, (255, 92, 97), player.position, reach, 1)
        pygame.draw.line(surface, (255, 92, 97), player.position, player.position + player.facing * reach, 2)
    if player.parry_active:
        pygame.draw.circle(surface, (251, 237, 136), player.position, S.PARRY_REACH, 2)
    for projectile in world.projectiles:
        pygame.draw.circle(surface, (255, 255, 255), projectile.position, projectile.radius, 1)
        pygame.draw.line(surface, (255, 255, 255), projectile.previous, projectile.position, 1)
    lines = [f"{fps:5.1f} FPS  |  simulation 120 Hz", f"STATE  {player.state.name}  {player.state_time:.3f}s",
             f"VELOCITY  {player.velocity.x:.1f}, {player.velocity.y:.1f}",
             f"DASH  {player.cooldowns['dash']:.2f}s  |  SLASH  {player.cooldowns['slash']:.2f}s",
             f"PARRY  {'ACTIVE' if player.parry_active else 'closed'} / {S.PARRY_WINDOW:.2f}s",
             f"HITBOX  {'active' if player.damage_active else 'off'}  |  projectiles {len(world.projectiles)}",
             "MINT: hurtboxes   RED: reach (front arc)   GOLD: parry"]
    echo = world.echo
    if echo is not None:
        position = echo.position
        pygame.draw.line(surface, MINT, position - Vector2(8, 0), position + Vector2(8, 0), 2)
        pygame.draw.line(surface, MINT, position - Vector2(0, 8), position + Vector2(0, 8), 2)
        if echo.damage_active:
            pygame.draw.circle(surface, MINT, position, S.SLASH_REACH, 1)
            pygame.draw.line(surface, MINT, position, position + echo.facing * S.SLASH_REACH, 2)
        if echo.parry_active:
            pygame.draw.circle(surface, GOLD, position, S.PARRY_REACH, 1)
        lines.append(f"ECHO  {echo.state.name}  /  {echo.timer:.2f}s")
        lines.append(f"AT  {position.x:.0f}, {position.y:.0f}  /  HITBOX {'active' if echo.damage_active else 'off'}")
    else:
        lines.append("ECHO  none")
    panel = pygame.Surface((440, 17 + len(lines) * 23), pygame.SRCALPHA)
    panel.fill((12, 23, 26, 235))
    surface.blit(panel, (64, 152))
    for i, line in enumerate(lines):
        surface.blit(font.render(line, True, (220, 235, 223)), (77, 162 + i * 23))
