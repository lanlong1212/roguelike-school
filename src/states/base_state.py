"""
游戏状态基类模块。

功能说明：
    定义所有游戏状态（主菜单、游戏中、暂停、结算等）的统一接口。
    采用状态栈模式：Game 维护一个状态栈，栈顶状态为当前活跃状态，
    支持叠加（如暂停状态压在游戏状态之上）。每个状态需实现五个
    生命周期方法，由 Game 在恰当时机调用。
"""
from abc import ABC, abstractmethod


class BaseState(ABC):
    """游戏状态抽象基类。子类必须实现全部抽象方法。"""

    def __init__(self, game):
        # 持有 Game 引用，便于访问屏幕、字体、输入、切换状态等
        self.game = game

    # ========== 生命周期方法 ==========

    @abstractmethod
    def enter(self):
        """进入状态时调用，用于初始化资源/重置数据。"""
        pass

    @abstractmethod
    def exit(self):
        """离开状态时调用，用于释放资源/保存数据。"""
        pass

    @abstractmethod
    def handle_event(self, event):
        """处理 pygame 事件（键盘/鼠标），由 Game 每帧分发。"""
        pass

    @abstractmethod
    def update(self, dt):
        """每帧逻辑更新，dt 为帧间隔秒数。"""
        pass

    @abstractmethod
    def draw(self, screen):
        """每帧绘制到 screen，由 Game 在 update 后调用。"""
        pass
