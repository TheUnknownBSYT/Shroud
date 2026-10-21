"""Arena artwork, HUD, effects, and debug drawing; no gameplay decisions."""
import math
import random
import pygame
from pygame import Vector2
import settings as S
from player import PlayerState, AnimationController, SpriteLibrary
from enemy import EnemyState
from level import Camera, Prop

INK = (20, 31, 32)


PAPER = (231, 235, 220)


MUTED = (150, 171, 160)


RED = (235, 78, 72)


GOLD = (255, 221, 133)


MINT = (139, 236, 200)


class Renderer:
    def __init__(self, world, camera=None) -> None:
        self.sprites = SpriteLibrary()
        self.animation = AnimationController(self.sprites.animations)
        self.last_action = -1
        self.font = pygame.font.Font(None, 24)
        self.small = pygame.font.Font(None, 20)
        self.title = pygame.font.Font(None, 44)
        self.large = pygame.font.Font(None, 62)
        # Opaque layers prevent transparent sprite pixels making holes in the pause overlay.
        self.scene = pygame.Surface((S.WIDTH, S.HEIGHT), depth=24)
        self.camera = camera if camera is not None else Camera(world.room.bounds)
        self.environment = {}
        names = set(world.room.tiles.values()) | {"floor_earth_01", "wall", "fence"}
        names.update(prop.asset for prop in world.room.props + world.room.decorations)
        names.update(enemy.sprite for enemy in world.enemies)
        for name in names:
            path = S.ENVIRONMENT_ROOT / f"env_training_{name}.png"
            if not name.endswith(("_01", "_02")):
                path = S.ENVIRONMENT_ROOT / f"env_training_{name}_01.png"
            source = pygame.image.load(path).convert_alpha()
            size = tuple(round(value * S.ENVIRONMENT_SCALE) for value in source.get_size())
            self.environment[name, 0] = pygame.transform.smoothscale(source, size)
        self.outer_floor = self.environment["floor_earth_01", 0].copy()
        self.outer_floor.fill((140, 165, 145, 255), special_flags=pygame.BLEND_RGBA_MULT)
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

    def point(self, position):
        return self.camera.world_to_screen(position)

    def _asset(self, name, angle=0):
        if (name, angle) not in self.environment:
            self.environment[name, angle] = pygame.transform.rotate(self.environment[name, 0], angle)
        return self.environment[name, angle]

    def _ground(self, world):
        self.scene.fill(INK)
        self.scene.set_clip(self.camera.viewport)
        visible = self.camera.visible_rect
        tile = S.TILE_SIZE
        origin = self.point((0, 0))
        for y in range(math.floor(visible.top / tile), math.ceil(visible.bottom / tile)):
            for x in range(math.floor(visible.left / tile), math.ceil(visible.right / tile)):
                name = world.room.tiles.get((x, y))
                image = self._asset(name) if name else self.outer_floor
                # Round the shared origin once so neighboring tiles never leave a seam.
                self.scene.blit(image, (round(origin.x) + x * tile, round(origin.y) + y * tile))
        for prop in world.room.decorations:
            if visible.colliderect(prop.rect):
                self._prop(prop, world)
        if world.room.data:
            for text, x, y in world.room.data["signs"]:
                position = Vector2(x, y) * tile
                if visible.collidepoint(position):
                    self.text(self.scene, text, self.point(position), PAPER, self.small)

    def _prop(self, prop, world):
        image = self._asset(prop.asset, prop.angle)
        if prop.asset == "tree" and prop.rect.collidepoint(world.player.position):
            image = image.copy()
            image.set_alpha(105)
        self.scene.blit(image, image.get_rect(center=self.point(prop.position)))

    def draw(self, screen, world, debug, fps, paused):
        self._ground(world)
        visible = self.camera.visible_rect.inflate(180, 180)
        for enemy in world.enemies:
            if enemy.state == EnemyState.ATTACK and visible.collidepoint(enemy.position):
                position = self.point(enemy.position)
                tip = position + enemy.aim * 220
                pygame.draw.line(self.scene, (157, 119, 92), position, tip, 1)
                progress = 1 - enemy.timer / S.ENEMY_TELEGRAPH
                pygame.draw.circle(self.scene, GOLD, position, int(42 - progress * 10), 2)
        for position, frame, age in self.trails:
            ghost = frame.copy()
            ghost.set_alpha(int(100 * age / .16))
            self.scene.blit(ghost, ghost.get_rect(center=self.point(position)))
        objects = []
        for prop in world.room.props:
            if visible.colliderect(prop.rect):
                bodies = prop.colliders()
                depth = max(body.bottom for body in bodies) if bodies else prop.position.y
                objects.append((depth, "prop", prop))
        for enemy in world.enemies:
            if visible.collidepoint(enemy.position):
                objects.append((enemy.position.y + 24, "enemy", enemy))
        objects.append((world.player.position.y + 24, "player", world.player))
        if world.echo is not None:
            objects.append((world.echo.position.y + 24, "echo", world.echo))
        for _, kind, entity in sorted(objects, key=lambda item: item[0]):
            if kind == "prop":
                self._prop(entity, world)
            elif kind == "enemy":
                self._enemy(entity)
            elif kind == "echo":
                self._echo(entity)
            else:
                self._player(world)
        for name, rect in world.room.gates:
            if name in world.room.open_gates or not visible.colliderect(rect):
                continue
            vertical = rect.height > rect.width
            count = round(max(rect.size) / S.TILE_SIZE)
            for i in range(count):
                position = Vector2(rect.center)
                position[1 if vertical else 0] = (rect.top if vertical else rect.left) + (i + .5) * S.TILE_SIZE
                self._prop(Prop("fence", position, 90 if vertical else 0), world)
        for projectile in world.projectiles:
            if not visible.collidepoint(projectile.position):
                continue
            position = self.point(projectile.position)
            if projectile.kind == "shuriken":
                star = pygame.transform.rotate(self.sprites.shuriken, -world.time * 950)
                self.scene.blit(star, star.get_rect(center=position))
            elif projectile.velocity.length_squared():
                color = MINT if projectile.team == "player" else GOLD
                tail = position - projectile.velocity.normalize() * 17
                pygame.draw.line(self.scene, (84, 100, 83), tail, position, 7)
                pygame.draw.line(self.scene, color, tail, position, 3)
                pygame.draw.circle(self.scene, PAPER, position, 4)
        self._impacts(world)
        self.scene.set_clip(None)
        screen.fill(INK)
        offset = (self.rng.uniform(-world.shake, world.shake), self.rng.uniform(-world.shake, world.shake))
        screen.blit(self.scene, offset)
        self._hud(screen, world)
        if debug:
            draw_debug(screen, world, self.small, fps, self.camera)
        if world.complete:
            self._completion(screen, world)
        elif paused or not world.player.alive:
            shade = pygame.Surface((S.WIDTH, S.HEIGHT), pygame.SRCALPHA)
            shade.fill((12, 22, 23, 170))
            screen.blit(shade, (0, 0))
            title = "PAUSED" if paused else "BACK TO THE SHADOWS"
            subtitle = "P to resume  /  R to restart" if paused else "R to restart the training grounds"
            for text, font, y, color in ((title, self.large, 343, PAPER), (subtitle, self.font, 404, MINT)):
                label = font.render(text, True, color)
                screen.blit(label, label.get_rect(center=(S.WIDTH / 2, y)))

    def _completion(self, screen, world):
        shade = pygame.Surface((S.WIDTH, S.HEIGHT), pygame.SRCALPHA)
        shade.fill((12, 22, 23, 225))
        screen.blit(shade, (0, 0))
        minutes, seconds = divmod(int(world.elapsed), 60)
        rows = ["TRAINING COMPLETE", f"{minutes:02}:{seconds:02}",
                f"Targets defeated    {world.stats['targets']}",
                f"Damage taken    {world.stats['damage']}",
                f"Deflections    {world.stats['deflections']}",
                f"Echo-assisted hits    {world.stats['echo_hits']}", "R to train again   /   ESC to quit"]
        for i, text in enumerate(rows):
            font = self.large if i == 0 else self.font
            label = font.render(text, True, MINT if i in (0, 6) else PAPER)
            screen.blit(label, label.get_rect(center=(S.WIDTH / 2, 245 + i * 49)))

    def _enemy(self, enemy):
        position = self.point(enemy.position)
        image = self._asset(enemy.sprite)
        if not enemy.alive:
            image = pygame.transform.rotate(image, 90)
            image.set_alpha(75)
        elif enemy.flash > 0:
            image = image.copy()
            image.fill((150, 150, 130, 0), special_flags=pygame.BLEND_RGBA_ADD)
        self.scene.blit(image, image.get_rect(center=position))
        if enemy.alive:
            pygame.draw.rect(self.scene, INK, (position.x - 25, position.y - 39, 50, 4), border_radius=2)
            pygame.draw.rect(self.scene, RED, (position.x - 25, position.y - 39,
                             50 * enemy.health / enemy.max_health, 4), border_radius=2)
            if enemy.shooting:
                pygame.draw.circle(self.scene, GOLD if enemy.state == EnemyState.ATTACK else RED,
                                   position + enemy.aim * 14, 4)

    def _player(self, world) -> None:
        player, pos = world.player, self.point(world.player.position)
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
        aim = player.aim_direction if player.mouse_aiming else player.facing
        marker = pos + aim * 42
        perpendicular = Vector2(-aim.y, aim.x)
        if player.alive:
            pygame.draw.polygon(self.scene, MINT, [marker + aim * 7,
                                marker - aim * 4 + perpendicular * 4,
                                marker - aim * 4 - perpendicular * 4])
            self._aim_guide(player, aim)
        if player.attack is not None and player.attack.kind == "slash":
            angle = math.atan2(-player.facing.y, player.facing.x)
            reach = player.attack.reach
            rect = pygame.Rect(0, 0, reach * 2, reach * 2)
            rect.center = pos
            pygame.draw.arc(self.scene, MINT if player.action_charge > 0.5 else PAPER,
                            rect, angle - math.pi / 2, angle + math.pi / 2,
                            4 if player.damage_active else 1)
        if player.parry_active:
            angle = math.atan2(-player.facing.y, player.facing.x)
            rect = pygame.Rect(0, 0, S.PARRY_REACH * 2, S.PARRY_REACH * 2)
            rect.center = pos
            pygame.draw.arc(self.scene, GOLD, rect, angle - math.pi / 2, angle + math.pi / 2, 3)

    def _aim_guide(self, player, aim):
        if player.held_action is None:
            return
        pos, progress = self.point(player.position), player.hold_progress
        color = MINT if progress >= 1 else GOLD
        if player.held_action == "throw":
            # The guide includes the star's 24-pixel spawn offset.
            distance = S.SHURIKEN_RANGE + 24
            spread = S.SHURIKEN_SPREAD * (1 - progress)
            for sign in (-1, 1):
                direction = aim.rotate(sign * spread)
                pygame.draw.aaline(self.scene, color, pos + direction * 49, pos + direction * distance)
            tip = pos + aim * distance
            pygame.draw.circle(self.scene, color, tip, 5, 1)
            label = "PRECISE" if progress >= 1 else f"FOCUS {progress:.0%}"
        else:
            reach = S.SLASH_REACH * (1 + progress * (S.SLASH_CHARGE_REACH - 1))
            angle = math.atan2(-aim.y, aim.x)
            rect = pygame.Rect(0, 0, reach * 2, reach * 2)
            rect.center = pos
            pygame.draw.arc(self.scene, color, rect, angle - math.pi / 2, angle + math.pi / 2, 2)
            label = "CHARGED" if progress >= 1 else f"CHARGE {progress:.0%}"
        pygame.draw.rect(self.scene, INK, (pos.x - 30, pos.y + 43, 60, 5), border_radius=2)
        pygame.draw.rect(self.scene, color, (pos.x - 30, pos.y + 43, 60 * progress, 5), border_radius=2)
        text = self.small.render(label, True, color)
        self.scene.blit(text, text.get_rect(center=(pos.x, pos.y + 61)))

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
        self.scene.blit(frame, frame.get_rect(center=self.point(echo.position)))
        marker = pygame.Surface((76, 24), pygame.SRCALPHA)
        pygame.draw.ellipse(marker, (*MINT, echo.alpha), (1, 1, 74, 22), 1)
        self.scene.blit(marker, (self.point(echo.position).x - 38, self.point(echo.position).y + 16))
        if echo.parry_active:
            angle = math.atan2(-echo.facing.y, echo.facing.x)
            rect = pygame.Rect(0, 0, S.PARRY_REACH * 2, S.PARRY_REACH * 2)
            rect.center = self.point(echo.position)
            pygame.draw.arc(self.scene, MINT, rect, angle - math.pi / 2, angle + math.pi / 2, 2)

    def _impacts(self, world) -> None:
        for effect in world.impacts:
            position = self.point(effect.position)
            progress = 1 - effect.remaining / 0.32
            color = {"parry": MINT, "echo": MINT, "hurt": RED, "defeat": GOLD}.get(effect.kind, PAPER)
            radius = int(8 + progress * (44 if effect.kind == "parry" else 24))
            pygame.draw.circle(self.scene, color, position, radius, max(1, int(3 * (1 - progress))))
            if effect.kind != "wall":
                for i in range(6):
                    direction = Vector2(1, 0).rotate(i * 60 + 20)
                    pygame.draw.line(self.scene, color, position + direction * radius,
                                     position + direction * (radius + 9 * (1 - progress)), 2)
            if effect.kind == "parry":
                label = self.font.render("DEFLECT", True, INK)
                rect = label.get_rect(center=(position.x, position.y - 42 - progress * 12))
                pygame.draw.rect(self.scene, MINT, rect.inflate(16, 8), border_radius=3)
                self.scene.blit(label, rect)

    def _hud(self, screen: pygame.Surface, world) -> None:
        pygame.draw.rect(screen, INK, (0, 0, S.WIDTH, 127))
        pygame.draw.rect(screen, INK, (0, 737, S.WIDTH, 63))
        pygame.draw.rect(screen, RED, (48, 30, 6, 37), border_radius=2)
        self.text(screen, "SHROUD", (69, 26), PAPER, self.title)
        self.text(screen, world.room.area_at(world.player.position)[0].upper(), (71, 72), MUTED, self.small)
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
        self.text(screen, self._objective(world), (48, 108), MUTED, self.small)
        self.text(screen, "WASD / ARROWS   Move", (48, 758), PAPER, self.small)
        self.text(screen, "LMB  Charge   RMB  Focus   J / K  Quick attacks", (306, 758), MUTED, self.small)
        self.text(screen, "R  Restart   P  Pause   F1  Debug   ESC  Quit", (899, 758), PAPER, self.small)

    def _objective(self, world):
        area, objective = world.room.area_at(world.player.position)
        if area == "Combat courtyard" and "courtyard" in world.room.open_gates:
            objective = "North gate open — follow the path"
        elif area == "Final challenge" and "final" in world.room.open_gates:
            objective = "West gate open — reach the exit garden"
        groups = {name for name, _ in world.room.gates}
        remaining = sum(enemy.alive and enemy.group in groups for enemy in world.enemies)
        return f"{objective}   /   {remaining} marked targets left   /   {int(world.elapsed)}s"


