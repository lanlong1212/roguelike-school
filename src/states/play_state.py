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
from src.combat.element import ELEMENT_COLOR, ELEMENT_NAME, REACTION_NAME, Element
from src.combat.status_effect import EFFECT_DISPLAY_NAME
from src.core import config
from src.core import save_manager
from src.entities.enemy import Enemy
from src.entities.player import Player, Skill, get_skill_pool
from src.states.base_state import BaseState
from src.ui.hud import HUD
from src.ui.menu import InventoryMenu, RestMenu, ShopMenu
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
    TileType.STAIR: config.COLOR_STAIR,
}

_ROOM_TYPE_LABEL: dict[RoomType, tuple[str, tuple[int, int, int]]] = {
    RoomType.BATTLE: ("战", config.COLOR_ENEMY),
    RoomType.ELITE:  ("精", config.COLOR_ELITE),
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

    def __init__(self, game, load_data: dict | None = None):
        super().__init__(game)
        self.floor: Floor | None = None
        self.player: Player | None = None
        self.camera = Vector2(0, 0)
        self._fog_surfaces: dict[int, pygame.Surface] = {}
        # 用于从存档恢复的临时数据（enter() 时消费）
        self._load_data: dict | None = load_data

        # 模式与战斗
        self.mode: PlayMode = PlayMode.EXPLORE
        self.battle: BattleManager | None = None
        # 战斗高亮缓存：可移动格子 → AP 成本；可攻击格子 → 目标敌人
        self._move_range: dict[tuple[int, int], int] = {}
        self._attack_targets: dict[tuple[int, int], Enemy] = {}
        # 玩家当前所在房间（用于触发战斗）
        self._current_room: Room | None = None
        self._battles_triggered: set[int] = set()  # 已触发战斗的房间 id
        self._cleared_room_positions: set[tuple[int, int]] = set()  # 已清空房间中心（存档用）
        self._last_room: Room | None = None  # Day 7：记录战斗房间用于掉落
        # Day 5：飘字列表与技能 UI 状态
        self._floating_texts: list[FloatingText] = []
        # 数字键 1/2/3 选技能；选中后点击红格释放；选中移动模式时点击蓝格移动
        self._selected_skill_index: int = 0  # 0=基础攻击（默认）
        # Day 8：HUD + 背包界面 + 统计
        self.hud: HUD = HUD()
        self._inventory_menu: InventoryMenu | None = None
        self._kills: int = 0  # 击杀数
        self._counted_kills: set[int] = set()  # 已计入击杀的敌人 id
        self._last_loot_desc: str = ""
        # Day 9：测试模式（T 键切换，开局送全套物品用于测试装备系统）
        self._test_mode: bool = False
        # 商店：当前打开的商店界面 / 各房间库存（按房间 id 保留已售状态）
        self._shop_menu: ShopMenu | None = None
        self._shop_stocks: dict[int, list] = {}
        # 休息房间：当前打开的休息界面 / 各房间是否已使用（按房间 id）
        self._rest_menu: RestMenu | None = None
        self._rest_used: set[int] = set()

    # ========== 生命周期 ==========

    def enter(self):
        # 从存档恢复（菜单"继续游戏"）
        if self._load_data is not None:
            self._restore_from_save_data(self._load_data)
        else:
            self.floor = Floor(level=1)
            self.player = Player(position=self.floor.player_spawn)
            self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
        self._load_data = None  # 消费后清空
        self._update_camera()
        self._update_current_room()

    def _restore_from_save_data(self, data: dict) -> None:
        """根据存档数据重建楼层与玩家（属性/背包/装备/位置/击杀数）。"""
        level = data.get("level", 1)
        self.floor = Floor(level=level, seed=data.get("floor_seed"))
        self.player = Player()  # 先用默认属性创建，apply_save_to_player 覆盖
        save_manager.apply_save_to_player(self.player, data)
        px, py = data["player"]["x"], data["player"]["y"]
        self.player.move_to(px, py)
        self._kills = data.get("kills", 0)
        # 恢复已清空房间（避免读档后重复刷怪）
        self._cleared_room_positions = {
            (c[0], c[1]) for c in data.get("cleared_rooms", [])
        }
        # 记录击杀计数集合清空（新会话内不追踪历史敌人 id）
        self._counted_kills.clear()
        self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)

    def exit(self):
        # 离开 PlayState（如暂停、切结算）时自动存档，形成检查点
        if self.player is not None and self.floor is not None:
            self._autosave()

    def _autosave(self) -> None:
        """把当前进度写入存档。"""
        if self.player is None or self.floor is None:
            return
        save_manager.save_game(
            self.player,
            level=self.floor.level,
            floor_seed=self.floor.seed,
            pos=self.player.position,
            kills=self._kills,
            cleared_rooms=self._cleared_room_positions,
        )

    # ========== 输入 ==========

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            # ESC → 商店/休息界面开着则先关闭；否则 Day 8：暂停
            if event.key == pygame.K_ESCAPE:
                if self._shop_menu is not None:
                    self._shop_menu = None
                    return
                if self._rest_menu is not None:
                    self._rest_menu = None
                    return
                from src.states.pause_state import PauseState
                self.game.push_state(PauseState(self.game, play_state=self))
                return

            # I 键 → 打开/关闭背包
            if event.key == pygame.K_i:
                if self._inventory_menu is None:
                    self._inventory_menu = InventoryMenu(
                        self.player.inventory,
                        on_use_item=self._use_inventory_item,
                    )
                else:
                    self._inventory_menu = None
                return

            # 背包打开时只响应 I/Esc
            if self._inventory_menu is not None:
                return

            # 商店/休息界面打开时只响应 Esc（已在上面处理）与鼠标点击
            if self._shop_menu is not None or self._rest_menu is not None:
                return

            if self.mode == PlayMode.EXPLORE:
                # WASD/方向键 → 尝试移动
                dx, dy = 0, 0
                if event.key in (pygame.K_w, pygame.K_UP): dy = -1
                elif event.key in (pygame.K_s, pygame.K_DOWN): dy = 1
                elif event.key in (pygame.K_a, pygame.K_LEFT): dx = -1
                elif event.key in (pygame.K_d, pygame.K_RIGHT): dx = 1
                if dx != 0 or dy != 0:
                    self._try_explore_move(dx, dy)
                # Day 9：T 键切换测试模式（送全套物品）
                elif event.key == pygame.K_t:
                    self._toggle_test_mode()

            elif self.mode == PlayMode.BATTLE:
                # 空格/回车 → 结束回合
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if self.battle and self.battle.is_player_turn:
                        self.battle.end_player_turn()
                        self._after_player_action()
                # 数字键 1-6 切换技能（6 个技能：2 物理 + 4 元素）
                elif event.key in (
                    pygame.K_1, pygame.K_2, pygame.K_3,
                    pygame.K_4, pygame.K_5, pygame.K_6,
                ):
                    idx = int(pygame.key.name(event.key)) - 1
                    if idx < len(self.player.skills):
                        self._selected_skill_index = idx
                        self._compute_battle_highlights()
                # M 键切回移动模式（不消耗 AP 选择）
                elif event.key == pygame.K_m:
                    self._selected_skill_index = -1  # -1 = 移动模式
                    self._compute_battle_highlights()
                # H 键使用药水（找第一个药水槽位）
                elif event.key == pygame.K_h:
                    self._use_first_potion()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 背包打开时点击背包
            if self._inventory_menu is not None:
                self._inventory_menu.handle_click(event.pos)
                return
            # 商店打开时点击商店
            if self._shop_menu is not None:
                self._shop_menu.handle_click(event.pos)
                return
            # 休息界面打开时点击休息界面
            if self._rest_menu is not None:
                self._rest_menu.handle_click(event.pos)
                return
            if self.mode == PlayMode.BATTLE:
                self._handle_battle_click(event.pos)
            else:
                # 探索模式：点击商店/休息房间的地图图标进入
                self._handle_explore_click(event.pos)

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

        # 状态处理日志显示（冻结/眩晕等）
        if self.battle and self.battle.last_status_logs:
            self._last_loot_desc = "；".join(self.battle.last_status_logs)
            self.battle.last_status_logs = []

        # Day 8：更新 HUD
        self.hud.update(
            self.player, self.floor,
            battle=self.battle, mode=self.mode,
            loot_desc=self._last_loot_desc,
        )

    # ========== 探索模式 ==========

    def _try_explore_move(self, dx: int, dy: int) -> None:
        assert self.player and self.floor
        old_pos = self.player.grid_pos
        if self.player.try_move_explore(dx, dy, self.floor.tilemap):
            self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
            self._update_camera()
            self._update_current_room()
            # 站在激活的阶梯上 → 下楼层
            if self._is_on_stair() and old_pos != self.player.grid_pos:
                self._descend_floor()

    def _is_on_stair(self) -> bool:
        """玩家是否站在已激活的阶梯上。"""
        if (
            self.floor is None
            or self.player is None
            or self.floor.stair_pos is None
            or not self.floor.stair_active
        ):
            return False
        return self.player.grid_pos == (
            int(self.floor.stair_pos.x),
            int(self.floor.stair_pos.y),
        )

    def _descend_floor(self) -> None:
        """进入下一层：重建楼层，保留等级/属性/背包/击杀数，更新迷雾。"""
        assert self.player and self.floor
        self.floor = Floor(level=self.floor.level + 1)
        self.player.move_to(
            int(self.floor.player_spawn.x),
            int(self.floor.player_spawn.y),
        )
        self.player.stats.reset_ap()
        self.mode = PlayMode.EXPLORE
        self.battle = None
        self._move_range.clear()
        self._attack_targets.clear()
        self._counted_kills.clear()
        self._cleared_room_positions.clear()  # 新楼层的房间状态重新记录
        self._battles_triggered.clear()
        # 新楼层：清空商店状态（房间是新对象，id 不复用）
        self._shop_menu = None
        self._shop_stocks.clear()
        # 新楼层：清空休息房间状态
        self._rest_menu = None
        self._rest_used.clear()
        self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
        self._update_camera()
        self._update_current_room()
        self._last_loot_desc = (
            f"进入第 {self.floor.level} 层，难度提升 {(self.floor.level - 1) * 20}%"
        )
        # 下楼层后立即存档
        self._autosave()

    def _update_current_room(self) -> None:
        """更新玩家当前所在房间：进入战斗房触发战斗；商店/休息房改为点击地图图标进入。"""
        assert self.player and self.floor
        gx, gy = self.player.grid_x, self.player.grid_y
        for room in self.floor.rooms:
            if room.contains(gx, gy):
                self._current_room = room
                # 进入战斗房且未触发过 → 开战（已清空房间见 _cleared_room_positions，不重复触发）
                if room.room_type in (RoomType.BATTLE, RoomType.ELITE, RoomType.BOSS):
                    center = room.center()
                    if (
                        id(room) not in self._battles_triggered
                        and (int(center.x), int(center.y)) not in self._cleared_room_positions
                    ):
                        self._battles_triggered.add(id(room))
                        self._start_battle(room)
                # 商店/休息房：不自动打开，玩家点击地图图标进入
                return
        self._current_room = None

    # ========== 商店 ==========

    def _open_shop(self, room: Room) -> None:
        """打开商店界面。库存按房间懒创建并保留已售状态。"""
        stock = self._shop_stocks.get(id(room))
        if stock is None:
            stock = self._create_shop_stock()
            self._shop_stocks[id(room)] = stock
        self._shop_menu = ShopMenu(
            self.player,
            stock,
            on_buy=self._buy_shop_item,
            on_close=self._close_shop,
        )

    def _close_shop(self) -> None:
        """关闭商店界面。"""
        self._shop_menu = None

    def _create_shop_stock(self) -> list:
        """商店库存（固定全库存 + 价格）。"""
        from src.items.potion import HealthPotion, StrengthPotion
        from src.items.weapon import create_iron_sword, create_long_bow
        return [
            (create_iron_sword(), config.SHOP_PRICE_IRON_SWORD),
            (create_long_bow(), config.SHOP_PRICE_LONG_BOW),
            (HealthPotion(), config.SHOP_PRICE_HEALTH_POTION),
            (StrengthPotion(), config.SHOP_PRICE_STRENGTH_POTION),
        ]

    def _buy_shop_item(self, index: int) -> None:
        """购买商品：扣金币、入背包、标记售罄。"""
        shop = self._shop_menu
        if shop is None:
            return
        item, price = shop.stock[index]
        if shop.is_sold(index):
            return
        if self.player.gold < price:
            self._last_loot_desc = "金币不足！"
            return
        if self.player.inventory.is_full:
            self._last_loot_desc = "背包已满！"
            return
        self.player.gold -= price
        self.player.inventory.add(item)
        shop.mark_sold(index)
        self._last_loot_desc = f"购买了 {item.name}"

    # ========== 休息房间 ==========

    def _open_rest(self, room: Room) -> None:
        """打开休息界面。休息/强化每次进房间只能二选一使用一次。"""
        if id(room) in self._rest_used:
            self._last_loot_desc = "此房间已经休息过了"
            return
        unlearned = [s for s in get_skill_pool() if self.player.get_skill(s.id) is None]
        self._rest_menu = RestMenu(
            self.player,
            unlearned,
            on_rest=self._do_rest,
            on_learn=self._do_learn,
            on_close=self._close_rest,
        )

    def _do_rest(self) -> None:
        """休息：回复 50% 最大生命值，本房间不可再用。"""
        if self.player is None or self._current_room is None:
            return
        heal = max(1, self.player.stats.max_hp // 2)
        self.player.stats.heal(heal)
        self._rest_used.add(id(self._current_room))
        self._rest_menu = None
        self._last_loot_desc = f"休息回复了 {heal} HP"

    def _do_learn(self, skill) -> None:
        """强化：学习一个技能，本房间不可再用。"""
        if self.player is None or self._current_room is None:
            return
        self.player.learn_skill(skill.id)
        self._rest_used.add(id(self._current_room))
        self._rest_menu = None
        self._last_loot_desc = f"学会了新技能：{skill.name}"

    def _close_rest(self) -> None:
        """关闭休息界面。"""
        self._rest_menu = None

    # ========== 战斗模式 ==========

    def _start_battle(self, room: Room) -> None:
        """触发一场战斗：生成敌人 + 创建 BattleManager + 计算高亮。"""
        assert self.player and self.floor
        # Day 7：Boss 房生成 Boss；战斗房生成 Slime/Skeleton；精英房生成 1 精英
        from src.entities.enemies.slime import Slime
        from src.entities.enemies.skeleton import Skeleton
        from src.entities.enemies.elite import Elite
        from src.entities.enemies.boss import Boss

        # 多楼层难度缩放：每层敌人 HP/ATK ×(1 + (level-1)*0.2)
        scale = 1.0 + (self.floor.level - 1) * 0.2

        def _scaled(enemy: Enemy) -> Enemy:
            enemy.stats.max_hp = int(enemy.stats.max_hp * scale)
            enemy.stats.hp = enemy.stats.max_hp
            enemy.stats.atk = int(enemy.stats.atk * scale)
            return enemy

        enemies: list[Enemy] = []
        if room.room_type == RoomType.BOSS:
            # Boss 房只放 Boss
            bc = room.center()
            boss = Boss(position=Vector2(int(bc.x), int(bc.y)))
            enemies.append(_scaled(boss))
        elif room.room_type == RoomType.ELITE:
            # 精英房：1 精英（+ 随从骷髅，组成守卫战）
            ec = room.center()
            elite = Elite(position=Vector2(int(ec.x), int(ec.y)))
            enemies.append(_scaled(elite))
            side = Skeleton(position=Vector2(int(ec.x) + 2, int(ec.y)))
            if not (int(ec.x) + 2, int(ec.y)) == self.player.grid_pos:
                enemies.append(_scaled(side))
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
                enemies.append(_scaled(enemy))

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
        bonus = (self.player.stats.attack_range - 1) if skill.id == "basic_attack" else 0
        attack_range = skill.range_cells + bonus

        # BFS 从玩家位置出发，找攻击范围内所有敌人
        # 距离用切比雪夫距离（8 方向），range_cells=1 即相邻 8 格
        # 战棋化：远程目标需视线无遮挡（相邻 1 格恒可见）
        px, py = start
        for (ex, ey), enemy in enemy_pos.items():
            dist = max(abs(ex - px), abs(ey - py))  # 切比雪夫距离
            if dist > attack_range:
                continue
            if dist > 1 and not tilemap.has_line_of_sight(px, py, ex, ey):
                continue
            self._attack_targets[(ex, ey)] = enemy

    def _handle_explore_click(self, mouse_pos: tuple[int, int]) -> None:
        """探索模式点击：点中商店/休息房间的图标格 → 打开对应界面。"""
        assert self.player and self.floor
        ts = config.TILE_SIZE
        cam_x, cam_y = self.camera.x, self.camera.y
        gx = int(mouse_pos[0] / ts + cam_x)
        gy = int(mouse_pos[1] / ts + cam_y)
        # 只能进入玩家当前所在房间的图标（避免隔空点远处商店）
        room = self._current_room
        if room is None or not room.contains(gx, gy):
            return
        if room.room_type == RoomType.SHOP:
            self._open_shop(room)
        elif room.room_type == RoomType.REST:
            self._open_rest(room)

    def _handle_battle_click(self, mouse_pos: tuple[int, int]) -> None:
        """
        战斗中鼠标点击：
        - 红格（攻击目标）→ 使用当前选中技能攻击（AoE 技能附带溅射/穿透）
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
                # 战棋化：远程技能需视线无遮挡（相邻 1 格恒通过）
                dist = max(abs(gx - self.player.grid_x), abs(gy - self.player.grid_y))
                if dist > 1 and not self.floor.tilemap.has_line_of_sight(
                    self.player.grid_x, self.player.grid_y, gx, gy
                ):
                    return
                # AoE 副目标（火球溅射 / 雷击穿透）
                secondaries = self._aoe_secondary_enemies(skill, target)
                # Day 5 统一走 SkillAction（含基础攻击 1.0×），元素系统传入技能元素
                action = SkillAction(
                    actor=self.player,
                    target=target,
                    skill_id=skill.id,
                    multiplier=skill.multiplier,
                    ap_cost=skill.ap_cost,
                    skill_name=skill.name,
                    element=skill.element,
                    apply_effect=skill.apply_effect,
                )
                if self.battle.execute_action(action):
                    self._spawn_damage_floating_text()
                    # 副目标结算：不耗 AP、直接 execute（跳过回合切换检查）
                    for extra in secondaries:
                        extra_action = SkillAction(
                            actor=self.player,
                            target=extra,
                            skill_id=skill.id,
                            multiplier=skill.multiplier,
                            ap_cost=0,
                            skill_name=skill.name,
                            element=skill.element,
                            apply_effect=skill.apply_effect,
                        )
                        extra_action.execute(self.battle)
                        self._spawn_damage_floating_text()
                    self._after_player_action()
            return

        # 点击可移动格子 → MoveAction
        if (gx, gy) in self._move_range and (gx, gy) != self.player.grid_pos:
            action = MoveAction(self.player, Vector2(gx, gy), ap_cost=1)
            if self.battle.execute_action(action):
                self._after_player_action()
            return

    # ========== AoE 范围计算（战棋化） ==========

    def _splash_cells(self, center: tuple[int, int]) -> set[tuple[int, int]]:
        """以 center 为中心的 3×3 溅射范围（切比雪夫半径 SPLASH_RADIUS）。"""
        r = config.SPLASH_RADIUS
        cx, cy = center
        return {
            (cx + dx, cy + dy)
            for dx in range(-r, r + 1)
            for dy in range(-r, r + 1)
        }

    def _line_beam_cells(
        self, start: tuple[int, int], target: tuple[int, int], max_range: int
    ) -> list[tuple[int, int]]:
        """
        直线穿透光束：从 start 经 target 沿同方向延伸至 max_range。
        遇墙即断（障碍柱可阻挡雷击光束），返回不含起点的格子序列。
        """
        px, py = start
        tx, ty = target
        tilemap = self.floor.tilemap
        line = list(tilemap._line_cells(px, py, tx, ty))  # 含起点
        if len(line) < 2:
            return []
        cells = line[1:]  # 排除自身格
        # 沿最后一步的方向延伸
        sdx = line[-1][0] - line[-2][0]
        sdy = line[-1][1] - line[-2][1]
        cx, cy = tx + sdx, ty + sdy
        steps = max(abs(tx - px), abs(ty - py))
        while steps < max_range:
            if not tilemap.in_bounds(cx, cy):
                break
            if tilemap.get_tile(cx, cy) == TileType.WALL:
                break
            cells.append((cx, cy))
            cx += sdx
            cy += sdy
            steps += 1
        return cells

    def _aoe_secondary_enemies(self, skill, primary) -> list:
        """按技能 AoE 形态返回主目标之外的受影响敌人。"""
        if skill.aoe == "none" or self.battle is None:
            return []
        alive = [
            e for e in self.battle.enemies
            if e is not primary and not e.stats.is_dead()
        ]
        if skill.aoe == "splash":
            cells = self._splash_cells(primary.grid_pos)
            return [e for e in alive if e.grid_pos in cells]
        if skill.aoe == "line":
            beam = set(self._line_beam_cells(
                self.player.grid_pos, primary.grid_pos, skill.range_cells
            ))
            return [e for e in alive if e.grid_pos in beam]
        return []

    def _get_aoe_preview_cells(self) -> set[tuple[int, int]]:
        """鼠标悬停目标时计算 AoE 预览格（供高亮渲染）。"""
        if self.battle is None or not self.battle.is_player_turn:
            return set()
        if self.player is None or self.floor is None:
            return set()
        skills = self.player.skills
        if not (0 <= self._selected_skill_index < len(skills)):
            return set()
        skill = skills[self._selected_skill_index]
        if skill.aoe == "none":
            return set()
        mouse = pygame.mouse.get_pos()
        ts = config.TILE_SIZE
        gx = int(mouse[0] / ts + self.camera.x)
        gy = int(mouse[1] / ts + self.camera.y)
        if (gx, gy) not in self._attack_targets:
            return set()
        if skill.aoe == "splash":
            return self._splash_cells((gx, gy))
        return set(self._line_beam_cells(
            self.player.grid_pos, (gx, gy), skill.range_cells
        ))

    def _spawn_damage_floating_text(self) -> None:
        """根据 battle.last_damage_result 生成飘字（含元素着色与反应提示）。"""
        assert self.battle
        result = self.battle.last_damage_result
        target = self.battle.last_damage_target
        if result is None or target is None:
            return
        ts = config.TILE_SIZE
        sx = (target.position.x - self.camera.x) * ts + ts // 4
        sy = (target.position.y - self.camera.y) * ts - 4
        # 飘字文本：暴击加感叹号
        text = f"-{result.damage}" + ("!" if result.is_crit else "")
        # 颜色：元素技能用元素色，否则按暴击/普通
        if result.element is not Element.NONE:
            color = ELEMENT_COLOR[result.element]
        elif result.is_crit:
            color = (255, 220, 80)  # 暴击黄色
        else:
            color = (255, 80, 80)   # 普通红色
        self._floating_texts.append(FloatingText(text, sx, sy, color))
        # 元素反应：飘白色大字
        if result.reaction is not None:
            self._floating_texts.append(
                FloatingText(f"{REACTION_NAME[result.reaction]}!", sx, sy - 16, (255, 255, 255))
            )
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
        # Day 8：更新击杀计数（敌人死亡时）
        for enemy in self.battle.enemies:
            if enemy.stats.is_dead() and id(enemy) not in self._counted_kills:
                self._kills += 1
                self._counted_kills.add(id(enemy))
                # 商店经济：击杀掉落金币
                self.player.gold += enemy.gold_reward
        # 战斗结束
        if self.battle.phase == TurnPhase.BATTLE_WON:
            is_boss = self._last_room and self._last_room.room_type == RoomType.BOSS
            # 记录已清空房间（存档用），读档后不重复刷怪
            if self._last_room is not None:
                center = self._last_room.center()
                self._cleared_room_positions.add((int(center.x), int(center.y)))
            self._end_battle(victory=True)
            # 击败 Boss：激活下行阶梯（Boss 房中心）
            if is_boss:
                self.floor.stair_active = True
                # 把 Boss 房中心瓦片改为阶梯，便于渲染与踩踏检测
                if self.floor.stair_pos is not None:
                    self.floor.tilemap.set_tile(
                        int(self.floor.stair_pos.x),
                        int(self.floor.stair_pos.y),
                        TileType.STAIR,
                    )
                self._last_loot_desc += " | 阶梯已开启，前往 Boss 房中心下楼"
                # 到达最高层 → 通关结算；否则留在本层找楼梯
                if self.floor.level >= config.MAX_FLOOR_LEVEL:
                    self._goto_game_over(victory=True)
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
            # Day 8：玩家死亡跳转 GameOver
            self._goto_game_over(victory=False)
            return
        self._compute_battle_highlights()

    def _goto_game_over(self, victory: bool) -> None:
        """Day 8：跳转到结算界面。本局结束，清除存档避免死局被恢复。"""
        from src.states.game_over_state import GameOverState
        # 统计击杀数与战利品
        loot_names = []
        for item in self.player.inventory.slots:
            if item is not None:
                loot_names.append(item.name)
        stats = {
            "kills": self._kills,
            "floor": self.floor.level,
            "time": "00:00",  # Day 9 加计时
            "gold": self.player.gold,
            "loot": loot_names,
        }
        self.game.change_state(GameOverState(self.game, victory=victory, stats=stats))
        # change_state 会触发本状态 exit() 的自动存档重写，故在切换完成后清档
        save_manager.clear_save()

    def _end_battle(self, victory: bool) -> None:
        """结束战斗，切回探索模式。"""
        # Day 7：先处理掉落（battle 仍可用）
        loot_desc = ""
        if victory and self._last_room:
            if self._last_room.room_type == RoomType.BOSS:
                loot_desc = self._drop_boss_loot()
            elif self._last_room.room_type == RoomType.ELITE:
                loot_desc = self._drop_elite_loot()
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

    def _drop_elite_loot(self) -> str:
        """精英掉落：30% 长弓，40% 铁剑，30% 力量药水。返回掉落描述。"""
        import random
        from src.items.potion import StrengthPotion
        from src.items.weapon import create_iron_sword, create_long_bow
        roll = random.random()
        if roll < 0.3:
            self.player.inventory.add(create_long_bow())
            return "获得：长弓"
        elif roll < 0.7:
            self.player.inventory.add(create_iron_sword())
            return "获得：铁剑"
        else:
            self.player.inventory.add(StrengthPotion())
            return "获得：力量药水"

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
            # Boss 房击败后（阶梯已激活）不再显示"王"标签，避免与楼梯重叠
            if room.room_type == RoomType.BOSS and self.floor.stair_active:
                continue
            # 商店/休息房间：绘制可点击的色块图标
            if room.room_type in (RoomType.SHOP, RoomType.REST):
                self._draw_room_icon(screen, room, cam_x, cam_y, ts)
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
                    self._draw_enemy_overhead(screen, enemy, cam_x, cam_y)

        # ---------- 第六层：玩家 ----------
        self.player.render(screen, cam_x, cam_y)

        # ---------- 第七层：飘字 ----------
        for ft in self._floating_texts:
            ft.draw(screen, self.game.font)

        # ---------- 第八层：HUD ----------
        self.hud.draw(screen, self.game.font)
        # 战斗模式：技能栏
        if self.mode == PlayMode.BATTLE:
            self._draw_skill_bar(screen)
        # 背包界面
        if self._inventory_menu is not None:
            self._inventory_menu.update(0)
            self._inventory_menu.draw(screen, self.game.font)
        # 商店界面
        if self._shop_menu is not None:
            self._shop_menu.update(0)
            self._shop_menu.draw(screen, self.game.font)
        # 休息界面
        if self._rest_menu is not None:
            self._rest_menu.update(0)
            self._rest_menu.draw(screen, self.game.font)

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

        # AoE 预览：悬停目标时橙色高亮溅射/穿透范围
        preview = self._get_aoe_preview_cells()
        if preview:
            aoe_surf = self._get_highlight_surface((255, 160, 40, 90), ts)
            for (gx, gy) in preview:
                if (gx, gy) == self.player.grid_pos:
                    continue
                sx = int((gx - cam_x) * ts)
                sy = int((gy - cam_y) * ts)
                screen.blit(aoe_surf, (sx, sy))

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

    def _draw_room_icon(self, screen, room: Room, cam_x: float, cam_y: float, ts: int) -> None:
        """绘制商店/休息房间的可点击色块图标（房间中心）。"""
        center = room.center()
        sx = int((center.x - cam_x) * ts + ts // 2)
        sy = int((center.y - cam_y) * ts + ts // 2)
        size = int(ts * 0.75)
        rect = pygame.Rect(sx - size // 2, sy - size // 2, size, size)
        # 商店金色 / 休息绿色
        color = (230, 210, 60) if room.room_type == RoomType.SHOP else (120, 220, 120)
        pygame.draw.rect(screen, color, rect, border_radius=4)
        pygame.draw.rect(screen, (255, 255, 255), rect, 2, border_radius=4)
        # 图标标记：商店"¥" / 休息"+"（用文字简写）
        mark = "¥" if room.room_type == RoomType.SHOP else "+"
        text_surf = self.game.font_small.render(mark, True, (20, 20, 20))
        text_rect = text_surf.get_rect(center=rect.center)
        screen.blit(text_surf, text_rect)

    def _draw_enemy_overhead(self, screen, enemy, cam_x: float, cam_y: float) -> None:
        """敌人头顶标记：附着元素外圈描边 + 状态效果小字。"""
        ts = config.TILE_SIZE
        sx = int((enemy.position.x - cam_x) * ts)
        sy = int((enemy.position.y - cam_y) * ts)
        # 附着元素：瓦片外圈按元素着色
        aura = enemy.status_effects.aura
        if aura is not None and aura is not Element.NONE:
            pygame.draw.rect(screen, ELEMENT_COLOR[aura], (sx, sy, ts, ts), 3)
        # 状态效果：敌人头顶小字
        effects = enemy.status_effects.all
        if effects:
            labels = [EFFECT_DISPLAY_NAME[e.effect_type] for e in effects]
            text_surf = self.game.font.render(" ".join(labels), True, (255, 255, 255))
            screen.blit(text_surf, (sx + ts // 2 - text_surf.get_width() // 2, sy - 14))

    def _draw_skill_bar(self, screen) -> None:
        """绘制技能选择栏：图形图标 + 快捷键角标；悬停图标显示技能说明。"""
        assert self.player
        skills = self.player.skills
        bar_y = 88  # Day 8：避开 HUD 的 HP/AP 条（8~76 像素）
        bar_x = 10
        slot_size = 46
        gap = 8
        mouse_pos = pygame.mouse.get_pos()
        hovered_skill: Skill | None = None
        hovered_rect: pygame.Rect | None = None
        for i, skill in enumerate(skills):
            rect = pygame.Rect(bar_x + i * (slot_size + gap), bar_y, slot_size, slot_size)
            # 选中态高亮
            is_selected = (i == self._selected_skill_index)
            bg = (60, 80, 120) if is_selected else (30, 30, 40)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            border_color = config.COLOR_TEXT_HIGHLIGHT if is_selected else config.GRAY
            pygame.draw.rect(screen, border_color, rect, 2, border_radius=4)
            # 技能图形图标
            self._draw_skill_icon(screen, skill, rect)
            # 快捷键数字角标（左上角）
            num_surf = self.game.font_small.render(str(i + 1), True, (20, 20, 20))
            pygame.draw.rect(screen, (255, 255, 255), (rect.x, rect.y, 15, 15))
            screen.blit(num_surf, (rect.x + 2, rect.y + 1))
            # AP 充足时右下角显示 AP 消耗
            if self.player.stats.ap >= skill.ap_cost:
                ap_surf = self.game.font_small.render(f"{skill.ap_cost}AP", True, (190, 220, 255))
                screen.blit(ap_surf, (rect.right - ap_surf.get_width() - 3, rect.bottom - ap_surf.get_height() - 1))
            # AP 不足时整格灰显
            if self.player.stats.ap < skill.ap_cost:
                overlay = pygame.Surface((slot_size, slot_size), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 160))
                screen.blit(overlay, rect)
            # 悬停检测
            if rect.collidepoint(mouse_pos):
                hovered_skill = skill
                hovered_rect = rect
        # 移动模式标记（尾部补一个移动图标格）
        move_rect = pygame.Rect(
            bar_x + len(skills) * (slot_size + gap), bar_y, slot_size, slot_size
        )
        is_move = self._selected_skill_index < 0
        pygame.draw.rect(screen, (60, 120, 80) if is_move else (30, 30, 40), move_rect, border_radius=4)
        pygame.draw.rect(screen, config.COLOR_TEXT_HIGHLIGHT if is_move else config.GRAY, move_rect, 2, border_radius=4)
        # 移动图标：向右箭头
        pygame.draw.polygon(screen, (120, 220, 140), [
            (move_rect.centerx - 5, move_rect.centery - 9),
            (move_rect.centerx + 9, move_rect.centery),
            (move_rect.centerx - 5, move_rect.centery + 9),
        ])
        # 悬停移动格也提示
        if move_rect.collidepoint(mouse_pos):
            hovered_skill = Skill(
                id="move_mode", name="移动模式", ap_cost=0, range_cells=0,
                multiplier=1.0, desc="点击蓝色格子移动，不消耗技能。按 M 键切换。",
            )
            hovered_rect = move_rect
        # 悬停说明面板
        if hovered_skill is not None and hovered_rect is not None:
            self._draw_skill_tooltip(screen, hovered_skill, hovered_rect)

    # ========== 技能图标绘制 ==========

    def _draw_skill_icon(self, screen, skill: Skill, rect: pygame.Rect) -> None:
        """在图标格内绘制技能图形（按技能类型/元素区分）。"""
        cx, cy = rect.centerx, rect.centery
        if skill.id == "basic_attack":
            self._draw_sword(screen, cx, cy, (200, 200, 210))
        elif skill.id == "charge_slash":
            self._draw_sword(screen, cx, cy, (255, 160, 90), slash=True)
        elif skill.element is Element.FIRE:
            self._draw_flame(screen, cx, cy, ELEMENT_COLOR[Element.FIRE])
        elif skill.element is Element.ICE:
            self._draw_snowflake(screen, cx, cy, ELEMENT_COLOR[Element.ICE])
        elif skill.element is Element.WATER:
            self._draw_droplet(screen, cx, cy, ELEMENT_COLOR[Element.WATER])
        elif skill.element is Element.LIGHTNING:
            self._draw_bolt(screen, cx, cy, ELEMENT_COLOR[Element.LIGHTNING])

    @staticmethod
    def _draw_sword(screen, cx: int, cy: int, color, slash: bool = False) -> None:
        """剑形图标。slash=True 时画成斜斩。"""
        if not slash:
            pygame.draw.polygon(screen, color, [
                (cx - 4, cy - 13), (cx + 4, cy - 13), (cx, cy - 6),
            ])  # 剑尖
            pygame.draw.line(screen, color, (cx, cy - 12), (cx, cy + 6), 3)  # 剑身
            pygame.draw.line(screen, color, (cx - 6, cy + 6), (cx + 6, cy + 6), 3)  # 护手
            pygame.draw.line(screen, color, (cx, cy + 6), (cx, cy + 11), 3)  # 剑柄
        else:
            # 斜斩：两道交叉弧线（简单用斜线模拟挥砍轨迹）
            pygame.draw.line(screen, color, (cx - 11, cy + 9), (cx + 9, cy - 11), 3)
            pygame.draw.line(screen, color, (cx - 7, cy + 11), (cx + 11, cy - 7), 3)

    @staticmethod
    def _draw_flame(screen, cx: int, cy: int, color) -> None:
        """火苗图标：外圈火 + 亮色内核。"""
        pygame.draw.circle(screen, color, (cx - 2, cy + 3), 8)
        pygame.draw.polygon(screen, color, [
            (cx - 6, cy - 1), (cx + 6, cy - 1), (cx, cy - 12),
        ])  # 火苗尖
        pygame.draw.circle(screen, (255, 240, 180), (cx - 2, cy + 2), 4)

    @staticmethod
    def _draw_snowflake(screen, cx: int, cy: int, color) -> None:
        """冰晶图标：六角雪花（三条交叉轴）。"""
        for i in range(3):
            import math
            ang = math.radians(i * 60)
            dx, dy = math.cos(ang) * 10, math.sin(ang) * 10
            pygame.draw.line(screen, color, (cx - dx, cy - dy), (cx + dx, cy + dy), 2)

    @staticmethod
    def _draw_droplet(screen, cx: int, cy: int, color) -> None:
        """水滴图标：圆 + 顶部尖。"""
        pygame.draw.circle(screen, color, (cx, cy + 3), 7)
        pygame.draw.polygon(screen, color, [
            (cx - 6, cy + 1), (cx + 6, cy + 1), (cx, cy - 10),
        ])

    @staticmethod
    def _draw_bolt(screen, cx: int, cy: int, color) -> None:
        """闪电图标：折线多边形。"""
        pygame.draw.polygon(screen, color, [
            (cx + 4, cy - 12), (cx - 5, cy + 1), (cx - 1, cy + 1),
            (cx - 4, cy + 12), (cx + 5, cy - 1), (cx + 1, cy - 1),
        ])

    # ========== 技能说明面板（悬停） ==========

    def _draw_skill_tooltip(self, screen, skill: Skill, anchor: pygame.Rect) -> None:
        """悬停技能图标时绘制说明面板。"""
        element_tag = "" if skill.element is Element.NONE else f"· {ELEMENT_NAME[skill.element]}属性"
        # 战棋化标签：AoE 形态 / 附加状态
        aoe_tag = {"splash": "  3×3溅射", "line": "  直线穿透"}.get(skill.aoe, "")
        effect_tag = f"  附加{EFFECT_DISPLAY_NAME[skill.apply_effect]}" if skill.apply_effect else ""
        title_color = (
            ELEMENT_COLOR[skill.element]
            if skill.element is not Element.NONE else config.COLOR_TEXT_HIGHLIGHT
        )
        lines: list[tuple[str, tuple, object]] = [
            (skill.name, title_color, self.game.font),
            (
                f"消耗 {skill.ap_cost} AP  倍率 {skill.multiplier}×  射程 {skill.range_cells} 格{element_tag}{aoe_tag}{effect_tag}",
                config.COLOR_TEXT, self.game.font_small,
            ),
            (skill.desc, (200, 200, 200), self.game.font_small),
        ]
        pad = 8
        line_h = 18
        panel_w = max(font.size(t)[0] for t, _, font in lines) + pad * 2
        panel_h = pad * 2 + line_h * len(lines)
        x = anchor.x
        y = anchor.bottom + 6
        if y + panel_h > config.SCREEN_HEIGHT - 10:
            y = anchor.top - panel_h - 6
        if x + panel_w > config.SCREEN_WIDTH - 10:
            x = config.SCREEN_WIDTH - panel_w - 10
        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((20, 20, 30, 235))
        screen.blit(bg, (x, y))
        pygame.draw.rect(screen, (110, 110, 130), (x, y, panel_w, panel_h), 1, border_radius=4)
        for idx, (text, color, font) in enumerate(lines):
            surf = font.render(text, True, color)
            screen.blit(surf, (x + pad, y + pad + idx * line_h))

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

    def _use_inventory_item(self, slot: int) -> None:
        """Day 8：从背包界面使用物品。"""
        inv = self.player.inventory
        item = inv.get_item(slot)
        if item is None:
            return
        hp_before = self.player.stats.hp
        inv.use_item(slot, self.player)
        # 如果是药水且回血了，生成治疗飘字
        from src.items.item import ItemType
        if item.item_type == ItemType.POTION:
            healed = self.player.stats.hp - hp_before
            if healed > 0:
                ts = config.TILE_SIZE
                sx = (self.player.position.x - self.camera.x) * ts + ts // 4
                sy = (self.player.position.y - self.camera.y) * ts - 4
                self._floating_texts.append(
                    FloatingText(f"+{healed}", sx, sy, (100, 255, 100))
                )
            self._last_loot_desc = f"使用 {item.name}"

    def _toggle_test_mode(self) -> None:
        """Day 9：切换测试模式，送全套物品用于测试装备系统。"""
        self._test_mode = not self._test_mode
        if self._test_mode:
            from src.items.weapon import create_iron_sword, create_long_bow
            from src.items.potion import HealthPotion, StrengthPotion
            self.player.inventory.add(create_iron_sword())
            self.player.inventory.add(create_long_bow())
            self.player.inventory.add(HealthPotion())
            self.player.inventory.add(HealthPotion())
            self.player.inventory.add(StrengthPotion())
            self.player.gold += 100  # 商店经济：送金币便于测试购买
            self._last_loot_desc = "[测试模式] 已获得全套物品+100金币，按 I 打开背包"
        else:
            self._last_loot_desc = "[测试模式] 关闭"
