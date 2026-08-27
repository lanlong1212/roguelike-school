"""游戏状态基类。所有状态需实现 enter/exit/handle_event/update/draw。"""
from abc import ABC, abstractmethod


class BaseState(ABC):
    def __init__(self, game):
        self.game = game

    @abstractmethod
    def enter(self):
        pass

    @abstractmethod
    def exit(self):
        pass

    @abstractmethod
    def handle_event(self, event):
        pass

    @abstractmethod
    def update(self, dt):
        pass

    @abstractmethod
    def draw(self, screen):
        pass
