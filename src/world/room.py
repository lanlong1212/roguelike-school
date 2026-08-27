"""
房间类模块。

功能说明：
    程序化地牢中的矩形房间数据类，封装尺寸、位置与常用查询方法。
    DungeonGenerator 生成 Room 列表，TileMap 用其填充地面瓦片，
    Floor 用其分配房间类型（战斗/Boss/商店/休息）。房间类型枚举
    定义于此，便于各模块共享。
"""
from enum import Enum, auto

from src.utils.vector import Vector2


class RoomType(Enum):
    """房间类型枚举。BOSS/REST/SHOP/BATTLE 共四种。"""
    START = auto()   # 玩家出生房（内部使用，不标注给玩家）
    BATTLE = auto()  # 战斗房
    BOSS = auto()    # Boss 房
    SHOP = auto()    # 商店房
    REST = auto()    # 休息房


class Room:
    """矩形房间。x1/y1 为左上角瓦片坐标（含），x2/y2 为右下角瓦片坐标（含）。"""

    __slots__ = ("x", "y", "w", "h", "room_type")

    def __init__(self, x: int, y: int, w: int, h: int):
        # 左上角瓦片坐标
        self.x = x
        self.y = y
        # 宽高（瓦片数）
        self.w = w
        self.h = h
        # 房间类型，生成后由 Floor 分配
        self.room_type: RoomType = RoomType.BATTLE

    # ========== 便捷属性 ==========

    @property
    def x1(self) -> int:
        """左边界（含）。"""
        return self.x

    @property
    def y1(self) -> int:
        """上边界（含）。"""
        return self.y

    @property
    def x2(self) -> int:
        """右边界（含）。"""
        return self.x + self.w - 1

    @property
    def y2(self) -> int:
        """下边界（含）。"""
        return self.y + self.h - 1

    def center(self) -> Vector2:
        """返回房间中心点坐标（瓦片坐标，整数 floor）。"""
        cx = self.x + self.w // 2
        cy = self.y + self.h // 2
        return Vector2(cx, cy)

    # ========== 几何查询 ==========

    def intersects(self, other: "Room") -> bool:
        """判断两房间是否有重叠瓦片（含边对边相交）。"""
        return (
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )

    def contains(self, gx: int, gy: int) -> bool:
        """判断瓦片 (gx, gy) 是否在房间内（不包含墙外皮）。"""
        return self.x1 <= gx <= self.x2 and self.y1 <= gy <= self.y2

    def tiles(self):
        """生成房间内所有瓦片坐标 (gx, gy)，用于填地面。"""
        for gy in range(self.y1, self.y2 + 1):
            for gx in range(self.x1, self.x2 + 1):
                yield gx, gy

    def distance_to(self, other: "Room") -> float:
        """两房间中心点之间的欧氏距离。"""
        return self.center().distance_to(other.center())

    def __repr__(self) -> str:
        return (
            f"Room({self.x},{self.y} {self.w}x{self.h} "
            f"type={self.room_type.name})"
        )
