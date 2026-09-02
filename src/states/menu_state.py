"""
主菜单状态模块。

功能说明：
    游戏启动后的首个状态，展示标题"迷城棋局"与开始按钮。
    - 开始游戏：进入新游戏（Level 1）
    - 继续游戏（有存档时显示）：从存档恢复进度
    支持鼠标点击按钮或键盘回车/空格进入 PlayState，Esc 退出游戏。
    按钮带 hover 高亮反馈，提升交互手感。
"""
import pygame

from src.core import config
from src.core import save_manager
from src.states.base_state import BaseState
from src.states.play_state import PlayState


class MenuState(BaseState):
    """主菜单状态：标题展示 + 开始/继续游戏按钮。"""

    def __init__(self, game):
        super().__init__(game)
        cx = config.SCREEN_WIDTH // 2
        # "开始游戏"按钮矩形，水平居中、垂直略偏下
        self.button_rect = pygame.Rect(0, 0, 240, 60)
        self.button_rect.center = (cx, config.SCREEN_HEIGHT // 2 + 40)
        # "继续游戏"按钮（有存档时显示），位于开始按钮下方
        self.continue_rect = pygame.Rect(0, 0, 240, 60)
        self.continue_rect.center = (cx, config.SCREEN_HEIGHT // 2 + 120)
        self.has_save = save_manager.has_save()

    # ========== 生命周期 ==========

    def enter(self):
        # 每次进入菜单刷新存档状态（结算清档后"继续游戏"按钮应消失）
        self.has_save = save_manager.has_save()

    def exit(self):
        pass

    def handle_event(self, event):
        """处理输入：点击按钮/回车开始游戏，Esc 退出。"""
        # 鼠标左键点击按钮区域 → 进入游戏
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.button_rect.collidepoint(event.pos):
                self.game.change_state(PlayState(self.game))
                return
            if self.has_save and self.continue_rect.collidepoint(event.pos):
                self.game.change_state(PlayState(self.game, load_data=save_manager.load_game()))
                return
        # 键盘操作
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN or event.key == pygame.K_SPACE:
                self.game.change_state(PlayState(self.game))
            if event.key == pygame.K_ESCAPE:
                self.game.quit()

    def update(self, dt):
        pass

    # ========== 绘制 ==========

    def draw(self, screen):
        """绘制背景、标题、副标题、按钮、底部提示。"""
        screen.fill(config.DARK_GRAY)

        # ---------- 标题 ----------
        title = self.game.font_large.render("迷城棋局", True, config.COLOR_TEXT_HIGHLIGHT)
        title_rect = title.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2 - 60))
        screen.blit(title, title_rect)

        # ---------- 副标题 ----------
        subtitle = self.game.font.render("Labyrinth Chess", True, config.COLOR_TEXT)
        subtitle_rect = subtitle.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2 - 10))
        screen.blit(subtitle, subtitle_rect)

        # ---------- 开始按钮（带 hover 高亮） ----------
        mouse_pos = pygame.mouse.get_pos()
        hover = self.button_rect.collidepoint(mouse_pos)
        color = config.COLOR_PLAYER if hover else config.GRAY
        pygame.draw.rect(screen, color, self.button_rect, border_radius=8)
        pygame.draw.rect(screen, config.WHITE, self.button_rect, 2, border_radius=8)

        text = self.game.font.render("开始游戏", True, config.COLOR_TEXT)
        text_rect = text.get_rect(center=self.button_rect.center)
        screen.blit(text, text_rect)

        # ---------- 继续按钮（有存档时显示） ----------
        if self.has_save:
            hover2 = self.continue_rect.collidepoint(mouse_pos)
            color2 = (60, 140, 90) if hover2 else (45, 70, 55)
            pygame.draw.rect(screen, color2, self.continue_rect, border_radius=8)
            pygame.draw.rect(screen, config.WHITE, self.continue_rect, 2, border_radius=8)
            text2 = self.game.font.render("继续游戏", True, config.COLOR_TEXT)
            text_rect2 = text2.get_rect(center=self.continue_rect.center)
            screen.blit(text2, text_rect2)

        # ---------- 底部操作提示 ----------
        hint = self.game.font.render("回车/点击开始 · Esc 退出", True, config.LIGHT_GRAY)
        hint_rect = hint.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT - 40))
        screen.blit(hint, hint_rect)
