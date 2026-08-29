"""
动画组件模块。

功能说明：
    Animator 持有多个命名动画状态（帧列表 + 帧率 + 是否循环），
    play() 切换状态，update(dt) 按帧率推进，surface 返回当前帧。

状态行为：
    - 循环状态（idle/walk）：播到末尾后从头继续
    - 非循环状态（attack/hurt/death）：播到末尾停在最后一帧；
      若配置了 on_finish 则自动切到指定状态（如 attack → idle）
    - is_finished：非循环状态播完且无 on_finish（死亡动画停留用）
"""
from __future__ import annotations

import pygame


class Animator:
    """实体动画状态机。"""

    __slots__ = ("states", "current", "_t", "_index", "_finished")

    def __init__(self):
        # 状态名 → (帧列表, 帧率 fps, 是否循环, 结束后切换的状态名或 None)
        self.states: dict[str, tuple[list[pygame.Surface], float, bool, str | None]] = {}
        self.current: str = ""      # 当前状态名（"" 表示无动画，走几何渲染）
        self._t: float = 0.0        # 当前状态累计时间
        self._index: int = 0        # 当前帧下标
        self._finished: bool = False  # 非循环状态是否已播完

    # ========== 状态注册 ==========

    def add(
        self,
        name: str,
        frames: list[pygame.Surface],
        fps: float,
        loop: bool = True,
        on_finish: str | None = None,
    ) -> None:
        """注册一个动画状态。frames 为空则忽略。"""
        if frames:
            self.states[name] = (frames, max(0.01, fps), loop, on_finish)

    def has(self, name: str) -> bool:
        return name in self.states

    # ========== 状态切换 ==========

    def play(self, name: str, restart: bool = False) -> None:
        """切换动画。同名且不 restart 则继续播（跨帧平滑）。"""
        if name not in self.states:
            return
        if name == self.current and not restart:
            return
        self.current = name
        self._t = 0.0
        self._index = 0
        self._finished = False

    # ========== 帧推进 ==========

    def update(self, dt: float) -> None:
        """推进当前动画。非循环播完停在末帧，或自动切 on_finish 状态。"""
        if self.current not in self.states:
            return
        frames, fps, loop, on_finish = self.states[self.current]
        self._t += dt
        step = 1.0 / fps
        while self._t >= step:
            self._t -= step
            self._index += 1
            if self._index < len(frames):
                continue
            if loop:
                self._index = 0
            else:
                self._index = len(frames) - 1
                self._finished = True
                if on_finish is not None and on_finish in self.states:
                    self.play(on_finish)
                return

    @property
    def is_finished(self) -> bool:
        """非循环动画播完且不会自动切换（死亡动画停留判定）。"""
        return self._finished

    # ========== 当前帧 ==========

    @property
    def surface(self) -> pygame.Surface | None:
        """当前帧图像；无动画状态返回 None。"""
        if self.current not in self.states:
            return None
        return self.states[self.current][0][self._index]
