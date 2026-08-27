"""游戏主类：初始化 pygame、主循环、状态栈管理、事件分发。"""
import os
import sys
import pygame

from src.core import config
from src.core.input import InputManager

_FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
_FONT_BOLD_PATH = r"C:\Windows\Fonts\msyhbd.ttc"


def _load_font(size, bold=False):
    path = _FONT_BOLD_PATH if bold else _FONT_PATH
    if os.path.exists(path):
        return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode(
            (config.SCREEN_WIDTH, config.SCREEN_HEIGHT)
        )
        pygame.display.set_caption(config.TITLE)
        self.clock = pygame.time.Clock()
        self.running = False
        self.input = InputManager()
        self._states = []
        self.font = _load_font(24)
        self.font_large = _load_font(48, bold=True)

    def push_state(self, state):
        if self._states:
            self._states[-1].exit()
        self._states.append(state)
        state.enter()

    def pop_state(self):
        if self._states:
            state = self._states.pop()
            state.exit()
            if self._states:
                self._states[-1].enter()

    def change_state(self, state):
        if self._states:
            self._states[-1].exit()
            self._states[-1] = state
        else:
            self._states.append(state)
        state.enter()

    @property
    def current_state(self):
        return self._states[-1] if self._states else None

    def quit(self):
        self.running = False

    def run(self):
        self.running = True
        while self.running:
            dt = self.clock.tick(config.FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.quit()
                    break
                self.input.handle_event(event)
                if self._states:
                    self._states[-1].handle_event(event)

            if self._states:
                self._states[-1].update(dt)
                self._states[-1].draw(self.screen)

            pygame.display.flip()
            self.input.end_frame()

        pygame.quit()
        sys.exit()
