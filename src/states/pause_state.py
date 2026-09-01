"""
暂停状态模块。

功能说明：
    Esc 键触发暂停，叠加在 PlayState 之上（用状态栈压入）。
    暂停时 PlayState 不再 update/draw（由 Game 的状态栈控制），
    PauseState 负责显示暂停菜单，并处理：
    - ESC / 继续：弹出自身，回到 PlayState
    - 返回主菜单：清空状态栈，回到 MenuState
"""
from __future__ import annotations

import pygame

from src.states.base_state import BaseState
from src.ui.help_panel import HelpPanel
from src.ui.menu import PauseMenu


class PauseState(BaseState):
    """暂停状态。"""

    def __init__(self, game, play_state=None):
        super().__init__(game)
        self.play_state = play_state  # 关联的 PlayState（用于恢复）
        self.help_panel: HelpPanel | None = None  # 图鉴面板（覆盖层，不压状态栈）
        self.menu = PauseMenu(
            on_resume=self._resume,
            on_quit=self._quit_to_menu,
            on_help=self._open_help,
        )

    def enter(self):
        pass

    def exit(self):
        pass

    def _open_help(self) -> None:
        """打开图鉴（叠在暂停菜单之上）。"""
        # 传入玩家引用：遗物页按 owned_relics 显示解锁状态
        self.help_panel = HelpPanel(
            player=self.play_state.player if self.play_state else None
        )

    def _resume(self) -> None:
        """继续游戏：弹出 PauseState。"""
        self.game.pop_state()

    def _quit_to_menu(self) -> None:
        """返回主菜单：清空状态栈。"""
        from src.states.menu_state import MenuState
        self.game.clear_states()
        self.game.push_state(MenuState(self.game))

    def handle_event(self, event: pygame.event.Event) -> None:
        # 图鉴打开时优先处理（F1/Esc/点X/点面板外关闭；左右键切标签）
        if self.help_panel is not None:
            if not self.help_panel.handle_event(event):
                self.help_panel = None
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_F1:
                self._open_help()
            elif event.key == pygame.K_ESCAPE:
                self._resume()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.menu.handle_click(event.pos)

    def update(self, dt: float) -> None:
        if self.help_panel is not None:
            self.help_panel.update(dt)
            return
        self.menu.update(dt)

    def draw(self, screen) -> None:
        # 先画底层的 PlayState（保留画面）
        if self.play_state:
            self.play_state.draw(screen)
        # 再画暂停菜单
        self.menu.draw(screen, self.game.font)
        # 图鉴叠在最上层
        if self.help_panel is not None:
            self.help_panel.update(0)
            self.help_panel.draw(screen, self.game.font, self.game.font_small)
