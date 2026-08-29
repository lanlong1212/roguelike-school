"""
游戏主类模块。

功能说明：
    游戏运行的核心，负责初始化 pygame、创建窗口、驱动主循环、
    管理状态栈、分发事件。所有游戏状态通过状态栈组织，栈顶为当前
    活跃状态。主循环每帧执行：事件分发 → 状态更新 → 状态绘制 →
    翻页 → 帧末清理。

字体加载说明：
    pygame-ce 2.5.7 在 Windows 上 SysFont 存在遍历系统字体的 bug，
    因此改用 pygame.font.Font 直接加载微软雅黑 ttc 文件绕过。
"""
import os
import sys
import pygame

from src.core import config
from src.core.input import InputManager

# 微软雅黑字体文件路径（常规 + 粗体）
_FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
_FONT_BOLD_PATH = r"C:\Windows\Fonts\msyhbd.ttc"


def _load_font(size, bold=False):
    """加载字体文件；若指定文件不存在则回退到 pygame 默认字体。"""
    path = _FONT_BOLD_PATH if bold else _FONT_PATH
    if os.path.exists(path):
        return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


class Game:
    """游戏主类：持有窗口、时钟、输入、状态栈等全局资源。"""

    def __init__(self):
        # ========== pygame 初始化 ==========
        pygame.init()
        self.screen = pygame.display.set_mode(
            (config.SCREEN_WIDTH, config.SCREEN_HEIGHT)
        )
        pygame.display.set_caption(config.TITLE)
        self.clock = pygame.time.Clock()
        self.running = False
        self.input = InputManager()
        self._states = []  # 状态栈，栈顶为当前活跃状态

        # ========== 字体 ==========
        self.font = _load_font(24)             # 普通文字
        self.font_small = _load_font(14)       # 小字（角标/tooltip 说明）
        self.font_large = _load_font(48, bold=True)  # 标题文字

    # ========== 状态栈管理 ==========

    def push_state(self, state):
        """压入新状态（暂停当前栈顶），用于叠加场景如暂停菜单。"""
        if self._states:
            self._states[-1].exit()
        self._states.append(state)
        state.enter()

    def pop_state(self):
        """弹出栈顶状态，恢复上一个状态，用于关闭暂停菜单。"""
        if self._states:
            state = self._states.pop()
            state.exit()

    def change_state(self, state):
        """替换栈顶状态，用于直接切换（如菜单→游戏→结算）。"""
        if self._states:
            self._states[-1].exit()
            self._states[-1] = state
        else:
            self._states.append(state)
        state.enter()

    def clear_states(self) -> None:
        """Day 8：清空状态栈（返回主菜单用）。"""
        for s in self._states:
            s.exit()
        self._states.clear()

    @property
    def current_state(self):
        """返回当前活跃状态（栈顶），无状态时返回 None。"""
        return self._states[-1] if self._states else None

    def quit(self):
        """请求退出主循环。"""
        self.running = False

    # ========== 主循环 ==========

    def run(self):
        """启动主循环，持续到 running 为 False。"""
        self.running = True
        while self.running:
            # 帧间隔（秒），用于时间相关的运动计算
            dt = self.clock.tick(config.FPS) / 1000.0

            # ---------- 事件分发 ----------
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                    break
                self.input.handle_event(event)
                if self._states:
                    self._states[-1].handle_event(event)

            # ---------- 逻辑更新与绘制 ----------
            if self._states:
                self._states[-1].update(dt)
                self._states[-1].draw(self.screen)

            # ---------- 翻页与帧末清理 ----------
            pygame.display.flip()
            self.input.end_frame()

        # 退出循环后清理 pygame
        pygame.quit()
        sys.exit()
