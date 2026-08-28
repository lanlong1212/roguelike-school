"""
玩家角色模块。

功能说明：
    Player 继承 Entity，实现 Day 3 探索模式下的 WASD 移动。
    每次移动一格后，通知 Floor.fog 更新视野。Day 4 起进入战斗模式
    时，移动改为消耗 AP 的格子选择（由 play_state 控制）。

操作模式（Day 3）：
    - 探索模式：WASD 一格一格走，撞墙不动，迷雾实时展开
    - 战斗模式（Day 4）：点击高亮格子移动，消耗 AP
"""
from __future__ import annotations

import pygame

from src.core import config
from src.entities.entity import Entity
from src.entities.stats import Stats
from src.utils.vector import Vector2
from src.world.tilemap import TileMap


class Player(Entity):
    """玩家角色。"""

    def __init__(self, position: Vector2 | None = None):
        # 玩家初始数值按 PRD 基线：HP 30 / ATK 6 / DEF 2 / AP 5 / Move 3
        stats = Stats(
            max_hp=30,
            atk=6,
            def_=2,
            max_ap=config.AP_MAX,
            move_range=config.MOVE_RANGE,
        )
        super().__init__(
            position=position,
            stats=stats,
            color=config.COLOR_PLAYER,
            name="Player",
        )

    # ========== 探索模式：WASD 移动 ==========

    def try_move_explore(
        self,
        dx: int,
        dy: int,
        tilemap: TileMap,
    ) -> bool:
        """
        探索模式移动：尝试往 (dx, dy) 方向移动 1 格。
        若目标瓦片不可行走则不动，返回 False；成功返回 True。
        Day 3 不消耗 AP（战斗中才扣）。
        """
        if dx == 0 and dy == 0:
            return False
        target_gx = self.grid_x + dx
        target_gy = self.grid_y + dy
        if not tilemap.is_walkable(target_gx, target_gy):
            return False
        self.move_to(target_gx, target_gy)
        return True

    # ========== 渲染 ==========

    def render(self, screen: pygame.Surface, cam_x: float, cam_y: float) -> None:
        """
        覆盖基类渲染：玩家画一个亮蓝色圆角方块 + 中心白色小点，
        比普通敌人更显眼。
        """
        ts = config.TILE_SIZE
        sx = int((self.position.x - cam_x) * ts)
        sy = int((self.position.y - cam_y) * ts)
        inset = 3
        rect = pygame.Rect(
            sx + inset,
            sy + inset,
            ts - inset * 2,
            ts - inset * 2,
        )
        pygame.draw.rect(screen, self.color, rect, border_radius=8)
        pygame.draw.rect(screen, config.WHITE, rect, 2, border_radius=8)
        # 中心点（朝向指示，Day 3 暂为静态）
        cx = sx + ts // 2
        cy = sy + ts // 2
        pygame.draw.circle(screen, config.WHITE, (cx, cy), 3)
