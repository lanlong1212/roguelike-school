"""
游戏进行中状态模块。

Day 5 扩展：
    - AttackAction 接入伤害公式，攻击真正扣血
    - 数字键 1/2/3 切换技能（基础攻击/冲锋斩/火球术）
    - 攻击范围按技能 range_cells 计算（火球术 5 格远程）
    - 伤害飘字系统：攻击命中后生成飘字，1 秒上浮渐隐
    - 敌人死亡后从攻击范围移除
"""
from __future__ import annotations

from collections import deque
from enum import Enum, auto
from typing import Optional

import pygame

from src.combat.action import AttackAction, EndTurnAction, MoveAction, SkillAction
from src.combat.battle_manager import BattleManager, TurnPhase
from src.core import config
from src.entities.enemy import Enemy
from src.entities.player import Player, Skill
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


# ========== 飘字系统 ==========
class FloatingText:
    """伤害飘字。从目标位置上浮并渐隐。"""

    __slots__ = ("text", "x", "y", "color", "age", "lifetime", "vy")

    def __init__(self, text: str, x: float, y: float, color: tuple[int, int, int]):
        self.text = text
        self.x = x          # 屏幕像素坐标
        self.y = y
        self.color = color
        self.age = 0.0      # 存活时间
        self.lifetime = 1.0  # 总存活秒数
        self.vy = -40       # 上浮速度（像素/秒）

    def update(self, dt: float) -> bool:
        """更新飘字，返回是否还存活。"""
        self.age += dt
        self.y += self.vy * dt
        return self.age < self.lifetime - 0.001  # 浮点余量，避免卡在边界

    def draw(self, screen, font) -> None:
        """绘制飘字。alpha 随存活时间衰减。"""
        if self.age >= self.lifetime:
            return
        # 透明度：0→1.0 期间从 255 衰减到 0
        alpha = int(255 * (1 - self.age / self.lifetime))
        text_surf = font.render(self.text, True, self.color)
        text_surf.set_alpha(alpha)
        screen.blit(text_surf, (int(self.x), int(self.y)))


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
        self._last_room: Room | None = None  # Day 7：记录战斗房间用于掉落
        # Day 5：飘字列表与技能 UI 状态
        self._floating_texts: list[FloatingText] = []
        # 数字键 1/2/3 选技能；选中后点击红格释放；选中移动模式时点击蓝格移动
        self._selected_skill_index: int = 0  # 0=基础攻击（默认）

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
                # 数字键 1/2/3 切换技能
                elif event.key == pygame.K_1:
                    self._selected_skill_index = 0
                    self._compute_battle_highlights()
                elif event.key == pygame.K_2:
                    if len(self.player.skills) > 1:
                        self._selected_skill_index = 1
                        self._compute_battle_highlights()
                elif event.key == pygame.K_3:
                    if len(self.player.skills) > 2:
                        self._selected_skill_index = 2
                        self._compute_battle_highlights()
                # M 键切回移动模式（不消耗 AP 选择）
                elif event.key == pygame.K_m:
                    self._selected_skill_index = -1  # -1 = 移动模式
                    self._compute_battle_highlights()
                # H 键使用药水（找第一个药水槽位）
                elif event.key == pygame.K_h:
                    self._use_first_potion()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.mode == PlayMode.BATTLE:
                self._handle_battle_click(event.pos)

    def update(self, dt):
        """每帧推进敌人回合 + 飘字动画。"""
        # 飘字更新（无论何种模式）
        if self._floating_texts:
            self._floating_texts = [t for t in self._floating_texts if t.update(dt)]

        if self.mode == PlayMode.BATTLE and self.battle:
            if self.battle.is_enemy_turn:
                self.battle.step_enemy_turn()
                # 敌人攻击后生成飘字（敌人攻击玩家时）
                self._spawn_enemy_damage_floating_text()
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
        # Day 7：Boss 房生成 Boss；战斗房生成 Slime/Skeleton
        from src.entities.enemies.slime import Slime
        from src.entities.enemies.skeleton import Skeleton
        from src.entities.enemies.boss import Boss

        enemies: list[Enemy] = []
        if room.room_type == RoomType.BOSS:
            # Boss 房只放 Boss
            bc = room.center()
            boss = Boss(position=Vector2(int(bc.x), int(bc.y)))
            enemies.append(boss)
        else:
            num = 2 if room.room_type == RoomType.BATTLE else 1
            corners = [
                (room.x1 + 1, room.y1 + 1),
                (room.x2 - 1, room.y1 + 1),
                (room.x1 + 1, room.y2 - 1),
                (room.x2 - 1, room.y2 - 1),
            ]
            for i in range(num):
                gx, gy = corners[i % len(corners)]
                if (gx, gy) == self.player.grid_pos:
                    continue
                if i == 0:
                    enemy = Slime(position=Vector2(gx, gy))
                else:
                    enemy = Skeleton(position=Vector2(gx, gy))
                enemies.append(enemy)

        self.battle = BattleManager(self.player, enemies, self.floor.tilemap)
        self.mode = PlayMode.BATTLE
        self.player.stats.reset_ap()
        self.battle.last_action_desc = f"遭遇 {len(enemies)} 个敌人！"
        self._last_room = room  # Day 7：记录当前房间用于掉落
        self._compute_battle_highlights()

    def _compute_battle_highlights(self) -> None:
        """
        BFS 计算玩家可移动范围（按 move_range 限制）与可攻击目标。
        Day 5：攻击范围按当前选中技能的 range_cells 计算。
        """
        assert self.player and self.floor and self.battle
        self._move_range.clear()
        self._attack_targets.clear()

        start = self.player.grid_pos
        move_range = self.player.stats.move_range
        tilemap = self.floor.tilemap
        enemy_pos = {e.grid_pos: e for e in self.battle.enemies if not e.stats.is_dead()}

        # --- 移动范围 BFS（始终计算，M 键切移动模式时用） ---
        visited = {start: 0}
        self._move_range[start] = 0
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
                # 被敌人占据的格子不能移动到，但 BFS 可以穿过敌人记录距离
                if (nx, ny) in enemy_pos:
                    visited[(nx, ny)] = dist + 1
                    continue
                visited[(nx, ny)] = dist + 1
                self._move_range[(nx, ny)] = dist + 1
                queue.append(((nx, ny), dist + 1))

        # --- 攻击范围：按当前技能 range_cells ---
        # _selected_skill_index = -1 表示纯移动模式，不显示攻击范围
        if self._selected_skill_index < 0:
            return
        skills = self.player.skills
        if self._selected_skill_index >= len(skills):
            return
        skill = skills[self._selected_skill_index]
        attack_range = skill.range_cells

        # BFS 从玩家位置出发，找攻击范围内所有敌人
        # 距离用切比雪夫距离（8 方向），range_cells=1 即相邻 8 格
        px, py = start
        for (ex, ey), enemy in enemy_pos.items():
            dist = max(abs(ex - px), abs(ey - py))  # 切比雪夫距离
            if dist <= attack_range:
                self._attack_targets[(ex, ey)] = enemy

    def _handle_battle_click(self, mouse_pos: tuple[int, int]) -> None:
        """
        战斗中鼠标点击：
        - 红格（攻击目标）→ 使用当前选中技能攻击
        - 蓝格（可移动）→ 移动
        """
        assert self.player and self.floor and self.battle
        if not self.battle.is_player_turn:
            return
        ts = config.TILE_SIZE
        cam_x, cam_y = self.camera.x, self.camera.y
        gx = int(mouse_pos[0] / ts + cam_x)
        gy = int(mouse_pos[1] / ts + cam_y)

        # 点击可攻击格子 → AttackAction/SkillAction
        if (gx, gy) in self._attack_targets:
            target = self._attack_targets[(gx, gy)]
            skills = self.player.skills
            if 0 <= self._selected_skill_index < len(skills):
                skill = skills[self._selected_skill_index]
                # Day 5 统一走 SkillAction（含基础攻击 1.0×）
                action = SkillAction(
                    actor=self.player,
                    target=target,
                    skill_id=skill.id,
                    multiplier=skill.multiplier,
                    ap_cost=skill.ap_cost,
                    skill_name=skill.name,
                )
                if self.battle.execute_action(action):
                    self._spawn_damage_floating_text()
                    self._after_player_action()
            return

        # 点击可移动格子 → MoveAction
        if (gx, gy) in self._move_range and (gx, gy) != self.player.grid_pos:
            action = MoveAction(self.player, Vector2(gx, gy), ap_cost=1)
            if self.battle.execute_action(action):
                self._after_player_action()
            return

    def _spawn_damage_floating_text(self) -> None:
        """根据 battle.last_damage_result 生成飘字。"""
        assert self.battle
        result = self.battle.last_damage_result
        target = self.battle.last_damage_target
        if result is None or target is None:
            return
        # 飘字文本：暴击加感叹号
        text = f"-{result.damage}"
        if result.is_crit:
            text = f"-{result.damage}!"
            color = (255, 220, 80)  # 暴击黄色
        else:
            color = (255, 80, 80)   # 普通红色
        # 屏幕坐标：目标头顶
        ts = config.TILE_SIZE
        sx = (target.position.x - self.camera.x) * ts + ts // 4
        sy = (target.position.y - self.camera.y) * ts - 4
        self._floating_texts.append(FloatingText(text, sx, sy, color))
        # 清除一次性标记，避免重复生成
        self.battle.last_damage_result = None
        self.battle.last_damage_target = None

    def _spawn_enemy_damage_floating_text(self) -> None:
        """敌人攻击玩家时生成飘字（飘在玩家头顶）。"""
        assert self.battle
        result = self.battle.last_damage_result
        target = self.battle.last_damage_target
        if result is None or target is None:
            return
        text = f"-{result.damage}"
        color = (255, 100, 100)
        ts = config.TILE_SIZE
        sx = (target.position.x - self.camera.x) * ts + ts // 4
        sy = (target.position.y - self.camera.y) * ts - 4
        self._floating_texts.append(FloatingText(text, sx, sy, color))
        self.battle.last_damage_result = None
        self.battle.last_damage_target = None

    def _after_player_action(self) -> None:
        """玩家执行行动后：刷新高亮、迷雾、相机，检查战斗结束。"""
        assert self.player and self.floor and self.battle
        # 战斗结束
        if self.battle.phase == TurnPhase.BATTLE_WON:
            self._end_battle(victory=True)
            return
        if self.battle.is_enemy_turn:
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
        # Day 7：先处理掉落（battle 仍可用）
        loot_desc = ""
        if victory and self._last_room:
            if self._last_room.room_type == RoomType.BOSS:
                loot_desc = self._drop_boss_loot()
            elif self._last_room.room_type == RoomType.BATTLE:
                loot_desc = self._drop_battle_loot()
        # 清理战斗状态
        self.mode = PlayMode.EXPLORE
        self.battle = None
        self._move_range.clear()
        self._attack_targets.clear()
        # 保留掉落信息用于 HUD 显示
        self._last_loot_desc = loot_desc
        # 失败 → Day 8 接入 game_over_state；Day 4 暂时回主菜单
        if not victory:
            from src.states.menu_state import MenuState
            self.game.change_state(MenuState(self.game))

    def _drop_boss_loot(self) -> str:
        """Boss 掉落：长弓 + 治疗药水 ×2。返回掉落描述。"""
        from src.items.weapon import create_long_bow
        from src.items.potion import HealthPotion
        loot = [create_long_bow(), HealthPotion(), HealthPotion()]
        for item in loot:
            self.player.inventory.add(item)
        return f"获得战利品：{', '.join(i.name for i in loot)}"

    def _drop_battle_loot(self) -> str:
        """普通战斗掉落：50% 药水，30% 铁剑。返回掉落描述。"""
        import random
        from src.items.potion import HealthPotion
        from src.items.weapon import create_iron_sword
        roll = random.random()
        if roll < 0.5:
            self.player.inventory.add(HealthPotion())
            return "获得：治疗药水"
        elif roll < 0.8:
            self.player.inventory.add(create_iron_sword())
            return "获得：铁剑"
        else:
            return "战斗胜利！"

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

        # ---------- 第七层：飘字 ----------
        for ft in self._floating_texts:
            ft.draw(screen, self.game.font)

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
                "点击蓝格移动 · 点击红格攻击 · 空格结束回合 · M 切换移动/攻击",
                True, config.COLOR_TEXT_HIGHLIGHT,
            )
            screen.blit(tip, (10, 10))
            # Day 5：技能栏（顶部下方）
            self._draw_skill_bar(screen)

    def _draw_skill_bar(self, screen) -> None:
        """绘制技能选择栏（数字键 1/2/3 切换）。"""
        assert self.player
        skills = self.player.skills
        bar_y = 40
        bar_x = 10
        slot_w = 200
        slot_h = 32
        gap = 8
        for i, skill in enumerate(skills):
            rect = pygame.Rect(bar_x + i * (slot_w + gap), bar_y, slot_w, slot_h)
            # 选中态高亮
            is_selected = (i == self._selected_skill_index)
            bg = (60, 80, 120) if is_selected else (30, 30, 40)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            border_color = config.COLOR_TEXT_HIGHLIGHT if is_selected else config.GRAY
            pygame.draw.rect(screen, border_color, rect, 2, border_radius=4)
            # 技能文本
            txt = f"[{i+1}] {skill.name} {skill.ap_cost}AP {skill.multiplier}×"
            text_surf = self.game.font.render(txt, True, config.COLOR_TEXT)
            screen.blit(text_surf, (rect.x + 6, rect.y + 6))
            # AP 不足时灰显
            if self.player.stats.ap < skill.ap_cost:
                overlay = pygame.Surface((slot_w, slot_h), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 140))
                screen.blit(overlay, rect)
        # 移动模式标记
        if self._selected_skill_index < 0:
            rect = pygame.Rect(bar_x + len(skills) * (slot_w + gap), bar_y, slot_w, slot_h)
            pygame.draw.rect(screen, (60, 120, 80), rect, border_radius=4)
            pygame.draw.rect(screen, config.COLOR_TEXT_HIGHLIGHT, rect, 2, border_radius=4)
            txt = "[M] 移动模式"
            text_surf = self.game.font.render(txt, True, config.COLOR_TEXT)
            screen.blit(text_surf, (rect.x + 6, rect.y + 6))

    def _use_first_potion(self) -> None:
        """Day 7：使用背包里第一个药水（H 键）。"""
        from src.items.item import ItemType
        inv = self.player.inventory
        for i in range(inv.MAX_SLOTS):
            item = inv.get_item(i)
            if item is not None and item.item_type == ItemType.POTION:
                hp_before = self.player.stats.hp
                if inv.use_item(i, self.player):
                    healed = self.player.stats.hp - hp_before
                    name = item.name
                    if healed > 0:
                        self.battle.last_action_desc = f"使用 {name}，回复 {healed} HP"
                        # 生成绿色治疗飘字
                        ts = config.TILE_SIZE
                        sx = (self.player.position.x - self.camera.x) * ts + ts // 4
                        sy = (self.player.position.y - self.camera.y) * ts - 4
                        self._floating_texts.append(
                            FloatingText(f"+{healed}", sx, sy, (100, 255, 100))
                        )
                    else:
                        self.battle.last_action_desc = f"使用 {name}"
                    self._compute_battle_highlights()
                return
