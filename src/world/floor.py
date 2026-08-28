"""
楼层管理模块。

功能说明：
    组合 DungeonGenerator / TileMap / FogOfWar 形成一个完整楼层。
    对外提供一个 Floor 类，PlayState 只需实例化 Floor 即可获得
    tilemap / rooms / 出生点 / 迷雾。自动进行房间类型分配：
    1 BOSS / 1 SHOP / 1 REST / 3 BATTLE（共 6 个）
"""
from __future__ import annotations

from src.core import config
from src.utils.rng import RNG
from src.utils.vector import Vector2
from src.world.dungeon_generator import DungeonGenerator, DungeonResult
from src.world.fog_of_war import FogOfWar
from src.world.room import Room, RoomType
from src.world.tilemap import TileMap


# 每层房间类型配额：1 BOSS, 1 SHOP, 1 REST, 3 BATTLE
_ROOM_TYPE_QUOTA = [
    RoomType.BOSS,
    RoomType.SHOP,
    RoomType.REST,
    RoomType.BATTLE,
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

        # Step 4: 计算玩家出生点（REST/SHOP/START 房间中心）+ 初始迷雾
        self.player_spawn = self._pick_spawn()
        self.fog.update_visibility(self.player_spawn, tilemap=self.tilemap)

    def _assign_room_types(self) -> None:
        """
        为房间列表分配 6 个类型：
          - 距离出生候选点最远的 = BOSS
          - 最近的 = REST（玩家休息恢复点）
          - 中间距离的按 SHOP + 3BATTLE 分配
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
        # 其余 = BATTLE
        for r in rooms_sorted[2:-1]:
            r.room_type = RoomType.BATTLE
        # 如果房间数刚好 6，这步会剩 3 个 BATTLE，与配额一致
        # 如果因生成异常房间<6，多余的类型位不报错

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
