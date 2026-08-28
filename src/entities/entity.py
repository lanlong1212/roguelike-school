"""
实体基类模块。

功能说明：
    所有可移动/可战斗对象（玩家、敌人、Boss）的基类。
    持有网格坐标 position 与战斗属性 stats，提供移动、渲染接口。
    子类通过覆盖 render() 自定义外观。
"""
from __future__ import annotations

import pygame

from src.core import config
from src.entities.stats import Stats
from src.utils.vector import Vector2


class Entity:
    """实体基类。坐标用 Vector2（浮点），网格运算时取整。"""

    __slots__ = ("position", "stats", "color", "name")

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

    def move_to(self, gx: int, gy: int) -> None:
        """直接移动到瓦片 (gx, gy)。不做合法性校验，由调用方保证。"""
        self.position.x = float(gx)
        self.position.y = float(gy)

    def move_by(self, dx: int, dy: int) -> None:
        """相对移动 (dx, dy) 格。"""
        self.position.x += dx
        self.position.y += dy

    # ========== 绘制 ==========

    def render(self, screen: pygame.Surface, cam_x: float, cam_y: float) -> None:
        """
        在屏幕上绘制实体。默认实现：在瓦片中心画一个略小的矩形。
        子类可覆盖此方法实现精灵/动画。
        """
        ts = config.TILE_SIZE
        sx = int((self.position.x - cam_x) * ts)
        sy = int((self.position.y - cam_y) * ts)
        # 略小于瓦片，留 4px 边距，看起来不顶满
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
