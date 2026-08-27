"""主菜单状态：标题 + 开始游戏按钮。"""
import pygame

from src.core import config
from src.states.base_state import BaseState
from src.states.play_state import PlayState


class MenuState(BaseState):
    def __init__(self, game):
        super().__init__(game)
        self.button_rect = pygame.Rect(0, 0, 240, 60)
        self.button_rect.center = (
            config.SCREEN_WIDTH // 2,
            config.SCREEN_HEIGHT // 2 + 40,
        )

    def enter(self):
        pass

    def exit(self):
        pass

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.button_rect.collidepoint(event.pos):
                self.game.change_state(PlayState(self.game))
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                self.game.change_state(PlayState(self.game))
            if event.key == pygame.K_ESCAPE:
                self.game.quit()

    def update(self, dt):
        pass

    def draw(self, screen):
        screen.fill(config.DARK_GRAY)

        title = self.game.font_large.render("迷城棋局", True, config.COLOR_TEXT_HIGHLIGHT)
        title_rect = title.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2 - 60))
        screen.blit(title, title_rect)

        subtitle = self.game.font.render("Labyrinth Chess", True, config.COLOR_TEXT)
        subtitle_rect = subtitle.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2 - 10))
        screen.blit(subtitle, subtitle_rect)

        mouse_pos = pygame.mouse.get_pos()
        hover = self.button_rect.collidepoint(mouse_pos)
        color = config.COLOR_PLAYER if hover else config.GRAY
        pygame.draw.rect(screen, color, self.button_rect, border_radius=8)
        pygame.draw.rect(screen, config.WHITE, self.button_rect, 2, border_radius=8)

        text = self.game.font.render("开始游戏", True, config.COLOR_TEXT)
        text_rect = text.get_rect(center=self.button_rect.center)
        screen.blit(text, text_rect)

        hint = self.game.font.render("回车/点击开始 · Esc 退出", True, config.LIGHT_GRAY)
        hint_rect = hint.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT - 40))
        screen.blit(hint, hint_rect)
