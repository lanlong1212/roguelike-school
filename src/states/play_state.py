"""
游戏进行中状态模块。

Day 3 内容：
    - 实例化 Floor + Player
    - WASD 探索模式移动（1 格/次，撞墙不动）
    - 玩家每次移动后，迷雾实时展开（VISIBLE 半径刷新）
    - 相机跟随玩家
    - HUD 显示玩家 HP/AP/坐标 + 楼层信息
Day 4 起接入战斗系统。
"""
import pygame

from src.core import config
from src.entities.player import Player
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
    TileType.TRAP: (180, 40, 40),
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
    """游戏中状态。Day 3：玩家移动 + 迷雾展开 + 相机跟随。"""

    def __init__(self, game):
        super().__init__(game)
        self.floor: Floor | None = None
        self.player: Player | None = None
        self.camera = Vector2(0, 0)
        # 预创建的迷雾 Surface（按 alpha 缓存）
        self._fog_surfaces: dict[int, pygame.Surface] = {}

    # ========== 生命周期 ==========

    def enter(self):
        """进入状态：生成楼层 + 创建玩家 + 初始化迷雾与相机。"""
        self.floor = Floor(level=1)
        self.player = Player(position=self.floor.player_spawn)
        # 玩家出生位置立即展开迷雾（Floor 构造时已做过一次，这里保险再刷一次）
        self.floor.fog.update_visibility(self.player.position)
        self._update_camera()

    def exit(self):
        pass

    def handle_event(self, event):
        """处理输入。"""
        if event.type == pygame.KEYDOWN:
            # Esc 返回主菜单
            if event.key == pygame.K_ESCAPE:
                from src.states.menu_state import MenuState
                self.game.change_state(MenuState(self.game))
                return
            # WASD / 方向键探索移动（1 格/次）
            dx, dy = 0, 0
            if event.key in (pygame.K_w, pygame.K_UP):
                dy = -1
            elif event.key in (pygame.K_s, pygame.K_DOWN):
                dy = 1
            elif event.key in (pygame.K_a, pygame.K_LEFT):
                dx = -1
            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                dx = 1
            if dx != 0 or dy != 0:
                self._try_player_move(dx, dy)

    def update(self, dt):
        """Day 3 无每帧逻辑（移动由按键触发，不走 dt）。"""
        pass

    # ========== 玩家移动 ==========

    def _try_player_move(self, dx: int, dy: int) -> None:
        """尝试移动玩家，成功则刷新迷雾和相机。"""
        assert self.player is not None and self.floor is not None
        if self.player.try_move_explore(dx, dy, self.floor.tilemap):
            # 移动成功：刷新迷雾 + 相机
            self.floor.fog.update_visibility(self.player.position)
            self._update_camera()

    # ========== 相机 ==========

    def _update_camera(self) -> None:
        """相机居中于玩家，保证不超出地图边界。"""
        assert self.player is not None and self.floor is not None
        ts = config.TILE_SIZE
        # 屏幕能容纳的瓦片数
        tiles_x = config.SCREEN_WIDTH / ts
        tiles_y = config.SCREEN_HEIGHT / ts
        # 目标相机：让玩家在屏幕中心
        cam_target_x = self.player.position.x - tiles_x / 2
        cam_target_y = self.player.position.y - tiles_y / 2
        # 钳制在地图范围内（避免看到地图外的黑色）
        max_cam_x = max(0, self.floor.map_width - tiles_x)
        max_cam_y = max(0, self.floor.map_height - tiles_y)
        self.camera.x = max(0, min(cam_target_x, max_cam_x))
        self.camera.y = max(0, min(cam_target_y, max_cam_y))

    # ========== 绘制 ==========

    def draw(self, screen):
        """三层绘制：瓦片 → 迷雾 → 房间标签 + 玩家 + HUD。"""
        assert self.floor is not None and self.player is not None
        screen.fill(config.BLACK)

        tilemap = self.floor.tilemap
        fog = self.floor.fog
        ts = config.TILE_SIZE
        cam_x, cam_y = self.camera.x, self.camera.y

        # ---------- 屏幕可见瓦片范围 ----------
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
                    continue
                alpha = (
                    config.COLOR_FOG_UNSEEN[3]
                    if state == FogState.UNSEEN
                    else config.COLOR_FOG_EXPLORED[3]
                )
                surface = self._get_fog_surface(alpha, ts)
                sx = int((gx - cam_x) * ts)
                sy = int((gy - cam_y) * ts)
                screen.blit(surface, (sx, sy))

        # ---------- 第三层：房间类型标签 ----------
        for room in self.floor.rooms:
            center = room.center()
            if fog.get_state(int(center.x), int(center.y)) == FogState.UNSEEN:
                continue
            label, color = _ROOM_TYPE_LABEL.get(room.room_type, ("?", config.WHITE))
            sx = int((center.x - cam_x) * ts + ts // 2)
            sy = int((center.y - cam_y) * ts + ts // 2)
            text = self.game.font.render(label, True, color)
            rect = text.get_rect(center=(sx, sy))
            screen.blit(text, rect)

        # ---------- 第四层：玩家 ----------
        self.player.render(screen, cam_x, cam_y)

        # ---------- HUD ----------
        self._draw_hud(screen)

    # ========== 辅助工具 ==========

    def _get_fog_surface(self, alpha: int, ts: int) -> pygame.Surface:
        """按 alpha 缓存雾表面。"""
        key = (alpha, ts)
        if key in self._fog_surfaces:
            return self._fog_surfaces[key]
        surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
        surf.fill((0, 0, 0, alpha))
        self._fog_surfaces[key] = surf
        return surf

    def _draw_hud(self, screen) -> None:
        """底部 HUD：楼层/种子 + 玩家 HP/AP/坐标。"""
        assert self.floor is not None and self.player is not None
        # 半透明面板
        bar = pygame.Surface((config.SCREEN_WIDTH, 40), pygame.SRCALPHA)
        bar.fill(config.COLOR_PANEL)
        screen.blit(bar, (0, config.SCREEN_HEIGHT - 40))

        # 左侧：楼层 + 种子
        left_text = self.game.font.render(
            f"F{self.floor.level}  ·  Seed:{self.floor.rng.seed}",
            True, config.COLOR_TEXT,
        )
        screen.blit(left_text, (10, config.SCREEN_HEIGHT - 32))

        # 中间：玩家 HP / AP
        s = self.player.stats
        center_text = self.game.font.render(
            f"HP {s.hp}/{s.max_hp}   AP {s.ap}/{s.max_ap}",
            True, config.COLOR_TEXT,
        )
        screen.blit(
            center_text,
            (config.SCREEN_WIDTH // 2 - center_text.get_width() // 2,
             config.SCREEN_HEIGHT - 32),
        )

        # 右侧：玩家坐标
        right_text = self.game.font.render(
            f"({self.player.grid_x},{self.player.grid_y})",
            True, config.LIGHT_GRAY,
        )
        screen.blit(
            right_text,
            (config.SCREEN_WIDTH - right_text.get_width() - 10,
             config.SCREEN_HEIGHT - 32),
        )
