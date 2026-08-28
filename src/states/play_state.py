"""
游戏进行中状态模块。

Day 4 内容：
    - 双模式：EXPLORE 探索 / BATTLE 战斗
    - 进入 BATTLE/BOSS 房间 → 触发战斗 → 生成 1-2 个占位 Enemy
    - 战斗中：BFS 计算可移动范围（蓝）/可攻击范围（红），鼠标点击执行
    - 战斗中：WASD 不再生效，改为点击移动；空格/回车结束回合
    - AP 归零或结束回合 → 切到敌人回合（Day 4 敌人不动立即切回）
    - HUD 增加回合数 + 最近行动描述
"""
from __future__ import annotations

from collections import deque
from enum import Enum, auto

import pygame

from src.combat.action import AttackAction, EndTurnAction, MoveAction
from src.combat.battle_manager import BattleManager, TurnPhase
from src.core import config
from src.entities.enemy import Enemy
from src.entities.player import Player
from src.states.base_state import BaseState
from src.utils.vector import Vector2
from src.world.floor import Floor
from src.world.fog_of_war import FogState
from src.world.room import Room, RoomType
from src.world.tilemap import TileType


# ========== 渲染颜色表（tile → 颜色） ==========
_TILE_COLORS: dict[TileType, tuple[int, int, int]] = {
    TileType.WALL: config.COLOR_WALL,
    TileType.FLOOR: config.COLOR_FLOOR,
    TileType.DOOR: config.COLOR_DOOR,
    TileType.TRAP: (180, 40, 40),
}

_ROOM_TYPE_LABEL: dict[RoomType, tuple[str, tuple[int, int, int]]] = {
    RoomType.BATTLE: ("战", config.COLOR_ENEMY),
    RoomType.BOSS:   ("王", config.COLOR_BOSS),
    RoomType.SHOP:   ("商", (230, 210, 60)),
    RoomType.REST:   ("休", (120, 220, 120)),
    RoomType.START:  ("始", config.COLOR_PLAYER),
}


class PlayMode(Enum):
    """PlayState 子模式。"""
    EXPLORE = auto()  # 探索：WASD 自由移动
    BATTLE = auto()  # 战斗：回合制，点击高亮格子


