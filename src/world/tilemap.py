"""
瓦片地图模块。

功能说明：
    二维网格瓦片地图。整张地图初始化为 WALL，
    地牢生成器把房间和走廊填成 FLOOR/DOOR。提供可行走查询、
    边界检查、按坐标读写瓦片接口，供移动/AI/渲染使用。
"""
from enum import IntEnum

from src.core import config


# ========== 瓦片类型 ==========
class TileType(IntEnum):
    """瓦片类型。值直接作为二维数组的存储值，便于序列化。"""
    WALL = 0    # 墙壁：不可行走
    FLOOR = 1   # 地面：可行走（房间内部/走廊）
    DOOR = 2    # 房门：可行走，特殊视觉
    TRAP = 3    # 陷阱：可行走，踩上触发伤害（后续扩展）
    STAIR = 4   # 下行阶梯：可行走，踩上进入下一层


class TileMap:
    """二维瓦片地图。尺寸由 MAP_MAX_SIZE 控制。"""

    def __init__(self, width: int = config.MAP_MAX_SIZE, height: int = config.MAP_MAX_SIZE):
        self.width = width
        self.height = height
        # 二维 list，全部初始化为墙
        self._grid: list[list[TileType]] = [
            [TileType.WALL for _ in range(width)] for _ in range(height)
        ]

    # ========== 基础读写 ==========

    def in_bounds(self, gx: int, gy: int) -> bool:
        """坐标是否在地图边界内。"""
        return 0 <= gx < self.width and 0 <= gy < self.height

    def get_tile(self, gx: int, gy: int) -> TileType:
        """返回指定瓦片类型；越界返回 WALL。"""
        if not self.in_bounds(gx, gy):
            return TileType.WALL
        return self._grid[gy][gx]

    def set_tile(self, gx: int, gy: int, tile: TileType) -> None:
        """设置指定瓦片；越界静默忽略。"""
        if not self.in_bounds(gx, gy):
            return
        self._grid[gy][gx] = tile

    def fill_rect(
        self,
        x1: int, y1: int, x2: int, y2: int, tile: TileType
    ) -> None:
        """填充矩形区域瓦片（闭区间），用于填房间地面。"""
        for gy in range(max(0, y1), min(self.height, y2 + 1)):
            for gx in range(max(0, x1), min(self.width, x2 + 1)):
                self._grid[gy][gx] = tile

    def draw_line_h(self, y: int, x1: int, x2: int, tile: TileType) -> None:
        """画一条水平线，用于走廊。自动规整 x1/x2 大小。"""
        x_start, x_end = sorted([x1, x2])
        for gx in range(max(0, x_start), min(self.width, x_end + 1)):
            if 0 <= y < self.height:
                self._grid[y][gx] = tile

    def draw_line_v(self, x: int, y1: int, y2: int, tile: TileType) -> None:
        """画一条垂直线，用于走廊。自动规整 y1/y2 大小。"""
        y_start, y_end = sorted([y1, y2])
        for gy in range(max(0, y_start), min(self.height, y_end + 1)):
            if 0 <= x < self.width:
                self._grid[gy][x] = tile

    # ========== 行走查询 ==========

    def is_walkable(self, gx: int, gy: int) -> bool:
        """瓦片可否行走。越界与墙返回 False。"""
        t = self.get_tile(gx, gy)
        return t in (TileType.FLOOR, TileType.DOOR, TileType.TRAP, TileType.STAIR)

    # ========== 战棋视线判定 ==========

    def _line_cells(self, x0: int, y0: int, x1: int, y1: int):
        """
        Bresenham 步进：生成 (x0,y0)→(x1,y1) 路径格子（含两端）。
        步数取 max(|dx|,|dy|)，每步按比例插值，贴合几何直线。
        """
        dx, dy = x1 - x0, y1 - y0
        n = max(abs(dx), abs(dy))
        if n == 0:
            yield x0, y0
            return
        for i in range(n + 1):
            yield x0 + round(dx * i / n), y0 + round(dy * i / n)

    def has_line_of_sight(self, x0: int, y0: int, x1: int, y1: int) -> bool:
        """
        战斗视线判定：两端点之间路径上的中间格遇墙 → 视线被挡。
        相邻格（距离 ≤1）无中间格，恒为可见。
        """
        for gx, gy in self._line_cells(x0, y0, x1, y1):
            # 跳过起点与终点：起点是自身格，终点是目标所在格
            if (gx, gy) == (x0, y0) or (gx, gy) == (x1, y1):
                continue
            if self.get_tile(gx, gy) == TileType.WALL:
                return False
        return True

    # ========== 遍历 ==========

    def __iter__(self):
        """遍历所有瓦片：yield (gx, gy, tile_type)。"""
        for gy in range(self.height):
            for gx in range(self.width):
                yield gx, gy, self._grid[gy][gx]
