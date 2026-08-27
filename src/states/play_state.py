"""
游戏进行中状态模块。

Day 2 内容：实例化 Floor 并在屏幕上渲染地图瓦片、战争迷雾、房间标签。
相机策略：玩家出生点居中于屏幕（Day 3 改成跟随玩家移动）。
Day 3 起接入玩家移动、战斗系统等。
"""
import pygame

from src.core import config
from src.states.base_state import BaseState
from src.utils.vector import Vector2
from src.world.floor import Floor
from src.world.fog_of_war import FogState
from src.world.room import RoomType
from src.world.tilemap import TileType


# ========== 渲染颜色表（tile → 颜色） ==========
_TILE_COLORS: dict[TileType, tuple[int, int, int]] = {
    TileType.WALL: config.COLOR_WALL,
    TileType.FLOOR: config.COLOR_FLOOR,
    TileType.DOOR: config.COLOR_DOOR,
    TileType.TRAP: (180, 40, 40),  # 陷阱暂亮红
}

# 房间类型 → 标签字符与颜色
_ROOM_TYPE_LABEL: dict[RoomType, tuple[str, tuple[int, int, int]]] = {
    RoomType.BATTLE: ("战", config.COLOR_ENEMY),
    RoomType.BOSS:   ("王", config.COLOR_BOSS),
    RoomType.SHOP:   ("商", (230, 210, 60)),
    RoomType.REST:   ("休", (120, 220, 120)),
    RoomType.START:  ("始", config.COLOR_PLAYER),
}


