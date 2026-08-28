"""
战争迷雾模块。

功能说明：
    三态迷雾：UNSEEN 未探索（全黑遮罩）、EXPLORED 已探索（半透明遮罩，
    不刷新动态物体）、VISIBLE 当前可见（无遮罩）。每帧由
    update_visibility(player_pos, radius) 根据玩家位置更新。
"""
from enum import IntEnum

from src.core import config
from src.world.tilemap import TileType
from src.utils.vector import Vector2


# ========== 迷雾状态 ==========
class FogState(IntEnum):
    """瓦片迷雾状态。值越小可见性越低。"""
    UNSEEN = 0     # 从未探索
    EXPLORED = 1   # 探索过但不在当前视野
    VISIBLE = 2    # 当前可见


class FogOfWar:
    """与 TileMap 同尺寸的迷雾网格。"""

    # 默认视野半径（瓦片），可在 Floor 初始化时改
    DEFAULT_RADIUS = 8

    def __init__(self, width: int = config.MAP_MAX_SIZE, height: int = config.MAP_MAX_SIZE):
        self.width = width
        self.height = height
        # 全部初始化为未探索
        self._grid: list[list[FogState]] = [
            [FogState.UNSEEN for _ in range(width)] for _ in range(height)
        ]

    # ========== 基础读写 ==========

    def in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < self.width and 0 <= gy < self.height

    def get_state(self, gx: int, gy: int) -> FogState:
        if not self.in_bounds(gx, gy):
            return FogState.UNSEEN
        return self._grid[gy][gx]

    def set_state(self, gx: int, gy: int, state: FogState) -> None:
        if not self.in_bounds(gx, gy):
            return
        self._grid[gy][gx] = state

    # ========== 视野更新 ==========

    def update_visibility(self, player_pos: Vector2, radius: int = DEFAULT_RADIUS,tilemap = None) -> None:
        """
        以玩家为中心、radius 为半径刷新视野。
        原 VISIBLE 但走出视野的瓦片降级为 EXPLORED，保留探索记忆。
        """
        cx, cy = int(player_pos.x), int(player_pos.y)

        # Step 1: 把之前 VISIBLE 的瓦片降级为 EXPLORED（不再可见但记忆地形）
        for gy in range(self.height):
            for gx in range(self.width):
                if self._grid[gy][gx] == FogState.VISIBLE:
                    self._grid[gy][gx] = FogState.EXPLORED

        # Step 2: 以 (cx,cy) 为中心、半径 radius 的圆内，设为 VISIBLE
        # 使用圆方程，扫描一个边长为 2r+1 的包围盒，在内部按距离筛选
        r2 = radius * radius
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx*dx+dy*dy > r2:
                    continue
                gx,gy = cx +dx , cy +dy
                if not self.in_bounds(gx,gy):
                    continue
                if abs(dx) + abs(dy) <= 1 or tilemap is None or self._has_line_of_sight(
                    cx, cy, gx, gy, tilemap
                ):
                    self._grid[gy][gx] = FogState.VISIBLE

        # ========== 射线检测 ==========

    def _line_cells(self, x0: int, y0: int, x1: int, y1: int):
        """
        Bresenham 步进版：生成 (x0,y0)→(x1,y1) 路径上的格子坐标。
        步数取 max(|dx|,|dy|)，每步按比例插值，贴合几何直线。
        """
        dx, dy = x1 - x0, y1 - y0
        n = max(abs(dx), abs(dy))
        if n == 0:
            yield x0, y0
            return
        for i in range(n + 1):
            yield x0 + round(dx * i / n), y0 + round(dy * i / n)

    def _has_line_of_sight(
        self, x0: int, y0: int, x1: int, y1: int, tilemap
    ) -> bool:
        """路径上（不含终点）遇墙 → 不可见。终点是墙也可见（能看到墙面）。"""
        for gx, gy in self._line_cells(x0, y0, x1, y1):
            if gx == x1 and gy == y1:
                break
            if tilemap.get_tile(gx, gy) == TileType.WALL:
                return False
        return True