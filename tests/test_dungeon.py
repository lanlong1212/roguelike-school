"""
地图生成单元测试。

验证等分网格地图生成器的核心契约：
- 房间数量与固定尺寸
- 房间类型配额（1 Boss / 1 Shop / 1 Rest / 1 Elite / 2 Battle）
- 全图连通（玩家出生点可走到所有房间中心）
- 障碍密度与 obstacle_tiles 一致性
- 同 seed 可复现（地图确定性）
"""
from src.core import config
from src.world.floor import Floor
from src.world.room import RoomType
from src.world.tilemap import TileType

SEEDS = [1, 42, 777, 2026, 99]
EXPECTED_QUOTA = {
    RoomType.BOSS: 1,
    RoomType.SHOP: 1,
    RoomType.REST: 1,
    RoomType.ELITE: 1,
    RoomType.BATTLE: 2,
}
# 房间内允许有障碍的类型（与 floor._place_battle_obstacles 一致）
OBSTACLE_ROOMS = (RoomType.BATTLE, RoomType.ELITE, RoomType.BOSS)


def _walkable_floor(floor) -> set:
    """收集全图可走瓦片集合。"""
    w, h = floor.tilemap.width, floor.tilemap.height
    return {
        (x, y)
        for x in range(w)
        for y in range(h)
        if floor.tilemap.is_walkable(x, y)
    }


def _reachable(floor, start) -> set:
    """从 start 出发沿可走瓦片 BFS 的可达集合。"""
    walkable = _walkable_floor(floor)
    assert start in walkable, f"出生点 {start} 不可走"
    seen = {start}
    queue = [start]
    while queue:
        x, y = queue.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in walkable and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


def test_room_count_and_quota():
    """每层固定 6 个房间，类型配额正确。"""
    for seed in SEEDS:
        floor = Floor(level=1, seed=seed)
        assert len(floor.rooms) == 6
        types = [r.room_type for r in floor.rooms]
        for rtype, count in EXPECTED_QUOTA.items():
            assert types.count(rtype) == count, f"seed={seed} 类型 {rtype} 数量错误"


def test_fixed_room_size_and_no_overlap():
    """所有房间为固定尺寸且互不重叠。"""
    for seed in SEEDS:
        floor = Floor(level=1, seed=seed)
        rects = [(r.x1, r.y1, r.x2, r.y2) for r in floor.rooms]
        for room, (x1, y1, x2, y2) in zip(floor.rooms, rects):
            assert (x2 - x1 + 1, y2 - y1 + 1) == (
                config.ROOM_FIXED_W, config.ROOM_FIXED_H,
            ), f"seed={seed} 房间尺寸错误"
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax1, ay1, ax2, ay2 = rects[i]
                bx1, by1, bx2, by2 = rects[j]
                overlap = ax1 <= bx2 and bx1 <= ax2 and ay1 <= by2 and by1 <= ay2
                assert not overlap, f"seed={seed} 房间 {i} 与 {j} 重叠"


def test_connectivity():
    """出生点可达所有房间中心（走廊连通、无孤岛房间）。"""
    for seed in SEEDS:
        floor = Floor(level=1, seed=seed)
        start = (int(floor.player_spawn.x), int(floor.player_spawn.y))
        reachable = _reachable(floor, start)
        for room in floor.rooms:
            c = room.center()
            assert (int(c.x), int(c.y)) in reachable, (
                f"seed={seed} {room.room_type.name} 房中心不可达"
            )


def test_obstacle_density_and_consistency():
    """障碍规则：障碍房 6~10 根、商店/休息房无障碍、集合与瓦片一致。"""
    for seed in SEEDS:
        floor = Floor(level=1, seed=seed)
        for room in floor.rooms:
            n = sum(
                1
                for gx in range(room.x1, room.x2 + 1)
                for gy in range(room.y1, room.y2 + 1)
                if floor.tilemap.get_tile(gx, gy) == TileType.WALL
            )
            if room.room_type in OBSTACLE_ROOMS:
                assert 6 <= n <= 10, f"seed={seed} {room.room_type.name} 障碍 {n} 超界"
            else:
                assert n == 0, f"seed={seed} {room.room_type.name} 不应有障碍"
        for gx, gy in floor.obstacle_tiles:
            assert floor.tilemap.get_tile(gx, gy) == TileType.WALL
        assert len(floor.obstacle_tiles) >= 6 * 4


def test_boss_stair_position():
    """阶梯位于 Boss 房中心，击败 Boss 前未激活。"""
    floor = Floor(level=1, seed=42)
    boss = next(r for r in floor.rooms if r.room_type == RoomType.BOSS)
    c = boss.center()
    assert floor.stair_pos is not None
    assert (int(floor.stair_pos.x), int(floor.stair_pos.y)) == (int(c.x), int(c.y))
    assert floor.stair_active is False


def test_same_seed_reproducible():
    """同 seed 生成的地图完全一致（存档复现地牢的前提）。"""
    a = Floor(level=1, seed=2026)
    b = Floor(level=1, seed=2026)
    w, h = a.tilemap.width, a.tilemap.height
    for x in range(w):
        for y in range(h):
            assert a.tilemap.get_tile(x, y) == b.tilemap.get_tile(x, y), (
                f"同 seed 地图不一致 at ({x},{y})"
            )
    assert a.player_spawn == b.player_spawn
