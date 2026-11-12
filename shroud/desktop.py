"""Letterboxed window and logical pointer coordinates; simulation stays 1280×800."""
from pathlib import Path
import pygame
from shroud import interface as UI

class Desktop:
    def __init__(self):
        info=pygame.display.Info()
        scale=min(1., max(.5,min((info.current_w-80)/1280,(info.current_h-100)/800)))
        self.windowed=(round(1280*scale),round(800*scale))
        self.fullscreen=False
        self.window=pygame.display.set_mode(self.windowed,pygame.RESIZABLE)
        self.canvas=pygame.Surface((1280,800))
        icon=pygame.image.load(str(Path(__file__).resolve().parents[1] / 'assets/powerups/icon_lingering_echo.png'))
        pygame.display.set_icon(icon)
        self.layout()

    def layout(self):
        w,h=self.window.get_size()
        self.scale=min(w/1280,h/800)
        self.viewport=pygame.Rect(0,0,round(1280*self.scale),round(800*self.scale))
        self.viewport.center=(w//2,h//2)

    def point(self,pos):
        return ((pos[0]-self.viewport.x)/self.scale,(pos[1]-self.viewport.y)/self.scale)

    def events(self,events):
        result=[]
        for event in events:
            if event.type==pygame.VIDEORESIZE and not self.fullscreen:
                self.windowed=(max(960,event.w),max(600,event.h))
                self.window=pygame.display.set_mode(self.windowed,pygame.RESIZABLE)
                self.layout()
            elif event.type==pygame.KEYDOWN and event.key==pygame.K_F11:
                previous=self.fullscreen
                try:
                    self.fullscreen=not previous
                    self.window=pygame.display.set_mode((0,0) if self.fullscreen else self.windowed,
                                                       pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE)
                except pygame.error:
                    self.fullscreen=False
                    self.window=pygame.display.set_mode(self.windowed,pygame.RESIZABLE)
                self.layout()
            elif hasattr(event,'pos'):
                data=event.dict.copy();data['pos']=self.point(event.pos)
                result.append(pygame.event.Event(event.type,data))
            else: result.append(event)
        return result

    def begin(self):
        UI.TEXT_TARGET=self.canvas
        UI.TEXT_QUEUE.clear()

    def present(self):
        self.window.fill(UI.INK)
        self.window.blit(pygame.transform.smoothscale(self.canvas,self.viewport.size),self.viewport)
        for message,pos,size,color,serif,center in UI.TEXT_QUEUE:
            image=UI.rendered(message,max(12,round(size*self.scale)),color,serif)
            point=(round(self.viewport.x+pos[0]*self.scale),round(self.viewport.y+pos[1]*self.scale))
            self.window.blit(image,image.get_rect(center=point) if center else point)
        UI.TEXT_TARGET=None
        pygame.display.flip()