def draw_debug(surface: pygame.Surface, world, font: pygame.font.Font, fps: float, camera) -> None:
    player = world.player
    point = camera.world_to_screen
    surface.set_clip(camera.viewport)
    for entity in [player, *world.enemies]:
        if entity.alive:
            pygame.draw.circle(surface, (85, 245, 209), point(entity.position), entity.radius, 1)
    for wall in world.room.walls_near(camera.visible_rect):
        if camera.visible_rect.colliderect(wall):
            pygame.draw.rect(surface, (255, 194, 74), wall.move(point((0, 0))), 1)
    if player.damage_active:
        reach = player.attack.reach if player.attack.kind == "slash" else player.radius + 10
        pygame.draw.circle(surface, (255, 92, 97), point(player.position), reach, 1)
        pygame.draw.line(surface, (255, 92, 97), point(player.position), point(player.position + player.facing * reach), 2)
    if player.parry_active:
        pygame.draw.circle(surface, (251, 237, 136), point(player.position), S.PARRY_REACH, 2)
    for projectile in world.projectiles:
        pygame.draw.circle(surface, (255, 255, 255), point(projectile.position), projectile.radius, 1)
        pygame.draw.line(surface, (255, 255, 255), point(projectile.previous), point(projectile.position), 1)
    for position in [world.room.spawn, *world.room.enemy_spawns]:
        if camera.visible_rect.collidepoint(position):
            pygame.draw.circle(surface, GOLD, point(position), 8, 1)
    pygame.draw.rect(surface, MINT, world.room.bounds.move(point((0, 0))), 2)
    lines = [f"WORLD {player.position.x:.1f}, {player.position.y:.1f}",
             f"CAMERA {camera.offset.x:.1f}, {camera.offset.y:.1f}", f"{fps:5.1f} FPS  |  simulation 120 Hz", f"STATE  {player.state.name}  {player.state_time:.3f}s",
             f"VELOCITY  {player.velocity.x:.1f}, {player.velocity.y:.1f}",
             f"DASH  {player.cooldowns['dash']:.2f}s  |  SLASH  {player.cooldowns['slash']:.2f}s",
             f"PARRY  {'ACTIVE' if player.parry_active else 'closed'} / {S.PARRY_WINDOW:.2f}s",
             f"HITBOX  {'active' if player.damage_active else 'off'}  |  projectiles {len(world.projectiles)}",
             "MINT: hurtboxes   RED: reach (front arc)   GOLD: parry"]
    echo = world.echo
    if echo is not None:
        position = point(echo.position)
        pygame.draw.line(surface, MINT, position - Vector2(8, 0), position + Vector2(8, 0), 2)
        pygame.draw.line(surface, MINT, position - Vector2(0, 8), position + Vector2(0, 8), 2)
        if echo.damage_active:
            pygame.draw.circle(surface, MINT, position, echo.attack.reach, 1)
            pygame.draw.line(surface, MINT, position, position + echo.facing * echo.attack.reach, 2)
        if echo.parry_active:
            pygame.draw.circle(surface, GOLD, position, S.PARRY_REACH, 1)
        lines.append(f"ECHO  {echo.state.name}  /  {echo.timer:.2f}s")
        lines.append(f"AT  {echo.position.x:.0f}, {echo.position.y:.0f}  /  HITBOX {'active' if echo.damage_active else 'off'}")
    else:
        lines.append("ECHO  none")
    surface.set_clip(None)
    panel = pygame.Surface((440, 17 + len(lines) * 23), pygame.SRCALPHA)
    panel.fill((12, 23, 26, 235))
    surface.blit(panel, (64, 152))
    for i, line in enumerate(lines):
        surface.blit(font.render(line, True, (220, 235, 223)), (77, 162 + i * 23))
