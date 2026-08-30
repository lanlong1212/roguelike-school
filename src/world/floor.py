"""
楼层管理模块。

功能说明：
    组合 DungeonGenerator / TileMap / FogOfWar 形成一个完整楼层。
    对外提供一个 Floor 类，PlayState 只需实例化 Floor 即可获得
    tilemap / rooms / 出生点 / 迷雾。自动进行房间类型分配：
    1 BOSS / 1 SHOP / 1 REST / 1 ELITE / 2 BATTLE（共 6 个）
"""
from __future__ import annotations

from src.core import config
from src.utils.rng import RNG
from src.utils.vector import Vector2
from src.world.dungeon_generator import DungeonGenerator, DungeonResult
from src.world.fog_of_war import FogOfWar
from src.world.room import Room, RoomType
from src.world.tilemap import TileMap, TileType


# 每层房间类型配额：1 BOSS, 1 SHOP, 1 REST, 1 ELITE, 2 BATTLE（共 6 个）
_ROOM_TYPE_QUOTA = [
    RoomType.BOSS,
    RoomType.SHOP,
    RoomType.REST,
    RoomType.ELITE,
    RoomType.BATTLE,
    RoomType.BATTLE,
]


class Floor:
    """单层地牢：包含 tilemap、rooms、迷雾、出生点。"""

    def __init__(
        self,
        level: int = 1,
        seed: int | None = None,
        map_width: int = config.MAP_MAX_SIZE,
        map_height: int = config.MAP_MAX_SIZE,
    ):
        self.level = level
        self.rng = RNG(seed)
        self.map_width = map_width
        self.map_height = map_height

        # 各子模块实例
        self.tilemap: TileMap = TileMap(map_width, map_height)
        self.fog: FogOfWar = FogOfWar(map_width, map_height)
        self.rooms: list[Room] = []
        self.dungeon_result: DungeonResult | None = None

        # 关键位置
        self.player_spawn: Vector2 = Vector2()  # 玩家出生点
        self.boss_room: Room | None = None      # Boss 房引用
        # 下行阶梯位置（Boss 房中心）。击败 Boss 前不可用，击败后 stair_active 置 True
        self.stair_pos: Vector2 | None = None
        self.stair_active: bool = False
        # 房间内障碍柱格坐标集合（渲染区分障碍柱贴图与边界墙贴图）
        self.obstacle_tiles: set[tuple[int, int]] = set()

        # 立即生成楼层
        self.generate_floor()

    # ========== 生成流程 ==========

    def generate_floor(self) -> None:
        """执行完整生成流程：BSP 房间 → 刻 tilemap → 分配类型 → 出生点。"""
        # Step 1: BSP 生成房间数据
        self.dungeon_result = DungeonGenerator.generate(
            map_width=self.map_width,
            map_height=self.map_height,
            rng=self.rng,
        )
        self.rooms = self.dungeon_result.rooms

        # Step 2: 把房间和走廊刻进 tilemap
        DungeonGenerator.carve_tilemap(self.tilemap, self.dungeon_result, self.rng)

        # Step 3: 分配房间类型
        self._assign_room_types()

        # Step 3.5: 战斗/精英房生成障碍柱（战棋地形：卡位/卡视线）
        self._place_battle_obstacles()

        # Step 4: 计算玩家出生点（REST/SHOP/START 房间中心）+ 初始迷雾
        self.player_spawn = self._pick_spawn()
        self.fog.update_visibility(self.player_spawn, tilemap=self.tilemap)

        # Step 5: 下行阶梯固定在 Boss 房中心（击败 Boss 前不渲染/不激活）
        if self.boss_room is not None:
            stair_pos = self.boss_room.center()
            self.stair_pos = Vector2(int(stair_pos.x), int(stair_pos.y))
        else:
            self.stair_pos = None

    @property
    def seed(self) -> int | None:
        """返回本楼层实际使用的种子（未指定时由 RNG 自动生成），用于存档复现。"""
        return self.rng.seed

    def _assign_room_types(self) -> None:
        """
        为房间列表分配 6 个类型：
          - 距离出生候选点最远的 = BOSS
          - 最近的 = REST（玩家休息恢复点）
          - 第二近的 = SHOP
          - 剩余房间中较远的 1 个 = ELITE（守卫在 Boss 之前）
          - 其余 = BATTLE
        """
        if not self.rooms:
            return
        # 用几何中心作为参考点（地图中心）
        center = Vector2(self.map_width / 2, self.map_height / 2)
        rooms_sorted = sorted(
            self.rooms,
            key=lambda r: r.center().distance_to(center),
        )

        # 距离最远 = BOSS
        rooms_sorted[-1].room_type = RoomType.BOSS
        self.boss_room = rooms_sorted[-1]
        # 距离最近 = REST（同时作出生点）
        rooms_sorted[0].room_type = RoomType.REST
        # 第二近 = SHOP
        if len(rooms_sorted) >= 2:
            rooms_sorted[1].room_type = RoomType.SHOP
        # 剩余房间：较远的一个 = ELITE，其余 = BATTLE
        remaining = rooms_sorted[2:-1]  # 剔除 BOSS 后，剩余中间房间
        if remaining:
            remaining[-1].room_type = RoomType.ELITE
            for r in remaining[:-1]:
                r.room_type = RoomType.BATTLE
        # 如果房间数刚好 6，这步会剩 1 ELITE + 2 BATTLE，与配额一致
        # 如果因生成异常房间<6，多余的类型位不报错

    def _place_battle_obstacles(self) -> None:
        """
        在战斗/精英/Boss 房内部随机放置障碍柱（WALL 单格）：
        - 数量 OBSTACLE_MIN~OBSTACLE_MAX，使用楼层种子保证可复现
        - 只放在房间内圈（边距 1），避开房间中心 2 格范围（敌人出生区、
          Boss 房下行阶梯）与四角出生点
        - 柱子之间不相邻（保持走廊感，单格散柱不会破坏连通性）
        """
        for room in self.rooms:
            if room.room_type not in (
                RoomType.BATTLE,
                RoomType.ELITE,
                RoomType.BOSS,
            ):
                continue
            count = self.rng.randint(config.OBSTACLE_MIN, config.OBSTACLE_MAX)
            # 候选格：内圈（不含边框）
            candidates = [
                (gx, gy)
                for gx in range(room.x1 + 1, room.x2)
                for gy in range(room.y1 + 1, room.y2)
            ]
            if not candidates:
                continue
            center = room.center()
            cx, cy = int(center.x), int(center.y)
            # 四角敌人出生点
            corners = {
                (room.x1 + 1, room.y1 + 1),
                (room.x2 - 1, room.y1 + 1),
                (room.x1 + 1, room.y2 - 1),
                (room.x2 - 1, room.y2 - 1),
            }
            placed: list[tuple[int, int]] = []
            for _ in range(count):
                # 随机挑一个未用候选位（最多尝试 count*3 次）
                for _try in range(count * 3):
                    gx, gy = self.rng.choice(candidates)
                    if (gx, gy) in placed:
                        continue
                    # 避开中心 2 格（精英/随从出生区）与四角出生点
                    if max(abs(gx - cx), abs(gy - cy)) <= 2:
                        continue
                    if (gx, gy) in corners:
                        continue
                    # 与已有柱子不相邻（正交）
                    if any(abs(gx - px) + abs(gy - py) == 1 for px, py in placed):
                        continue
                    self.tilemap.set_tile(gx, gy, TileType.WALL)
                    placed.append((gx, gy))
                    break
            # 收集本房间障碍柱（play_state 渲染用 obstacle 贴图区分边界墙）
            self.obstacle_tiles.update(placed)

    def _pick_spawn(self) -> Vector2:
        """选择玩家出生位置：REST 房间中心。"""
        rest_room = next(
            (r for r in self.rooms if r.room_type == RoomType.REST),
            None,
        )
        if rest_room is None:
            # 找不到 REST 房就退回第一个房间中心
            return self.rooms[0].center() if self.rooms else Vector2(5, 5)
        return rest_room.center()
