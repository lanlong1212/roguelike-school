"""游戏进行中状态。Day 1 占位实现，Day 2 接入地图生成。"""
import pygame

from src.core import config
from src.states.base_state import BaseState


class PlayState(BaseState):
    def __init__(self, game):
        super().__init__(game)

    def enter(self):
        pass

    def exit(self):
        pass

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.game.change_state(__import__(
                    "src.states.menu_state", fromlist=["MenuState"]
                ).MenuState(self.game))

    def update(self, dt):
        pass

    def draw(self, screen):
        screen.fill(config.BLACK)
        text = self.game.font.render("游戏中 (Day 1 占位)", True, config.COLOR_TEXT)
        text_rect = text.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2))
        screen.blit(text, text_rect)
        hint = self.game.font.render("Esc 返回主菜单", True, config.LIGHT_GRAY)
        hint_rect = hint.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2 + 40))
        screen.blit(hint, hint_rect)
