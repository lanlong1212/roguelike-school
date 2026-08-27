"""
程序化地牢生成器（BSP 二叉空间分割）。

功能说明：
    实现二叉空间分割算法生成房间 + 走廊结构：
    Step 1) 递归二叉切分整张地图矩形，得到一组大小均匀的叶节点。
    Step 2) 在每个叶节点中随机放一个房间，过滤掉重叠的直到恰好 N 个。
    Step 3) 以贪心邻接顺序用 L 形走廊连通所有房间（无孤岛）。
    返回房间列表（未分配类型，由 Floor 决定）与走廊瓦片集合。

参数控制：
    ROOM_MIN_SIZE / ROOM_MAX_SIZE 控制房间大小波动，
    CORRIDOR_WIDTH 控制走廊宽度（战棋至少 2 格），
    TARGET_ROOMS 控制输出房间数量。
"""
from src.core import config
from src.utils.rng import RNG
from src.world.room import Room, RoomType
from src.world.tilemap import TileMap, TileType

# ========== 生成参数 ==========
ROOM_MIN_SIZE = 6           # 房间最小边长
ROOM_MAX_SIZE = config.ROOM_MAX_SIZE  # 房间最大边长 12
SPLIT_THRESHOLD = ROOM_MAX_SIZE + 4    # 子矩形宽/高小于此值停止切分
CORRIDOR_WIDTH = 2          # 走廊宽度（战棋需要过敌人）
TARGET_ROOMS = 6            # MVP 单层房间数


# ========== BSP 叶节点（仅作辅助结构，不暴露） ==========
class _BSPLeaf:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h


def _bsp_split(leaf: _BSPLeaf, rng: RNG, leaves: list[_BSPLeaf]) -> None:
    """递归切分一个矩形，子矩形足够小则停止并加入 leaves。"""
    # 停止条件：任一维度 < SPLIT_THRESHOLD
    if leaf.w < SPLIT_THRESHOLD and leaf.h < SPLIT_THRESHOLD:
        leaves.append(leaf)
        return

    # 决定切向：优先沿长轴切；若两轴相近则随机
    can_split_w = leaf.w >= SPLIT_THRESHOLD
    can_split_h = leaf.h >= SPLIT_THRESHOLD
    if can_split_w and can_split_h:
        vertical = rng.random() < 0.5
    elif can_split_w:
        vertical = True  # 沿 x 轴切（得到左右两半）
    elif can_split_h:
        vertical = False  # 沿 y 轴切（得到上下两半）
    else:
        leaves.append(leaf)
        return

    if vertical:
        # 垂直切（切 x 方向）：比例 [0.4, 0.6] 避免太偏
        ratio = rng.uniform(0.4, 0.6)
        split_x = leaf.x + int(leaf.w * ratio)
        left_w = split_x - leaf.x
        right_w = leaf.x + leaf.w - split_x
        if left_w < ROOM_MIN_SIZE + 2 or right_w < ROOM_MIN_SIZE + 2:
            # 切出来某边太小，放弃切分
            leaves.append(leaf)
            return
        _bsp_split(_BSPLeaf(leaf.x, leaf.y, left_w, leaf.h), rng, leaves)
        _bsp_split(_BSPLeaf(split_x, leaf.y, right_w, leaf.h), rng, leaves)
    else:
        # 水平切（切 y 方向）
        ratio = rng.uniform(0.4, 0.6)
        split_y = leaf.y + int(leaf.h * ratio)
        top_h = split_y - leaf.y
        bottom_h = leaf.y + leaf.h - split_y
        if top_h < ROOM_MIN_SIZE + 2 or bottom_h < ROOM_MIN_SIZE + 2:
            leaves.append(leaf)
            return
        _bsp_split(_BSPLeaf(leaf.x, leaf.y, leaf.w, top_h), rng, leaves)
        _bsp_split(_BSPLeaf(leaf.x, split_y, leaf.w, bottom_h), rng, leaves)


# ========== 走廊瓦片集合（返回给 floor 填门标记） ==========
class DungeonResult:
    """生成结果容器。"""
    def __init__(self, rooms: list[Room]):
        self.rooms: list[Room] = rooms


