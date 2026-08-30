"""
程序化地牢生成器（等分网格布局）。

功能说明：
    Step 1) 把整张地图划分为 cols × rows 等分网格（房间数决定网格形状）。
    Step 2) 每个网格单元中心放一个固定尺寸房间（位置允许少量随机抖动）。
    Step 3) 相邻网格的房间两两直连走廊（横平竖直，带环路，多路线可选）。
    返回房间列表与走廊连线（未分配类型，由 Floor 决定）。

参数控制：
    config.ROOM_FIXED_W / ROOM_FIXED_H 控制房间尺寸（统一大小），
    CORRIDOR_WIDTH 控制走廊宽度（战棋至少 2 格），
    target_rooms 控制输出房间数量。
"""
import math

from src.core import config
from src.utils.rng import RNG
from src.world.room import Room
from src.world.tilemap import TileMap, TileType

CORRIDOR_WIDTH = 2          # 走廊宽度（战棋需要过敌人）


# ========== 生成结果容器 ==========
class DungeonResult:
    """生成结果容器。rooms: 房间列表；corridors: 走廊连线 (Room, Room)。"""

    def __init__(self, rooms: list[Room], corridors: list[tuple[Room, Room]]):
        self.rooms: list[Room] = rooms
        self.corridors: list[tuple[Room, Room]] = corridors


class DungeonGenerator:
    """程序化地牢生成入口（等分网格布局）。"""

    @staticmethod
    def generate(
        map_width: int = config.MAP_MAX_SIZE,
        map_height: int = config.MAP_MAX_SIZE,
        rng: RNG | None = None,
        target_rooms: int = 6,
        room_w: int = config.ROOM_FIXED_W,
        room_h: int = config.ROOM_FIXED_H,
    ) -> DungeonResult:
        """
        生成等分网格布局的房间 + 走廊。
        网格列数取 ceil(sqrt(n))，行数取 ceil(n/cols)，使网格尽量接近方形。
        返回 DungeonResult（含房间列表与走廊连线，类型暂默认为 BATTLE）。
        """
        rng = rng or RNG()
        n = max(1, target_rooms)

        # ========== Step 1: 划分 cols × rows 等分网格 ==========
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        cell_w = map_width / cols
        cell_h = map_height / rows
        # 房间尺寸不能超过网格单元（留 2 格边距）
        rw = min(room_w, int(cell_w) - 2)
        rh = min(room_h, int(cell_h) - 2)

        # ========== Step 2: 每个网格单元中心放一个固定尺寸房间 ==========
        # 格内位置允许少量随机抖动（不超出单元），布局规整但不呆板
        rooms: list[Room] = []
        grid: list[list[Room | None]] = [[None] * cols for _ in range(rows)]
        for i in range(n):
            row, col = divmod(i, cols)
            jitter_x = rng.randint(0, max(0, int(cell_w) - rw - 2))
            jitter_y = rng.randint(0, max(0, int(cell_h) - rh - 2))
            x = int(col * cell_w) + 1 + jitter_x
            y = int(row * cell_h) + 1 + jitter_y
            room = Room(x, y, rw, rh)
            rooms.append(room)
            grid[row][col] = room

        # ========== Step 3: 网格相邻房间两两直连（横向 + 纵向，含环路） ==========
        corridors: list[tuple[Room, Room]] = []
        for row in range(rows):
            for col in range(cols):
                a = grid[row][col]
                if a is None:
                    continue
                if col + 1 < cols and grid[row][col + 1] is not None:
                    corridors.append((a, grid[row][col + 1]))
                if row + 1 < rows and grid[row + 1][col] is not None:
                    corridors.append((a, grid[row + 1][col]))

        return DungeonResult(rooms, corridors)

    @staticmethod
    def carve_tilemap(
        tilemap: TileMap,
        result: DungeonResult,
        rng: RNG | None = None,
    ) -> None:
        """
        根据 DungeonResult 把走廊和房间地面刻入 tilemap。
        Door 瓦片：走廊接触房间边界时自动加 DOOR。
        """
        rng = rng or RNG()
        rooms = result.rooms

        # 1. 填所有房间地面
        for room in rooms:
            tilemap.fill_rect(room.x1, room.y1, room.x2, room.y2, TileType.FLOOR)

        # 2. 按走廊连线直连（相邻网格同行/同列，直线走廊，宽 CORRIDOR_WIDTH）
        for a, b in result.corridors:
            ax, ay = int(a.center().x), int(a.center().y)
            bx, by = int(b.center().x), int(b.center().y)
            if ay == by:  # 同行 → 水平走廊
                for w_off in range(CORRIDOR_WIDTH):
                    yy = ay + w_off
                    if yy < tilemap.height:
                        tilemap.draw_line_h(yy, ax, bx, TileType.FLOOR)
            elif ax == bx:  # 同列 → 垂直走廊
                for w_off in range(CORRIDOR_WIDTH):
                    xx = ax + w_off
                    if xx < tilemap.width:
                        tilemap.draw_line_v(xx, ay, by, TileType.FLOOR)
            else:  # 兜底 L 形（随机抖动导致不同行列时）
                if rng.random() < 0.5:
                    for w_off in range(CORRIDOR_WIDTH):
                        yy = ay + w_off
                        if yy < tilemap.height:
                            tilemap.draw_line_h(yy, ax, bx, TileType.FLOOR)
                    for w_off in range(CORRIDOR_WIDTH):
                        xx = bx + w_off
                        if xx < tilemap.width:
                            tilemap.draw_line_v(xx, ay, by, TileType.FLOOR)
                else:
                    for w_off in range(CORRIDOR_WIDTH):
                        xx = ax + w_off
                        if xx < tilemap.width:
                            tilemap.draw_line_v(xx, ay, by, TileType.FLOOR)
                    for w_off in range(CORRIDOR_WIDTH):
                        yy = by + w_off
                        if yy < tilemap.height:
                            tilemap.draw_line_h(yy, ax, bx, TileType.FLOOR)

        # 3. 自动加 DOOR：在每个房间四周边界外 1 格找地面（走廊），相交点标 DOOR
        for room in rooms:
            door_candidates: list[tuple[int, int]] = []
            # 左右边
            for gy in range(room.y1, room.y2 + 1):
                if tilemap.get_tile(room.x1 - 1, gy) == TileType.FLOOR:
                    door_candidates.append((room.x1, gy))
                if tilemap.get_tile(room.x2 + 1, gy) == TileType.FLOOR:
                    door_candidates.append((room.x2, gy))
            # 上下边
            for gx in range(room.x1, room.x2 + 1):
                if tilemap.get_tile(gx, room.y1 - 1) == TileType.FLOOR:
                    door_candidates.append((gx, room.y1))
                if tilemap.get_tile(gx, room.y2 + 1) == TileType.FLOOR:
                    door_candidates.append((gx, room.y2))
            # 每个方向最多保留一个 DOOR，避免满墙门
            if door_candidates:
                # 每房间随机选 1-2 个候选标为 DOOR
                chosen = rng.sample(
                    door_candidates,
                    k=min(2, len(door_candidates)),
                )
                for gx, gy in chosen:
                    tilemap.set_tile(gx, gy, TileType.DOOR)
