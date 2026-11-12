"""Real menu boundaries, explicit difficulty and desktop input round-trips."""
import pygame
import pytest
from shroud.game import Game
from shroud.enemy import EnemyState
from shroud.interface import DIFFICULTIES
from shroud import settings as S

@pytest.fixture
def game(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER','dummy')
    pygame.display.init();pygame.font.init()
    g=Game('training_01',biome='grounds',title=True,desktop=True)
    yield g
    pygame.quit()

def key(k): return pygame.event.Event(pygame.KEYDOWN,key=k)

def test_title_difficulty_pause_and_safe_quit(game):
    g=game
    assert g.menu_input([key(pygame.K_RETURN)])
    assert g.menu.page=='difficulty'
    g.menu_input([key(pygame.K_RETURN)])
    assert g.world.difficulty=='gentle' and not g.menu_open
    assert all(e.difficulty==DIFFICULTIES['gentle'][2:] for e in g.world.enemies)
    g.world.retry_checkpoint()
    assert all(e.difficulty==DIFFICULTIES['gentle'][2:] for e in g.world.enemies)
    g.menu_input([key(pygame.K_ESCAPE)])
    assert g.paused and g.menu_open and not getattr(g,'exit_requested',False)
    g.menu.focus=g.menu.options().index('Quit')
    g.menu_input([key(pygame.K_RETURN)])
    assert g.menu.page=='quit' and not getattr(g,'exit_requested',False)
    g.menu_input([key(pygame.K_ESCAPE)])
    assert g.menu.page=='pause'
    assert g.history.records[0]['context']['difficulty']=='gentle'

@pytest.mark.parametrize('size',[(960,600),(1280,800),(1500,900)])
def test_resize_maps_card_and_aim_exactly(game,size):
    d=game.desktop
    d.events([pygame.event.Event(pygame.VIDEORESIZE,w=size[0],h=size[1])])
    for logical in ((0,0),(424,400),(856,660),(1279,799)):
        physical=(d.viewport.x+logical[0]*d.scale,d.viewport.y+logical[1]*d.scale)
        event=d.events([pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=physical,button=1)])[0]
        assert event.pos==pytest.approx(logical)
    game.run(1)

def test_f11_restores_window_and_handles_unsupported_mode(game,monkeypatch):
    d=game.desktop; original=d.windowed
    d.events([key(pygame.K_F11)]); d.events([key(pygame.K_F11)])
    assert not d.fullscreen and d.window.get_size()==original
    real=pygame.display.set_mode
    def mode(size,flags=0):
        if flags & pygame.FULLSCREEN: raise pygame.error('unsupported')
        return real(size,flags)
    monkeypatch.setattr(pygame.display,'set_mode',mode)
    d.events([key(pygame.K_F11)])
    assert not d.fullscreen and d.window.get_size()==original

@pytest.mark.parametrize('difficulty',DIFFICULTIES)
def test_difficulty_changes_enemy_pressure_only(game,difficulty):
    game.menu.difficulty=difficulty;game.load('training_01')
    enemy=next(e for e in game.world.enemies if e.shooting)
    enemy.timer=0;enemy.activation_range=None
    enemy.tick(0,enemy.position+pygame.Vector2(200,0),True)
    warning,pace,speed=DIFFICULTIES[difficulty][2:]
    assert enemy.state==EnemyState.ATTACK and enemy.timer==S.ENEMY_TELEGRAPH*warning
    shot=enemy.tick(enemy.timer,enemy.position+pygame.Vector2(200,0),True)
    assert shot.velocity.length()==pytest.approx(S.ENEMY_PROJECTILE_SPEED*speed)
    assert enemy.timer==S.ENEMY_COOLDOWN*pace
    assert game.rewards.effective().slash_damage==S.SLASH_DAMAGE

def test_desktop_modal_batches_focus_and_retry_buttons(game,monkeypatch):
    from types import SimpleNamespace
    from tools.powerup_lab import configure
    g=game
    g.clock=SimpleNamespace(tick=lambda fps:17,get_fps=lambda:60)
    def frame(events):
        monkeypatch.setattr(pygame.event,'get',lambda:events)
        g.run(1)
    frame([key(pygame.K_RETURN)])
    frame([key(pygame.K_DOWN)])
    frame([key(pygame.K_RETURN),key(pygame.K_j)])
    assert g.world.difficulty=='balanced' and g.world.player.attack is None
    configure(g,burst='haste',offers=('flow','frenzy'))
    frame([key(pygame.K_1),key(pygame.K_RETURN)])
    assert g.choice.replacing
    frame([key(pygame.K_ESCAPE)])
    assert not g.choice.replacing and g.rewards.stored=='haste'
    frame([key(pygame.K_RETURN)]); frame([key(pygame.K_RETURN)])
    frame([key(pygame.K_q)])
    remaining=g.rewards.remaining
    frame([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
    frame([pygame.event.Event(pygame.WINDOWFOCUSGAINED)])
    assert g.paused and g.rewards.remaining==remaining
    frame([key(pygame.K_p)])
    g.world.player.receive_damage(999)
    frame([])
    assert g.menu.page=='retry'
    frame([key(pygame.K_RETURN),key(pygame.K_j)])
    assert g.world.player.alive and g.world.player.attack is None
    assert not g.menu_open

def test_reward_focus_hover_and_selection_are_separate(game):
    from tools.powerup_lab import configure
    game.menu_open=False;game.paused=False
    configure(game,offers=('reach','parry'))
    game.reward_input([key(pygame.K_RIGHT)])
    assert game.choice.focused==0 and game.choice.selected is None
    game.reward_input([key(pygame.K_RETURN)])
    assert game.choice.selected==0 and not game.rewards.ranks
    game.reward_input([key(pygame.K_RIGHT)])
    game.reward_input([pygame.event.Event(pygame.MOUSEMOTION,pos=(400,400),rel=(1,1),buttons=(0,0,0))])
    assert game.choice.focused==1 and game.choice.selected==0
    game.reward_input([key(pygame.K_RETURN)])
    assert game.choice.selected==1 and not game.rewards.ranks
    game.reward_input([key(pygame.K_RETURN)])
    assert game.choice is None and game.rewards.ranks=={'parry':1}