class DungeonGenerator:
    """程序化地牢生成入口。"""

    @staticmethod
    def generate(
        map_width: int = config.MAP_MAX_SIZE,
        map_height: int = config.MAP_MAX_SIZE,
        rng: RNG | None = None,
        target_rooms: int = TARGET_ROOMS,
    ) -> DungeonResult:
        """
        生成 N 个房间+走廊，结果写入 tilemap。
        返回 DungeonResult（含房间列表，类型暂默认为 BATTLE）。
        """
        rng = rng or RNG()

        # ========== Step 1: BSP 切分得到叶矩形 ==========
        leaves: list[_BSPLeaf] = []
        _bsp_split(_BSPLeaf(0, 0, map_width, map_height), rng, leaves)

        # ========== Step 2: 每个叶节点内放一个房间 ==========
        candidate_rooms: list[Room] = []
        for leaf in leaves:
            # 房间大小：[MIN, min(MAX, leaf.w/h-2)]
            w_min = ROOM_MIN_SIZE
            w_max = min(ROOM_MAX_SIZE, leaf.w - 2)
            h_min = ROOM_MIN_SIZE
            h_max = min(ROOM_MAX_SIZE, leaf.h - 2)
            if w_max < w_min or h_max < h_min:
                continue
            w = rng.randint(w_min, w_max)
            h = rng.randint(h_min, h_max)
            # 在叶节点内偏移 [1, leaf-房间-1]，确保留边
            offset_x = rng.randint(1, leaf.w - w - 1)
            offset_y = rng.randint(1, leaf.h - h - 1)
            candidate_rooms.append(Room(leaf.x + offset_x, leaf.y + offset_y, w, h))

        # ========== Step 3: 去重（去掉重叠房间），恰好 target_rooms 个 ==========
        rng.shuffle(candidate_rooms)
        rooms: list[Room] = []
        for room in candidate_rooms:
            if len(rooms) >= target_rooms:
                break
            # 与已有房间不重叠才加入；留 1 格间距避免贴脸
            expanded = Room(room.x - 1, room.y - 1, room.w + 2, room.h + 2)
            if any(expanded.intersects(r) for r in rooms):
                continue
            rooms.append(room)

        # 若房间不够，尝试减少间距再补（极端情况，小概率）
        attempt = 0
        while len(rooms) < target_rooms and attempt < 50:
            attempt += 1
            w = rng.randint(ROOM_MIN_SIZE, ROOM_MAX_SIZE)
            h = rng.randint(ROOM_MIN_SIZE, ROOM_MAX_SIZE)
            x = rng.randint(2, map_width - w - 2)
            y = rng.randint(2, map_height - h - 2)
            extra = Room(x, y, w, h)
            expanded = Room(x - 1, y - 1, w + 2, h + 2)
            if any(expanded.intersects(r) for r in rooms):
                continue
            rooms.append(extra)

        return DungeonResult(rooms)

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

        # 2. 按房间顺序贪心连走廊：按 x 排序后顺序连，保证无孤岛
        #    先按中心 x 粗略排序，再顺序 0-1, 1-2, ...
        ordered = sorted(rooms, key=lambda r: (r.center().x, r.center().y))
        for i in range(1, len(ordered)):
            a = ordered[i - 1].center()
            b = ordered[i].center()
            ax, ay = int(a.x), int(a.y)
            bx, by = int(b.x), int(b.y)
            # L 形走廊：随机决定先横后竖还是先竖后横
            if rng.random() < 0.5:
                # 先水平再垂直
                for w_off in range(CORRIDOR_WIDTH):
                    yy = ay + w_off
                    if yy >= tilemap.height:
                        continue
                    tilemap.draw_line_h(yy, ax, bx, TileType.FLOOR)
                for w_off in range(CORRIDOR_WIDTH):
                    xx = bx + w_off
                    if xx >= tilemap.width:
                        continue
                    tilemap.draw_line_v(xx, ay, by, TileType.FLOOR)
            else:
                # 先垂直再水平
                for w_off in range(CORRIDOR_WIDTH):
                    xx = ax + w_off
                    if xx >= tilemap.width:
                        continue
                    tilemap.draw_line_v(xx, ay, by, TileType.FLOOR)
                for w_off in range(CORRIDOR_WIDTH):
                    yy = by + w_off
                    if yy >= tilemap.height:
                        continue
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