class PlayState(BaseState):
    """游戏中状态。Day 2：地图生成与渲染。Day 3：玩家移动。"""

    def __init__(self, game):
        super().__init__(game)
        self.floor: Floor | None = None
        # 相机：瓦片坐标偏移，屏幕左上角对应的瓦片世界坐标
        self.camera = Vector2(0, 0)
        # 预创建的迷雾 Surface（每帧复用，避免逐瓦片创建 Surface 开销）
        self._fog_surfaces: dict[int, pygame.Surface] = {}

    # ========== 生命周期 ==========

    def enter(self):
        """进入状态时生成一层地牢 + 调整相机到出生点。"""
        self.floor = Floor(level=1)
        # 相机以玩家出生点为中心
        center_gx = self.floor.player_spawn.x
        center_gy = self.floor.player_spawn.y
        tiles_x = config.SCREEN_WIDTH // config.TILE_SIZE
        tiles_y = config.SCREEN_HEIGHT // config.TILE_SIZE
        self.camera = Vector2(center_gx - tiles_x / 2, center_gy - tiles_y / 2)

    def exit(self):
        pass

    def handle_event(self, event):
        """处理输入：Esc 返回主菜单。"""
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                from src.states.menu_state import MenuState
                self.game.change_state(MenuState(self.game))

    def update(self, dt):
        """Day 2 无逻辑更新。"""
        pass

    # ========== 绘制 ==========

    def draw(self, screen):
        """
        三层绘制：
            1) 瓦片（墙/地/门/陷阱按类型填色）
            2) 战争迷雾遮罩（UNSEEN=全黑, EXPLORED=半透明黑）
            3) 房间类型标签（在房间中心）
        """
        assert self.floor is not None
        screen.fill(config.BLACK)

        tilemap = self.floor.tilemap
        fog = self.floor.fog
        ts = config.TILE_SIZE

        # ---------- 计算屏幕可见的瓦片范围（减少超量绘制） ----------
        cam_x, cam_y = self.camera.x, self.camera.y
        screen_tiles_x = (config.SCREEN_WIDTH + ts - 1) // ts
        screen_tiles_y = (config.SCREEN_HEIGHT + ts - 1) // ts
        gx_start = max(0, int(cam_x))
        gy_start = max(0, int(cam_y))
        gx_end = min(tilemap.width, int(cam_x + screen_tiles_x) + 1)
        gy_end = min(tilemap.height, int(cam_y + screen_tiles_y) + 1)

        # ---------- 第一层：瓦片颜色 ----------
        for gy in range(gy_start, gy_end):
            for gx in range(gx_start, gx_end):
                tile = tilemap.get_tile(gx, gy)
                color = _TILE_COLORS.get(tile, config.COLOR_WALL)
                sx = int((gx - cam_x) * ts)
                sy = int((gy - cam_y) * ts)
                pygame.draw.rect(screen, color, (sx, sy, ts, ts))

        # ---------- 第二层：战争迷雾遮罩 ----------
        for gy in range(gy_start, gy_end):
            for gx in range(gx_start, gx_end):
                state = fog.get_state(gx, gy)
                if state == FogState.VISIBLE:
                    continue  # 当前可见：无遮罩
                alpha = (
                    config.COLOR_FOG_UNSEEN[3]   # 未探索：255 全黑
                    if state == FogState.UNSEEN
                    else config.COLOR_FOG_EXPLORED[3]  # 已探索：160 半透明
                )
                surface = self._get_fog_surface(alpha, ts)
                sx = int((gx - cam_x) * ts)
                sy = int((gy - cam_y) * ts)
                screen.blit(surface, (sx, sy))

        # ---------- 第三层：房间类型标签（只画 VISIBLE/EXPLORED 区域） ----------
        for room in self.floor.rooms:
            center = room.center()
            label, color = _ROOM_TYPE_LABEL.get(
                room.room_type, ("?", config.WHITE)
            )
            # 只在可见或已探索房间显示标签（避免未探索区域提前露信息）
            if fog.get_state(int(center.x), int(center.y)) == FogState.UNSEEN:
                continue
            sx = int((center.x - cam_x) * ts + ts // 2)
            sy = int((center.y - cam_y) * ts + ts // 2)
            text = self.game.font.render(label, True, color)
            rect = text.get_rect(center=(sx, sy))
            screen.blit(text, rect)

        # ---------- 调试 HUD：楼层号 + 种子 + 房间信息 ----------
        self._draw_top_hud(screen)

    # ========== 辅助工具 ==========

    def _get_fog_surface(self, alpha: int, ts: int) -> pygame.Surface:
        """按 alpha 缓存雾表面，避免逐帧创建。"""
        key = (alpha, ts)
        if key in self._fog_surfaces:
            return self._fog_surfaces[key]
        surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
        surf.fill((0, 0, 0, alpha))
        self._fog_surfaces[key] = surf
        return surf

    def _draw_top_hud(self, screen) -> None:
        """顶部调试 HUD：显示楼层、种子、房间类型统计。"""
        assert self.floor is not None
        # 底部半透明条
        bar = pygame.Surface(
            (config.SCREEN_WIDTH, 32),
            pygame.SRCALPHA,
        )
        bar.fill(config.COLOR_PANEL)
        screen.blit(bar, (0, config.SCREEN_HEIGHT - 32))

        # 种子与楼层
        text = self.game.font.render(
            f"F{self.floor.level}  ·  "
            f"Seed: {self.floor.rng.seed}  ·  "
            f"Rooms: {len(self.floor.rooms)}  ·  "
            f"Spawn: ({self.floor.player_spawn.x:.0f}, {self.floor.player_spawn.y:.0f})",
            True,
            config.COLOR_TEXT,
        )
        screen.blit(text, (10, config.SCREEN_HEIGHT - 30))

        # 房间类型统计
        counts = {}
        for r in self.floor.rooms:
            counts[r.room_type.name] = counts.get(r.room_type.name, 0) + 1
        stats_text = "    ".join(f"{k}:{v}" for k, v in counts.items())
        label_surf = self.game.font.render(stats_text, True, config.LIGHT_GRAY)
        screen.blit(
            label_surf,
            (config.SCREEN_WIDTH - label_surf.get_width() - 10, config.SCREEN_HEIGHT - 30),
        )
