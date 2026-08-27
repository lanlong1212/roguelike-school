"""
游戏进行中状态模块。

功能说明：
    游戏核心玩法状态，承载地牢探索、回合制战斗、HUD 显示等。
    Day 1 为占位实现，仅显示提示文字与返回主菜单功能；
    Day 2 起将逐步接入程序化地图生成、玩家移动、战斗系统等。
"""
import pygame

from src.core import config
from src.states.base_state import BaseState


class PlayState(BaseState):
    """游戏中状态。Day 1 占位，Day 2 接入地图生成与玩家移动。"""

    def __init__(self, game):
        super().__init__(game)

    # ========== 生命周期 ==========

    def enter(self):
        pass

    def exit(self):
        pass

    def handle_event(self, event):
        """处理输入：Esc 返回主菜单（Day 1 仅此功能）。"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                # 延迟 import 避免与 menu_state 形成循环依赖
                self.game.change_state(__import__(
                    "src.states.menu_state", fromlist=["MenuState"]
                ).MenuState(self.game))

    def update(self, dt):
        pass

    # ========== 绘制 ==========

    def draw(self, screen):
        """Day 1 占位绘制：提示文字 + 返回提示。"""
        screen.fill(config.BLACK)

        # 占位提示
        text = self.game.font.render("游戏中 (Day 1 占位)", True, config.COLOR_TEXT)
        text_rect = text.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2))
        screen.blit(text, text_rect)

        # 操作提示
        hint = self.game.font.render("Esc 返回主菜单", True, config.LIGHT_GRAY)
        hint_rect = hint.get_rect(center=(config.SCREEN_WIDTH // 2, config.SCREEN_HEIGHT // 2 + 40))
        screen.blit(hint, hint_rect)
