"""
游戏结束状态模块。

功能说明：
    死亡或胜利时显示结算界面：
    - 标题：胜利 / 失败
    - 统计：击杀数、到达楼层、用时、获得货币
    - 按钮：再来一局（回主菜单开始新游戏）

    由 PlayState 在玩家死亡或 Boss 被击败后切换到此状态。
"""
from __future__ import annotations

import pygame

from src.core import config
from src.states.base_state import BaseState
from src.ui.ui_element import Button, Panel, Text


class GameOverState(BaseState):
    """游戏结束/结算状态。"""

    def __init__(
        self,
        game,
        victory: bool = False,
        stats: dict | None = None,
    ):
        super().__init__(game)
        self.victory = victory
        self.stats = stats or {
            "kills": 0,
            "floor": 1,
            "time": "00:00",
            "loot": [],
        }
        sw, sh = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        panel_w, panel_h = 400, 320
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        self.panel = Panel(pygame.Rect(panel_x, panel_y, panel_w, panel_h))

        # 标题
        title = "胜利！" if victory else "你死了"
        title_color = (255, 220, 80) if victory else (255, 80, 80)
        self.title_text = Text(
            pygame.Rect(panel_x, panel_y + 20, panel_w, 48),
            title, color=title_color,
        )

        # 统计文本
        stats_lines = [
            f"击杀数: {self.stats.get('kills', 0)}",
            f"到达楼层: {self.stats.get('floor', 1)}",
            f"用时: {self.stats.get('time', '00:00')}",
        ]
        loot = self.stats.get("loot", [])
        if loot:
            stats_lines.append(f"获得: {', '.join(loot)}")
        self.stats_text = []
        for i, line in enumerate(stats_lines):
            self.stats_text.append(
                Text(
                    pygame.Rect(panel_x + 40, panel_y + 90 + i * 28, panel_w - 80, 24),
                    line, color=(220, 220, 220), center=False,
                )
            )

        # 按钮
        btn_w, btn_h = 240, 40
        btn_x = panel_x + (panel_w - btn_w) // 2
        self.btn_restart = Button(
            pygame.Rect(btn_x, panel_y + panel_h - 60, btn_w, btn_h),
            "再来一局 (空格)", on_click=self._restart,
        )
        self.buttons = [self.btn_restart]

    def enter(self):
        pass

    def exit(self):
        pass

    def _restart(self) -> None:
        """回到主菜单开始新游戏。结算即本局结束，清除存档。"""
        from src.core import save_manager
        from src.states.menu_state import MenuState
        save_manager.clear_save()
        self.game.clear_states()
        self.game.push_state(MenuState(self.game))

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self._restart()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for btn in self.buttons:
                btn.handle_click(event.pos)

    def update(self, dt: float) -> None:
        for btn in self.buttons:
            btn.update(dt)

    def draw(self, screen) -> None:
        # 全屏遮罩
        overlay = pygame.Surface((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        # 面板
        self.panel.draw(screen, self.game.font)
        self.title_text.draw(screen, self.game.font)
        for text in self.stats_text:
            text.draw(screen, self.game.font)
        for btn in self.buttons:
            btn.draw(screen, self.game.font)