class PlayState(BaseState):
    """游戏中状态。Day 4：探索 + 战斗双模式。"""

    def __init__(self, game):
        super().__init__(game)
        self.floor: Floor | None = None
        self.player: Player | None = None
        self.camera = Vector2(0, 0)
        self._fog_surfaces: dict[int, pygame.Surface] = {}

        # 模式与战斗
        self.mode: PlayMode = PlayMode.EXPLORE
        self.battle: BattleManager | None = None
        # 战斗高亮缓存：可移动格子 → AP 成本；可攻击格子 → 目标敌人
        self._move_range: dict[tuple[int, int], int] = {}
        self._attack_targets: dict[tuple[int, int], Enemy] = {}
        # 玩家当前所在房间（用于触发战斗）
        self._current_room: Room | None = None
        self._battles_triggered: set[int] = set()  # 已触发战斗的房间 id

    # ========== 生命周期 ==========

    def enter(self):
        self.floor = Floor(level=1)
        self.player = Player(position=self.floor.player_spawn)
        self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
        self._update_camera()
        self._update_current_room()

    def exit(self):
        pass

    # ========== 输入 ==========

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                from src.states.menu_state import MenuState
                self.game.change_state(MenuState(self.game))
                return

            if self.mode == PlayMode.EXPLORE:
                # WASD 探索移动
                dx, dy = 0, 0
                if event.key in (pygame.K_w, pygame.K_UP): dy = -1
                elif event.key in (pygame.K_s, pygame.K_DOWN): dy = 1
                elif event.key in (pygame.K_a, pygame.K_LEFT): dx = -1
                elif event.key in (pygame.K_d, pygame.K_RIGHT): dx = 1
                if dx or dy:
                    self._try_explore_move(dx, dy)

            elif self.mode == PlayMode.BATTLE:
                # 空格/回车 → 结束回合
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if self.battle and self.battle.is_player_turn:
                        self.battle.end_player_turn()
                        self._after_player_action()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.mode == PlayMode.BATTLE:
                self._handle_battle_click(event.pos)

    def update(self, dt):
        """每帧推进敌人回合（Day 4 立即结束）。"""
        if self.mode == PlayMode.BATTLE and self.battle:
            if self.battle.is_enemy_turn:
                self.battle.step_enemy_turn()
                # step_enemy_turn Day 4 直接切回玩家回合
                self._after_enemy_turn()

    # ========== 探索模式 ==========

    def _try_explore_move(self, dx: int, dy: int) -> None:
        assert self.player and self.floor
        if self.player.try_move_explore(dx, dy, self.floor.tilemap):
            self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
            self._update_camera()
            self._update_current_room()

    def _update_current_room(self) -> None:
        """更新玩家当前所在房间，进入战斗房则触发战斗。"""
        assert self.player and self.floor
        gx, gy = self.player.grid_x, self.player.grid_y
        for room in self.floor.rooms:
            if room.contains(gx, gy):
                self._current_room = room
                # 进入战斗房且未触发过 → 开战
                if room.room_type in (RoomType.BATTLE, RoomType.BOSS):
                    if id(room) not in self._battles_triggered:
                        self._battles_triggered.add(id(room))
                        self._start_battle(room)
                return
        self._current_room = None

    # ========== 战斗模式 ==========

    def _start_battle(self, room: Room) -> None:
        """触发一场战斗：生成敌人 + 创建 BattleManager + 计算高亮。"""
        assert self.player and self.floor
        # Day 4：根据房间类型生成 1-2 个占位敌人，放在房间角落
        enemies: list[Enemy] = []
        num = 2 if room.room_type == RoomType.BATTLE else 1  # Boss 房只放 1 个（Day 7 换成 Boss）
        # 候选位置：房间四角往内 1 格
        corners = [
            (room.x1 + 1, room.y1 + 1),
            (room.x2 - 1, room.y1 + 1),
            (room.x1 + 1, room.y2 - 1),
            (room.x2 - 1, room.y2 - 1),
        ]
        for i in range(num):
            gx, gy = corners[i % len(corners)]
            # 避免和玩家重合
            if (gx, gy) == self.player.grid_pos:
                continue
            enemy = Enemy(position=Vector2(gx, gy), name=f"Enemy_{i+1}")
            enemies.append(enemy)

        self.battle = BattleManager(self.player, enemies, self.floor.tilemap)
        self.mode = PlayMode.BATTLE
        self.player.stats.reset_ap()
        self.battle.last_action_desc = f"遭遇 {len(enemies)} 个敌人！"
        self._compute_battle_highlights()

    def _compute_battle_highlights(self) -> None:
        """BFS 计算玩家可移动范围（按 move_range 限制）与可攻击目标。"""
        assert self.player and self.floor and self.battle
        self._move_range.clear()
        self._attack_targets.clear()

        start = self.player.grid_pos
        move_range = self.player.stats.move_range
        tilemap = self.floor.tilemap
        # 敌人位置集合
        enemy_pos = {e.grid_pos: e for e in self.battle.enemies if not e.stats.is_dead()}

        # BFS：每个格子记录到达它的最小步数
        visited = {start: 0}
        self._move_range[start] = 0  # 自身位置算 0 步
        queue = deque([(start, 0)])
        while queue:
            (gx, gy), dist = queue.popleft()
            if dist >= move_range:
                continue
            for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                nx, ny = gx + dx, gy + dy
                if (nx, ny) in visited:
                    continue
                if not tilemap.is_walkable(nx, ny):
                    continue
                # 被敌人占据的格子不能移动到，但可以攻击
                if (nx, ny) in enemy_pos:
                    self._attack_targets[(nx, ny)] = enemy_pos[(nx, ny)]
                    visited[(nx, ny)] = dist + 1
                    continue
                visited[(nx, ny)] = dist + 1
                self._move_range[(nx, ny)] = dist + 1
                queue.append(((nx, ny), dist + 1))

        # 额外：玩家相邻 1 格的敌人也可攻击（即便不在移动范围内）
        px, py = start
        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
            nx, ny = px + dx, py + dy
            if (nx, ny) in enemy_pos:
                self._attack_targets[(nx, ny)] = enemy_pos[(nx, ny)]

    def _handle_battle_click(self, mouse_pos: tuple[int, int]) -> None:
        """战斗中鼠标点击：蓝色移动 / 红色攻击 / 其他忽略。"""
        assert self.player and self.floor and self.battle
        if not self.battle.is_player_turn:
            return
        ts = config.TILE_SIZE
        cam_x, cam_y = self.camera.x, self.camera.y
        gx = int(mouse_pos[0] / ts + cam_x)
        gy = int(mouse_pos[1] / ts + cam_y)

        # 点击可攻击格子 → AttackAction
        if (gx, gy) in self._attack_targets:
            target = self._attack_targets[(gx, gy)]
            action = AttackAction(self.player, target, ap_cost=2)
            if self.battle.execute_action(action):
                self._after_player_action()
            return

        # 点击可移动格子 → MoveAction
        if (gx, gy) in self._move_range and (gx, gy) != self.player.grid_pos:
            # Day 4：移动消耗 1 AP/格（用 BFS 距离作为 AP 成本上限 1）
            action = MoveAction(self.player, Vector2(gx, gy), ap_cost=1)
            if self.battle.execute_action(action):
                self._after_player_action()
            return
        # 点击其他位置：忽略

    def _after_player_action(self) -> None:
        """玩家执行行动后：刷新高亮、迷雾、相机，检查战斗结束。"""
        assert self.player and self.floor and self.battle
        # 战斗结束
        if self.battle.phase == TurnPhase.BATTLE_WON:
            self._end_battle(victory=True)
            return
        if self.battle.is_enemy_turn:
            # 进入敌人回合，update() 会推进
            return
        # 仍在玩家回合：刷新高亮与迷雾
        self._compute_battle_highlights()
        self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
        self._update_camera()

    def _after_enemy_turn(self) -> None:
        """敌人回合结束，回到玩家回合：刷新 AP 与高亮。"""
        assert self.player and self.battle
        if self.battle.phase == TurnPhase.BATTLE_LOST:
            self._end_battle(victory=False)
            return
        self._compute_battle_highlights()

    def _end_battle(self, victory: bool) -> None:
        """结束战斗，切回探索模式。"""
        self.mode = PlayMode.EXPLORE
        self.battle = None
        self._move_range.clear()
        self._attack_targets.clear()
        # 失败 → Day 8 接入 game_over_state；Day 4 暂时回主菜单
        if not victory:
            from src.states.menu_state import MenuState
            self.game.change_state(MenuState(self.game))

    # ========== 相机 ==========

    def _update_camera(self) -> None:
        assert self.player and self.floor
        ts = config.TILE_SIZE
        tiles_x = config.SCREEN_WIDTH / ts
        tiles_y = config.SCREEN_HEIGHT / ts
        cam_target_x = self.player.position.x - tiles_x / 2
        cam_target_y = self.player.position.y - tiles_y / 2
        max_cam_x = max(0, self.floor.map_width - tiles_x)
        max_cam_y = max(0, self.floor.map_height - tiles_y)
        self.camera.x = max(0, min(cam_target_x, max_cam_x))
        self.camera.y = max(0, min(cam_target_y, max_cam_y))

    # ========== 绘制 ==========

    def draw(self, screen):
        assert self.floor and self.player
        screen.fill(config.BLACK)

        tilemap = self.floor.tilemap
        fog = self.floor.fog
        ts = config.TILE_SIZE
        cam_x, cam_y = self.camera.x, self.camera.y

        # ---------- 可见瓦片范围 ----------
        screen_tiles_x = (config.SCREEN_WIDTH + ts - 1) // ts
        screen_tiles_y = (config.SCREEN_HEIGHT + ts - 1) // ts
        gx_start = max(0, int(cam_x))
        gy_start = max(0, int(cam_y))
        gx_end = min(tilemap.width, int(cam_x + screen_tiles_x) + 1)
        gy_end = min(tilemap.height, int(cam_y + screen_tiles_y) + 1)

        # ---------- 第一层：瓦片 ----------
        for gy in range(gy_start, gy_end):
            for gx in range(gx_start, gx_end):
                tile = tilemap.get_tile(gx, gy)
                color = _TILE_COLORS.get(tile, config.COLOR_WALL)
                sx = int((gx - cam_x) * ts)
                sy = int((gy - cam_y) * ts)
                pygame.draw.rect(screen, color, (sx, sy, ts, ts))

        # ---------- 第二层：战斗高亮 ----------
        if self.mode == PlayMode.BATTLE:
            self._draw_battle_highlights(screen, cam_x, cam_y, ts)

        # ---------- 第三层：战争迷雾 ----------
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

        # ---------- 第四层：房间标签 ----------
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

        # ---------- 第五层：敌人 ----------
        if self.battle:
            for enemy in self.battle.enemies:
                if not enemy.stats.is_dead():
                    enemy.render(screen, cam_x, cam_y)

        # ---------- 第六层：玩家 ----------
        self.player.render(screen, cam_x, cam_y)

        # ---------- HUD ----------
        self._draw_hud(screen)

    def _draw_battle_highlights(self, screen, cam_x, cam_y, ts) -> None:
        """绘制可移动（蓝）/可攻击（红）半透明高亮。"""
        # 可移动：蓝色半透明
        move_surf = self._get_highlight_surface(
            config.COLOR_MOVE_RANGE, ts
        )
        for (gx, gy) in self._move_range:
            if (gx, gy) == self.player.grid_pos:
                continue
            sx = int((gx - cam_x) * ts)
            sy = int((gy - cam_y) * ts)
            screen.blit(move_surf, (sx, sy))

        # 可攻击：红色半透明
        attack_surf = self._get_highlight_surface(
            config.COLOR_ATTACK_RANGE, ts
        )
        for (gx, gy) in self._attack_targets:
            sx = int((gx - cam_x) * ts)
            sy = int((gy - cam_y) * ts)
            screen.blit(attack_surf, (sx, sy))

    # ========== 辅助 ==========

    def _get_fog_surface(self, alpha: int, ts: int) -> pygame.Surface:
        key = (alpha, ts)
        if key in self._fog_surfaces:
            return self._fog_surfaces[key]
        surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
        surf.fill((0, 0, 0, alpha))
        self._fog_surfaces[key] = surf
        return surf

    def _get_highlight_surface(self, color: tuple, ts: int) -> pygame.Surface:
        """按颜色缓存高亮 Surface。"""
        key = ("hl",) + color
        if key in self._fog_surfaces:
            return self._fog_surfaces[key]
        surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
        surf.fill(color)
        self._fog_surfaces[key] = surf
        return surf

    def _draw_hud(self, screen) -> None:
        assert self.floor and self.player
        # 半透明面板
        bar = pygame.Surface((config.SCREEN_WIDTH, 40), pygame.SRCALPHA)
        bar.fill(config.COLOR_PANEL)
        screen.blit(bar, (0, config.SCREEN_HEIGHT - 40))

        # 左侧：楼层 + 种子 + 模式
        mode_str = "探索" if self.mode == PlayMode.EXPLORE else "战斗"
        left_text = self.game.font.render(
            f"F{self.floor.level}  ·  Seed:{self.floor.rng.seed}  ·  [{mode_str}]",
            True, config.COLOR_TEXT,
        )
        screen.blit(left_text, (10, config.SCREEN_HEIGHT - 32))

        # 中间：HP / AP / 回合
        s = self.player.stats
        if self.battle:
            center_text = self.game.font.render(
                f"HP {s.hp}/{s.max_hp}   AP {s.ap}/{s.max_ap}   Turn {self.battle.turn_count}",
                True, config.COLOR_TEXT,
            )
        else:
            center_text = self.game.font.render(
                f"HP {s.hp}/{s.max_hp}   AP {s.ap}/{s.max_ap}",
                True, config.COLOR_TEXT,
            )
        screen.blit(
            center_text,
            (config.SCREEN_WIDTH // 2 - center_text.get_width() // 2,
             config.SCREEN_HEIGHT - 32),
        )

        # 右侧：玩家坐标 / 行动描述
        if self.battle and self.battle.last_action_desc:
            right_text = self.game.font.render(
                self.battle.last_action_desc[:30],
                True, config.COLOR_TEXT_HIGHLIGHT,
            )
        else:
            right_text = self.game.font.render(
                f"({self.player.grid_x},{self.player.grid_y})",
                True, config.LIGHT_GRAY,
            )
        screen.blit(
            right_text,
            (config.SCREEN_WIDTH - right_text.get_width() - 10,
             config.SCREEN_HEIGHT - 32),
        )

        # 战斗模式提示
        if self.mode == PlayMode.BATTLE:
            tip = self.game.font.render(
                "点击蓝格移动 · 点击红格攻击 · 空格结束回合",
                True, config.COLOR_TEXT_HIGHLIGHT,
            )
            screen.blit(tip, (10, 10))
