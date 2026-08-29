"""
实体基类模块。

功能说明：
    所有可移动/可战斗对象（玩家、敌人、Boss）的基类。
    持有网格坐标 position 与战斗属性 stats，提供移动、渲染接口。
    子类通过覆盖 render() 自定义外观。
"""
from __future__ import annotations

import pygame

from src.combat.element import Element
from src.combat.status_effect import StatusEffectContainer
from src.core import config
from src.entities.stats import Stats
from src.utils.vector import Vector2


class Entity:
    """实体基类。坐标用 Vector2（浮点），网格运算时取整。"""

    __slots__ = ("position", "stats", "color", "name", "status_effects", "element_resist",
                 "animator", "facing", "visual_pos", "_move_from", "_move_t", "move_duration")

    def __init__(
        self,
        position: Vector2 | None = None,
        stats: Stats | None = None,
        color: tuple[int, int, int] = config.COLOR_PLAYER,
        name: str = "Entity",
    ):
        self.position: Vector2 = position.copy() if position else Vector2(0, 0)
        self.stats: Stats = stats or Stats()
        self.color: tuple[int, int, int] = color
        self.name: str = name
        # Day 5：状态效果容器
        self.status_effects: StatusEffectContainer = StatusEffectContainer()
        # 元素抗性表：元素 → 倍率（1.0 正常 / 1.25 弱点 / 0.75 抗性）。默认无克制
        self.element_resist: dict[Element, float] = {}
        # 动画：animator 由子类按素材构建；None 时走几何色块渲染
        self.animator: "Animator | None" = None
        self.facing: str = "down"  # up / down / left / right
        # 平滑移动：visual_pos（渲染坐标）向 position（逻辑坐标）插值。
        # 逻辑判定立即用新格子；画面在 move_duration 内滑过去，避免瞬移感。
        self.move_duration: float = config.MOVE_ANIM_DURATION
        self.visual_pos: Vector2 = self.position.copy()
        self._move_from: Vector2 = self.position.copy()
        self._move_t: float = 1.0  # 插值进度 0→1，1.0 表示已到位

    # ========== 网格坐标访问 ==========

    @property
    def grid_x(self) -> int:
        """当前所在瓦片 X（整数）。"""
        return int(self.position.x)

    @property
    def grid_y(self) -> int:
        """当前所在瓦片 Y（整数）。"""
        return int(self.position.y)

    @property
    def grid_pos(self) -> tuple[int, int]:
        """(gx, gy) 整数元组，用于瓦片索引。"""
        return (self.grid_x, self.grid_y)

    # ========== 移动 ==========

    def move_to(self, gx: int, gy: int, instant: bool = False) -> None:
        """
        移动到瓦片 (gx, gy)。不做合法性校验，由调用方保证。

        instant=True 时视觉立即到位（换层/读档等瞬移场景）；
        否则视觉坐标在 move_duration 内从当前位置平滑滑向新格子。
        """
        self.position.x = float(gx)
        self.position.y = float(gy)
        if instant:
            self.visual_pos = self.position.copy()
            self._move_from = self.position.copy()
            self._move_t = 1.0
        else:
            # 从当前视觉位置出发（连续移动时动画衔接不跳变）
            self._move_from = self.visual_pos.copy()
            self._move_t = 0.0

    def move_by(self, dx: int, dy: int) -> None:
        """相对移动 (dx, dy) 格。"""
        self.move_to(self.grid_x + dx, self.grid_y + dy)

    # ========== 平滑移动插值 ==========

    def update_visual(self, dt: float, linear: bool = False) -> None:
        """
        推进视觉坐标插值，每帧由状态层调用。

        linear=True 匀速滑动（长按连续行走，避免每格重复加减速产生顿挫）；
        linear=False ease-out cubic（单格移动/停止收尾，起步停步更自然）。
        """
        if self._move_t >= 1.0:
            return
        self._move_t = min(1.0, self._move_t + dt / max(0.01, self.move_duration))
        t = self._move_t if linear else 1.0 - (1.0 - self._move_t) ** 3
        self.visual_pos.x = self._move_from.x + (self.position.x - self._move_from.x) * t
        self.visual_pos.y = self._move_from.y + (self.position.y - self._move_from.y) * t

    # ========== 朝向与动画 ==========

    def face(self, dx: int, dy: int) -> None:
        """根据移动输入更新朝向（单轴输入即可）。"""
        if dy < 0:
            self.facing = "up"
        elif dy > 0:
            self.facing = "down"
        elif dx < 0:
            self.facing = "left"
        elif dx > 0:
            self.facing = "right"

    def play_anim(self, state: str, restart: bool = False) -> None:
        """
        播放动画。优先尝试带朝向的状态名（attack_down），
        不存在则回退无朝向名（attack，敌人素材）。
        """
        if self.animator is None:
            return
        directed = f"{state}_{self.facing}"
        if self.animator.has(directed):
            self.animator.play(directed, restart)
        else:
            self.animator.play(state, restart)

    # ========== 绘制 ==========

    def render(self, screen: pygame.Surface, cam_x: float, cam_y: float) -> None:
        """
        在屏幕上绘制实体。有动画时绘制当前帧（已缩放至瓦片尺寸），
        否则退回默认色块。
        """
        ts = config.TILE_SIZE
        sx = int((self.visual_pos.x - cam_x) * ts)
        sy = int((self.visual_pos.y - cam_y) * ts)
        if self.animator is not None:
            frame = self.animator.surface
            if frame is not None:
                screen.blit(frame, (sx, sy))
                return
        # 几何色块渲染（无素材时的回退）：略小于瓦片，留边距
        inset = 4
        rect = pygame.Rect(
            sx + inset,
            sy + inset,
            ts - inset * 2,
            ts - inset * 2,
        )
        pygame.draw.rect(screen, self.color, rect, border_radius=6)
        # 黑色描边
        pygame.draw.rect(screen, config.BLACK, rect, 2, border_radius=6)

    def __repr__(self) -> str:
        return (
            f"{self.name}({self.grid_x},{self.grid_y}) "
            f"{self.stats}"
        )
