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
from src.combat.status_effect import EFFECT_DISPLAY_NAME, EffectType
from src.core import config
from src.core import save_manager
from src.core.asset_manager import resource_root
from src.entities.enemy import Enemy
from src.entities.player import Player, Skill, get_skill_pool
from src.states.base_state import BaseState
from src.ui.hud import HUD
from src.ui.icons import get_element_icon
from src.ui.menu import InventoryMenu, PotionTargetMenu, RestMenu, ShopMenu
from src.utils.vector import Vector2
from src.world.floor import Floor
from src.world.fog_of_war import FogState
from src.world.room import Room, RoomType
from src.world.tilemap import TileType


# ========== 渲染颜色表（tile → 颜色；有贴图的瓦片优先用贴图） ==========
_TILE_COLORS: dict[TileType, tuple[int, int, int]] = {
    TileType.WALL: config.COLOR_WALL,
    TileType.FLOOR: config.COLOR_FLOOR,
    TileType.DOOR: config.COLOR_DOOR,
    TileType.TRAP: (180, 40, 40),
    TileType.STAIR: config.COLOR_STAIR,
}

# 瓦片贴图缓存（懒加载，缺失时回退色块）。来源 assets/images/tiles/game/
_TILE_SURFACE_NAMES: dict[TileType, str] = {
    TileType.FLOOR: "floor.png",
    TileType.WALL: "wall.png",
    TileType.STAIR: "stair.png",
}
_TILE_SURFACES: dict[TileType, "pygame.Surface | None"] = {}

# 游戏瓦片贴图目录（兼容开发与 PyInstaller 打包环境）
_TILE_GAME_DIR = resource_root() / "assets" / "images" / "tiles" / "game"


def _get_tile_surface(tile: TileType) -> "pygame.Surface | None":
    """返回瓦片贴图（首次加载后缓存）；素材缺失返回 None 走色块回退。"""
    if tile not in _TILE_SURFACES:
        name = _TILE_SURFACE_NAMES.get(tile)
        path = _TILE_GAME_DIR / name if name else None
        if path and path.exists():
            _TILE_SURFACES[tile] = pygame.image.load(str(path)).convert_alpha()
        else:
            _TILE_SURFACES[tile] = None
    return _TILE_SURFACES[tile]


# 房间障碍柱贴图（区别于边界墙），与瓦片贴图同样懒加载
_OBSTACLE_SURFACE: list["pygame.Surface | None"] = []


def _get_obstacle_surface() -> "pygame.Surface | None":
    """返回障碍柱贴图（首次加载后缓存）；素材缺失返回 None 走色块回退。"""
    if not _OBSTACLE_SURFACE:
        path = _TILE_GAME_DIR / "obstacle.png"
        _OBSTACLE_SURFACE.append(
            pygame.image.load(str(path)).convert_alpha() if path.exists() else None
        )
    return _OBSTACLE_SURFACE[0]

_ROOM_TYPE_LABEL: dict[RoomType, tuple[str, tuple[int, int, int]]] = {
    RoomType.BATTLE: ("战", config.COLOR_ENEMY),
    RoomType.ELITE:  ("精", config.COLOR_ELITE),
    RoomType.BOSS:   ("王", config.COLOR_BOSS),
    RoomType.SHOP:   ("商", (230, 210, 60)),
    RoomType.REST:   ("休", (120, 220, 120)),
    RoomType.START:  ("始", config.COLOR_PLAYER),
}

# ========== 方向键 → 网格方向映射（WASD 与方向键等价） ==========
_DIR_VECTORS: dict[int, tuple[int, int]] = {
    pygame.K_d: (1, 0), pygame.K_RIGHT: (1, 0),
    pygame.K_a: (-1, 0), pygame.K_LEFT: (-1, 0),
    pygame.K_s: (0, 1), pygame.K_DOWN: (0, 1),
    pygame.K_w: (0, -1), pygame.K_UP: (0, -1),
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
        # 元素头顶小图标缓存（元素 → 16×16 Surface，懒加载避免每帧新建）
        self._aura_icon_cache: dict = {}
        # 数字键 1/2/3 选技能；选中后点击红格释放；选中移动模式时点击蓝格移动
        self._selected_skill_index: int = 0  # 0=基础攻击（默认）
        # Day 8：HUD + 背包界面 + 统计
        self.hud: HUD = HUD()
        self._inventory_menu: InventoryMenu | None = None
        self._kills: int = 0  # 击杀数
        self._counted_kills: set[int] = set()  # 已计入击杀的敌人 id
        # 动画：死亡演出中的尸体（死亡动画播完后移除）、探索静止计时
        self._dying: list[Enemy] = []
        self._idle_timer: float = 99.0
        # 探索长按连续行走：移动冷却（按住方向键每格间隔，衔接滑步动画）
        self._move_cooldown: float = 0.0
        # 方向键按下顺序表（最新在末尾）：两轴冲突时最后按下的方向优先
        self._key_order: list[int] = []
        self._last_loot_desc: str = ""
        # Day 9：测试模式（T 键切换，开局送全套物品用于测试装备系统）
        self._test_mode: bool = False
        # 商店：当前打开的商店界面 / 各房间库存（按房间 id 保留已售状态）
        self._shop_menu: ShopMenu | None = None
        self._shop_stocks: dict[int, list] = {}
        # 休息房间：当前打开的休息界面 / 各房间是否已使用（按房间 id）
        self._rest_menu: RestMenu | None = None
        self._rest_used: set[int] = set()
        # 药水使用对象选择：待用药槽位 + 选择菜单（伙伴存活时背包点击药水弹出）
        self._pending_potion_slot: int = -1
        self._potion_target_menu: PotionTargetMenu | None = None
        # 玩家死亡演出：等待敌人攻击动画播完再跳结算（避免画面生硬）
        self._pending_lost: bool = False
        # 友方单位列表（阶段 3：可控伙伴；未来可追加更多同类角色）。
        # 现有代码通过 _companion property 读取第一个伙伴，新增角色 append 即可。
        self._allies: list = []

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
        self.player.move_to(px, py, instant=True)
        self._kills = data.get("kills", 0)
        # 恢复已清空房间（避免读档后重复刷怪）
        self._cleared_room_positions = {
            (c[0], c[1]) for c in data.get("cleared_rooms", [])
        }
        # 记录击杀计数集合清空（新会话内不追踪历史敌人 id）
        self._counted_kills.clear()
        # 恢复伙伴（仅存活时创建；独立 AP 池无叠加风险）
        self._restore_companion_from_save(data)
        self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)

    def _restore_companion_from_save(self, data) -> None:
        """从存档恢复伙伴。

        - 存档存在且存活 → 重建实体 + 恢复属性/位置/技能，追加进 _allies。
          伙伴持有独立 AP 池（2 点/回合），不再给主角 +1 AP 上限。
        - 伙伴死亡/从未召唤 → 不创建（死亡后本局永久消失）。
        - 旧档 ap_bonus_active 字段仅作兼容读取，不再承担 AP 语义。
        """
        assert self.player is not None and self.floor is not None
        if self._allies:
            return
        c = data.get("companion")
        if not c or not c.get("exists") or not c.get("alive", c.get("ap_bonus_active")):
            return
        from src.entities.companion import Companion
        companion = Companion(position=Vector2(c.get("x", 0), c.get("y", 0)))
        companion.stats.max_hp = c.get("max_hp", 15)
        companion.stats.hp = min(c.get("hp", 15), companion.stats.max_hp)
        companion.stats.atk = c.get("atk", 3)
        companion.stats.def_ = c.get("def_", 3)
        # 位置校验：存档位置不可走（理论上同种子地图一致，保险兜底）→ 就近放玩家身边
        if not self.floor.tilemap.is_walkable(companion.grid_x, companion.grid_y):
            gx, gy = self._companion_spawn_position()
            companion.move_to(gx, gy, instant=True)
        for sid in c.get("skills", []):
            if companion.get_skill(sid) is None:
                companion.learn_skill(sid)
        companion.alive = True
        self._allies.append(companion)

    def exit(self):
        # 离开 PlayState（如暂停、切结算）时自动存档，形成检查点
        if self.player is not None and self.floor is not None:
            self._autosave()

    def _autosave(self) -> None:
        """把当前进度写入存档（含伙伴状态）。"""
        if self.player is None or self.floor is None:
            return
        save_manager.save_game(
            self.player,
            level=self.floor.level,
            floor_seed=self.floor.seed,
            pos=self.player.position,
            kills=self._kills,
            cleared_rooms=self._cleared_room_positions,
            companion=self._companion,
        )

    # ========== 输入 ==========

    def handle_event(self, event):
        # 方向键按下顺序记录（任何界面状态下都维护，保证长按方向状态一致）
        if event.type == pygame.KEYUP:
            if event.key in self._key_order:
                self._key_order.remove(event.key)
            return
        if (
            event.type == pygame.KEYDOWN
            and not getattr(event, "repeat", False)
            and event.key in _DIR_VECTORS
        ):
            # 过滤系统按键重复；重复收到已在列表中的键（异常情况）则移到最新
            if event.key in self._key_order:
                self._key_order.remove(event.key)
            self._key_order.append(event.key)

        if event.type == pygame.KEYDOWN:
            # ESC → 药水对象选择/商店/休息/背包界面开着则先关闭；否则 Day 8：暂停
            if event.key == pygame.K_ESCAPE:
                if self._potion_target_menu is not None:
                    self._close_potion_target()
                    return
                if self._shop_menu is not None:
                    self._shop_menu = None
                    return
                if self._rest_menu is not None:
                    self._rest_menu = None
                    return
                if self._inventory_menu is not None:
                    self._close_inventory()
                    return
                from src.states.pause_state import PauseState
                self.game.push_state(PauseState(self.game, play_state=self))
                return

            # V 键 → 收起/展开状态面板（避免血条挡住地图上的敌人）
            if event.key == pygame.K_v:
                self.hud.toggle()
                return

            # B 键 → 打开/关闭背包（药水对象选择开着时先关闭它）
            if event.key == pygame.K_b:
                if self._potion_target_menu is not None:
                    self._close_potion_target()
                    return
                # 商店/休息界面打开时按 B 不响应（同 ESC 拦截逻辑，
                # 避免背包与商店层叠：商店画在背包上层但点击先给背包，导致关不掉商店）
                if self._shop_menu is not None or self._rest_menu is not None:
                    return
                if self._inventory_menu is None:
                    self._inventory_menu = InventoryMenu(
                        self.player.inventory,
                        on_use_item=self._use_inventory_item,
                        on_close=self._close_inventory,
                    )
                else:
                    self._close_inventory()
                return

            # 背包打开时只响应 B/Esc
            if self._inventory_menu is not None:
                return

            # 商店/休息界面打开时只响应 Esc（已在上面处理）与鼠标点击
            if self._shop_menu is not None or self._rest_menu is not None:
                return

            if self.mode == PlayMode.EXPLORE:
                # 移动由 update() 轮询按键处理（支持长按连续行走）
                # Day 9：T 键切换测试模式（送全套物品）
                if event.key == pygame.K_t:
                    self._toggle_test_mode()

            elif self.mode == PlayMode.BATTLE:
                # 空格/回车 → 结束回合
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if self.battle and self.battle.is_player_turn:
                        self.battle.end_player_turn()
                        self._after_player_action()
                # Tab → 循环切换受控实体（在存活友方单位之间轮转；只有玩家时无效）
                elif event.key == pygame.K_TAB and self.battle is not None:
                    alive = self.battle.friendly_entities
                    if len(alive) > 1:
                        idx = alive.index(self.battle.current_actor)
                        self._switch_actor(alive[(idx + 1) % len(alive)])
                # 数字键 1-6 切换技能（按当前受控实体的技能表）
                elif event.key in (
                    pygame.K_1, pygame.K_2, pygame.K_3,
                    pygame.K_4, pygame.K_5, pygame.K_6,
                ):
                    idx = int(pygame.key.name(event.key)) - 1
                    actor = self.battle.current_actor if self.battle else self.player
                    if idx < len(actor.skills):
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
            # HUD 收起按钮（最高优先级）
            if self.hud.toggle_rect.collidepoint(event.pos):
                self.hud.toggle()
                return
            # 药水使用对象选择菜单（优先于背包）
            if self._potion_target_menu is not None:
                self._potion_target_menu.handle_click(event.pos)
                return
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
                # 头像栏点击优先于战场点击（命中头像格时不再处理战场）
                if not self._handle_actor_bar_click(event.pos):
                    self._handle_battle_click(event.pos)
            else:
                # 探索模式：点击商店/休息房间的地图图标进入
                self._handle_explore_click(event.pos)

    def update(self, dt):
        """每帧推进敌人回合 + 飘字动画 + 实体动画。"""
        # 飘字更新（无论何种模式）
        if self._floating_texts:
            self._floating_texts = [t for t in self._floating_texts if t.update(dt)]

        # 实体动画推进（玩家 / 战斗敌人 / 死亡演出）
        if self.player is not None:
            # 长按方向键期间匀速滑动（避免每格重复加减速导致顿挫）
            holding = self.mode == PlayMode.EXPLORE and any(self._read_direction_keys())
            self.player.update_visual(dt, linear=holding)  # 平滑移动插值
            if self.player.animator is not None:
                self.player.animator.update(dt)
        for e in self._dying:
            e.update_visual(dt)
            if e.animator is not None:
                e.animator.update(dt)
        # 死亡动画播完 → 移出演出列表（消失）
        self._dying = [
            e for e in self._dying
            if e.animator is not None and not e.animator.is_finished
        ]
        if self.battle is not None:
            # 阶段 3/4：伙伴死亡 → 本局永久消失（独立 AP 池，无需回退主角 AP）
            if self._companion is not None and not self._companion.alive:
                self._on_companion_death()
            for e in self.battle.enemies:
                if not e.stats.is_dead():
                    e.update_visual(dt)  # 平滑移动插值
                    if e.animator is not None:
                        e.animator.update(dt)
                        e.tick_idle(dt)  # 走完静止超时 → 回待机，避免原地踏步
                    e.tick_fx(dt)  # 子类特效层推进（Boss AOE 粒子）
            # 阶段 3：友方单位动画推进（存活时；占位色块模式下 animator 为 None）
            for c in self.battle.allies:
                if c is self.player or not c.alive:
                    continue
                c.update_visual(dt)
                if c.animator is not None:
                    c.animator.update(dt)

        # 相机每帧跟随玩家视觉位置（平滑移动时镜头同步滑动）
        self._update_camera()

        # 静止超时 → 回待机动画（阈值需大于 walk 一轮时长，避免长按时被
        # 系统按键重复间隔打断；仅打断 walk，不碰 attack/death）
        if self.player is not None:
            self._idle_timer += dt
            if (
                self._idle_timer > 0.7
                and self.player.animator is not None
                and self.player.animator.current.startswith("walk")
            ):
                self.player.play_anim("idle")

        # 探索模式：按住方向键连续行走（轮询按键状态，无需连点）
        if self.mode == PlayMode.EXPLORE:
            self._update_explore_movement(dt)

        if self.mode == PlayMode.BATTLE and self.battle:
            if self.battle.is_enemy_turn:
                self.battle.step_enemy_turn()
                # 敌人攻击后生成飘字（敌人攻击玩家时）
                self._spawn_enemy_damage_floating_text()
                self._after_enemy_turn()

        # 玩家死亡演出结束（敌人攻击动画播完）→ 跳转结算
        if self._pending_lost and self.battle is not None:
            if not any(
                e.animator is not None and e.animator.current.startswith("attack")
                for e in self.battle.enemies
            ):
                self._pending_lost = False
                self._end_battle(victory=False)
                self._goto_game_over(victory=False)
                return

        # 状态处理日志显示（冻结/眩晕等）
        if self.battle and self.battle.last_status_logs:
            self._last_loot_desc = "；".join(self.battle.last_status_logs)
            self.battle.last_status_logs = []

        # Day 8：更新 HUD
        self.hud.update(
            self.player, self.floor,
            battle=self.battle, mode=self.mode,
            loot_desc=self._last_loot_desc,
            companion=self._companion,
        )

    # ========== 探索模式 ==========

    def _update_explore_movement(self, dt: float) -> None:
        """
        长按连续行走：轮询方向键，冷却结束即走一格。

        冷却间隔与滑步动画时长一致，按住时角色连续滑动不顿挫；
        任何界面（背包/商店/休息）打开时不响应移动。
        """
        if self.player is None or self.floor is None:
            return
        if (
            self._inventory_menu is not None
            or self._shop_menu is not None
            or self._rest_menu is not None
            or self._potion_target_menu is not None
        ):
            return
        self._move_cooldown -= dt
        if self._move_cooldown > 0:
            return
        dx, dy = self._read_direction_keys()
        if dx != 0 or dy != 0:
            self._try_explore_move(dx, dy)
            # 略短于动画时长：在滑步完成前衔接下一格，消除格间空窗停顿
            # （move_to 从当前视觉位置出发，速度连续；松开后末段自动减速）
            self._move_cooldown = config.MOVE_ANIM_DURATION * 0.8

    def _read_direction_keys(self) -> tuple[int, int]:
        """
        读取按住的方向键 → (dx, dy)，最后按下的方向优先。

        两轴冲突（如 W+A）时取最新按下的方向键单轴移动；松开后自动
        回退到仍在按住的次新方向。只认 get_pressed() 中仍按住的键，
        防止 KEYUP 丢失（如窗口失焦）产生幽灵方向。
        """
        keys = pygame.key.get_pressed()
        for key in reversed(self._key_order):
            if keys[key]:
                return _DIR_VECTORS[key]
        return (0, 0)

    def _try_explore_move(self, dx: int, dy: int) -> None:
        assert self.player and self.floor
        old_pos = self.player.grid_pos
        self.player.face(dx, dy)
        self._idle_timer = 0.0
        if self.player.try_move_explore(dx, dy, self.floor.tilemap):
            self.player.play_anim("walk")
            self.floor.fog.update_visibility(self.player.position, tilemap=self.floor.tilemap)
            self._update_camera()
            self._update_current_room()
            # 伙伴同步跟随（若本步触发了战斗则内部自动跳过）
            self._companion_follow_step()
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
            instant=True,
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
        # 新楼层：清空药水目标选择
        self._close_potion_target()
        # 友方单位换层：旧楼层坐标在新地图可能撞墙，直接放回玩家身边
        for a in self._allies:
            gx, gy = self._companion_spawn_position()
            a.move_to(gx, gy, instant=True)
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
            unlearned_talents=self.player.unlearned_talents(),
            on_rest=self._do_rest,
            on_learn=self._do_learn,
            on_learn_talent=self._do_learn_talent,
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

    def _do_learn_talent(self, talent) -> None:
        """强化：学习一个天赋（属性永久生效），本房间不可再用。"""
        if self.player is None or self._current_room is None:
            return
        if self.player.learn_talent(talent.id):
            # 召唤伙伴：创建实体并挂载（伙伴独立 2 AP/回合，不影响主角 AP）
            if talent.id == "summon_companion":
                self._spawn_companion()
            self._rest_used.add(id(self._current_room))
            self._rest_menu = None
            self._last_loot_desc = f"习得天赋：{talent.name}（{talent.desc}）"

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
            # 战斗房敌人数量：L2 起 +1（1 史莱姆 + 2 骷髅），提高远程压力
            num = 3 if (
                room.room_type == RoomType.BATTLE and self.floor.level >= 2
            ) else 2 if room.room_type == RoomType.BATTLE else 1
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

        # 阶段 3：战斗开始时把友方单位放到主角身边空位（探索中只保存引用，不参与渲染）
        alive_allies = [a for a in self._allies if a.alive]
        for ally in alive_allies:
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                gx, gy = self.player.grid_x + dx, self.player.grid_y + dy
                if (
                    self.floor.tilemap.is_walkable(gx, gy)
                    and (gx, gy) not in {e.grid_pos for e in enemies}
                    and (gx, gy) not in {a.grid_pos for a in alive_allies if a is not ally}
                ):
                    ally.position = Vector2(gx, gy)
                    break
        self.battle = BattleManager(
            self.player, enemies, self.floor.tilemap, companions=alive_allies or None
        )
        self.mode = PlayMode.BATTLE
        # 独立 AP 池：玩家与伙伴各自重置行动点（玩家 5 / 伙伴 2）
        self.player.stats.reset_ap()
        for a in alive_allies:
            a.stats.reset_ap()
        self.battle.last_action_desc = f"遭遇 {len(enemies)} 个敌人！"
        self._last_room = room  # Day 7：记录当前房间用于掉落
        self._compute_battle_highlights()

    def _compute_battle_highlights(self) -> None:
        """
        BFS 计算玩家可移动范围（按 move_range 限制）与可攻击目标。
        Day 5：攻击范围按当前选中技能的 range_cells 计算。
        """
        assert self.player and self.floor and self.battle
        actor = self.battle.current_actor
        self._move_range.clear()
        self._attack_targets.clear()

        start = actor.grid_pos
        move_range = actor.stats.move_range
        tilemap = self.floor.tilemap
        enemy_pos = {e.grid_pos: e for e in self.battle.enemies if not e.stats.is_dead()}
        # 阶段 3：友方单位（除自己）位置不可停留，避免与伙伴/主角重叠
        friendly_blocked = {e.grid_pos for e in self.battle.friendly_entities if e is not actor}

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
                # 友方单位占据的格子不可进入（避免单位重叠）
                if (nx, ny) in friendly_blocked:
                    continue
                # 被敌人占据的格子不能移动到，但 BFS 可以穿过敌人记录距离
                if (nx, ny) in enemy_pos:
                    visited[(nx, ny)] = dist + 1
                    continue
                visited[(nx, ny)] = dist + 1
                # 锁门：未清空战斗房前，房间外格子不可走也不显示
                locked_room = self._current_room if self._is_battle_room_locked() else None
                if locked_room is None or locked_room.contains(nx, ny):
                    self._move_range[(nx, ny)] = dist + 1
                queue.append(((nx, ny), dist + 1))

        # --- 攻击范围：按当前技能 range_cells ---
        # _selected_skill_index = -1 表示纯移动模式，不显示攻击范围
        if self._selected_skill_index < 0:
            return
        skills = actor.skills
        if self._selected_skill_index >= len(skills):
            return
        skill = skills[self._selected_skill_index]
        bonus = (actor.stats.attack_range - 1) if skill.id == "basic_attack" else 0
        attack_range = skill.range_cells + bonus

        # 自身目标技能（如伙伴反击姿态 range_cells=0）：点击自己所在格施放
        if attack_range <= 0:
            self._attack_targets[actor.grid_pos] = actor
            return

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

    def _is_battle_room_locked(self) -> bool:
        """当前所在战斗/精英/Boss 房是否处于锁门状态（已开战且未全灭）。"""
        room = self._current_room
        if room is None or room.room_type not in (
            RoomType.BATTLE, RoomType.ELITE, RoomType.BOSS,
        ):
            return False
        center = room.center()
        return (
            id(room) in self._battles_triggered
            and (int(center.x), int(center.y)) not in self._cleared_room_positions
        )

    def _switch_actor(self, actor) -> bool:
        """切换当前受控实体：成功则重置技能选中（默认第一技能）并重算高亮。"""
        if self.battle is None or not self.battle.switch_actor(actor):
            return False
        self._selected_skill_index = 0  # 切到谁就默认选它的第一个技能
        self._compute_battle_highlights()
        return True

    def _handle_battle_click(self, mouse_pos: tuple[int, int]) -> None:
        """
        战斗中鼠标点击：
        - 红格（攻击目标）→ 使用当前选中技能攻击（AoE 技能附带溅射/穿透）
        - 蓝格（可移动）→ 移动
        """
        assert self.player and self.floor and self.battle
        if not self.battle.is_player_turn:
            return
        actor = self.battle.current_actor
        ts = config.TILE_SIZE
        cam_x, cam_y = self.camera.x, self.camera.y
        gx = int(mouse_pos[0] / ts + cam_x)
        gy = int(mouse_pos[1] / ts + cam_y)

        # 点击可攻击格子 → AttackAction/SkillAction
        if (gx, gy) in self._attack_targets:
            target = self._attack_targets[(gx, gy)]
            skills = actor.skills
            if 0 <= self._selected_skill_index < len(skills):
                skill = skills[self._selected_skill_index]
                # 嘲讽每回合限 1 次：已用则提示并终止（0 AP 免费技能防刷仇恨）
                if skill.id == "taunt" and getattr(actor, "taunt_used_this_turn", False):
                    self._spawn_player_hint("嘲讽每回合只能使用一次")
                    return
                # 战棋化：远程技能需视线无遮挡（相邻 1 格恒通过）
                dist = max(abs(gx - actor.grid_x), abs(gy - actor.grid_y))
                if dist > 1 and not self.floor.tilemap.has_line_of_sight(
                    actor.grid_x, actor.grid_y, gx, gy
                ):
                    return
                # AoE 副目标（火球溅射 / 雷击穿透）
                secondaries = self._aoe_secondary_enemies(skill, target)
                # Day 5 统一走 SkillAction（含基础攻击 1.0×），元素系统传入技能元素
                action = SkillAction(
                    actor=actor,
                    target=target,
                    skill_id=skill.id,
                    multiplier=skill.multiplier,
                    ap_cost=skill.ap_cost,
                    skill_name=skill.name,
                    element=skill.element,
                    apply_effect=skill.apply_effect,
                    effect_duration=skill.effect_duration,
                    effect_chance=skill.effect_chance,
                )
                if self.battle.execute_action(action):
                    self._spawn_damage_floating_text()
                    # 副目标结算：不耗 AP、直接 execute（跳过回合切换检查）
                    for extra in secondaries:
                        extra_action = SkillAction(
                            actor=actor,
                            target=extra,
                            skill_id=skill.id,
                            multiplier=skill.multiplier,
                            ap_cost=0,
                            skill_name=skill.name,
                            element=skill.element,
                            apply_effect=skill.apply_effect,
                            effect_duration=skill.effect_duration,
                            effect_chance=skill.effect_chance,
                        )
                        extra_action.execute(self.battle)
                        self._spawn_damage_floating_text()
                    self._after_player_action()
            return

        # 点击可移动格子 → MoveAction
        if (gx, gy) in self._move_range and (gx, gy) != actor.grid_pos:
            # 锁门：未清空战斗房前不可走出房间
            if self._is_battle_room_locked():
                room = self._current_room
                if room is not None and not room.contains(gx, gy):
                    sx = (
                        (actor.visual_pos.x - self.camera.x) * ts
                        + ts // 4
                    )
                    sy = (
                        (actor.visual_pos.y - self.camera.y) * ts
                        - 4
                    )
                    self._floating_texts.append(
                        FloatingText("消灭所有敌人后才能离开!", sx, sy, (255, 220, 120))
                    )
                    return
            action = MoveAction(actor, Vector2(gx, gy), ap_cost=1)
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
        actor = self.battle.current_actor
        skills = actor.skills
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
            actor.grid_pos, (gx, gy), skill.range_cells
        ))

    def _spawn_damage_floating_text(self) -> None:
        """根据 battle.last_damage_result 生成飘字（含元素着色与反应提示）。"""
        assert self.battle
        result = self.battle.last_damage_result
        target = self.battle.last_damage_target
        if result is None or target is None:
            return
        ts = config.TILE_SIZE
        sx = (target.visual_pos.x - self.camera.x) * ts + ts // 4
        sy = (target.visual_pos.y - self.camera.y) * ts - 4
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
        # 受击动画（存活且有 hurt 状态时，如骷髅）
        if not target.stats.is_dead():
            if target.animator is not None and target.animator.has("hurt"):
                target.animator.play("hurt", restart=True)
        # 清除一次性标记，避免重复生成
        self.battle.last_damage_result = None
        self.battle.last_damage_target = None

    def _spawn_enemy_damage_floating_text(self) -> None:
        """敌人攻击友方时生成飘字（飘在受击者头顶）；
        反击姿态触发的反击单独飘在攻击者头顶（与主伤害同时显示）。"""
        assert self.battle
        ts = config.TILE_SIZE
        result = self.battle.last_damage_result
        target = self.battle.last_damage_target
        if result is not None and target is not None:
            sx = (target.visual_pos.x - self.camera.x) * ts + ts // 4
            sy = (target.visual_pos.y - self.camera.y) * ts - 4
            self._floating_texts.append(
                FloatingText(f"-{result.damage}", sx, sy, (255, 100, 100))
            )
        # 反击姿态：反击伤害飘在攻击者头顶
        cres = self.battle.last_counter_result
        ctarget = self.battle.last_counter_target
        if cres is not None and ctarget is not None:
            sx = (ctarget.visual_pos.x - self.camera.x) * ts + ts // 4
            sy = (ctarget.visual_pos.y - self.camera.y) * ts - 4
            self._floating_texts.append(
                FloatingText(f"反击 -{cres.damage}", sx, sy, (255, 220, 120))
            )
            self.battle.last_counter_result = None
            self.battle.last_counter_target = None
        self.battle.last_damage_result = None
        self.battle.last_damage_target = None

    def _spawn_player_hint(self, text: str, color=(255, 220, 120)) -> None:
        """在玩家头顶生成提示飘字（如 AP 耗尽），与伤害飘字错开。"""
        ts = config.TILE_SIZE
        sx = (self.player.visual_pos.x - self.camera.x) * ts + ts // 4
        sy = (self.player.visual_pos.y - self.camera.y) * ts - 16
        self._floating_texts.append(FloatingText(text, sx, sy, color))

    def _after_player_action(self) -> None:
        """玩家执行行动后：刷新高亮、迷雾、相机，检查战斗结束。"""
        assert self.player and self.floor and self.battle
        # 动画：有新行动输入，静止计时清零（walk 播完 0.7s 后自然回 idle）
        self._idle_timer = 0.0
        # Day 8：更新击杀计数（敌人死亡时）
        for enemy in self.battle.enemies:
            if enemy.stats.is_dead() and id(enemy) not in self._counted_kills:
                self._kills += 1
                self._counted_kills.add(id(enemy))
                # 商店经济：击杀掉落金币
                self.player.gold += enemy.gold_reward
                # 死亡动画演出：加入尸体列表，播完后消失。
                # 防御：素材缺 death 帧表时不进演出列表（直接消失），避免卡尸
                enemy.play_anim("death", restart=True)
                if (
                    enemy.animator is not None
                    and enemy.animator.has("death")
                    and enemy not in self._dying
                ):
                    self._dying.append(enemy)
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
        # AP 耗尽：提示手动结束回合（不自动切换；按当前受控实体各自的池判断）
        if self.battle.current_actor.stats.ap <= 0:
            self._spawn_player_hint("AP已耗尽")

    def _after_enemy_turn(self) -> None:
        """敌人回合结束，回到玩家回合：刷新 AP 与高亮。"""
        assert self.player and self.battle
        if self.battle.phase == TurnPhase.BATTLE_LOST:
            # 玩家死亡：不立即跳结算，先让敌人攻击动画播完再跳转
            self._pending_lost = True
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
        # 跟随受控实体：战斗时跟 current_actor（平滑移动时镜头同步滑动）
        follow = (
            self.battle.current_actor
            if self.battle is not None and self.mode == PlayMode.BATTLE
            else self.player
        )
        cam_target_x = follow.visual_pos.x - tiles_x / 2
        cam_target_y = follow.visual_pos.y - tiles_y / 2
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

        # ---------- 第一层：瓦片（有贴图用贴图，缺失回退色块） ----------
        obstacles = self.floor.obstacle_tiles
        for gy in range(gy_start, gy_end):
            for gx in range(gx_start, gx_end):
                tile = tilemap.get_tile(gx, gy)
                # 障碍柱（房间内单格墙）与边界墙使用不同贴图
                if tile == TileType.WALL and (gx, gy) in obstacles:
                    surf = _get_obstacle_surface()
                else:
                    surf = _get_tile_surface(tile)
                sx = int((gx - cam_x) * ts)
                sy = int((gy - cam_y) * ts)
                if surf is not None:
                    screen.blit(surf, (sx, sy))
                else:
                    color = _TILE_COLORS.get(tile, config.COLOR_WALL)
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
                    enemy.facing_left = self.player.position.x < enemy.position.x
                    enemy.render(screen, cam_x, cam_y)
                    self._draw_entity_overhead(screen, enemy, cam_x, cam_y)
        # 死亡演出中的尸体（死亡动画播放期间仍可见）
        for corpse in self._dying:
            corpse.facing_left = self.player.position.x < corpse.position.x
            corpse.render(screen, cam_x, cam_y)

        # ---------- 第五点五层：友方单位（战斗中出现；占位色块 + 头顶血条） ----------
        if self.battle is not None:
            for c in self.battle.allies:
                if c is self.player or not c.alive:
                    continue
                c.facing_left = self.player.position.x < c.position.x
                c.render(screen, cam_x, cam_y)
                self._draw_entity_overhead(screen, c, cam_x, cam_y)

        # ---------- 第六层：玩家 ----------
        self.player.render(screen, cam_x, cam_y)
        self._draw_entity_overhead(screen, self.player, cam_x, cam_y)

        # ---------- 第七层：飘字 ----------
        for ft in self._floating_texts:
            ft.draw(screen, self.game.font)

        # ---------- 第八层：HUD ----------
        self.hud.draw(screen, self.game.font)
        # 战斗模式：技能栏 + 受控实体头像栏
        if self.mode == PlayMode.BATTLE:
            self._draw_skill_bar(screen)
            self._draw_actor_bar(screen)
        # 背包界面
        if self._inventory_menu is not None:
            self._inventory_menu.update(0)
            self._inventory_menu.draw(screen, self.game.font)
        # 药水使用对象选择菜单（叠在背包之上）
        if self._potion_target_menu is not None:
            self._potion_target_menu.update(0)
            self._potion_target_menu.draw(screen, self.game.font)
        # 商店界面
        if self._shop_menu is not None:
            self._shop_menu.update(0)
            self._shop_menu.draw(screen, self.game.font)
        # 休息界面
        if self._rest_menu is not None:
            self._rest_menu.update(0)
            self._rest_menu.draw(screen, self.game.font, self.game.font_small)

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

    def _draw_entity_overhead(self, screen, entity, cam_x: float, cam_y: float) -> None:
        """实体头顶标记（玩家/伙伴/敌人通用）：元素附着图标+剩余回合数 + 状态效果小字。
        元素图标为预缩放缓存 Surface（避免每帧新建），状态结束（附着/时长归零）自动消失。"""
        ts = config.TILE_SIZE
        sx = int((entity.visual_pos.x - cam_x) * ts)
        sy = int((entity.visual_pos.y - cam_y) * ts)
        # 附着元素：瓦片外圈按元素着色 + 头顶图标与剩余回合数
        aura = entity.status_effects.aura
        if aura is not None and aura is not Element.NONE:
            pygame.draw.rect(screen, ELEMENT_COLOR[aura], (sx, sy, ts, ts), 3)
            cx = sx + ts // 2
            icon = self._aura_overhead_icon(aura)
            if icon is not None:
                screen.blit(icon, (cx - icon.get_width() // 2, sy - 30))
                # 剩余回合数：图标右下角小数字
                turns = self.game.font_small.render(
                    str(entity.status_effects.aura_remaining), True, (255, 255, 255)
                )
                screen.blit(turns, (cx + icon.get_width() // 2 - 5, sy - 24))
            else:
                # 无素材回退：元素名首字 + 元素色
                t = self.game.font.render(ELEMENT_NAME[aura][0], True, ELEMENT_COLOR[aura])
                screen.blit(t, (cx - t.get_width() // 2, sy - 30))
        # 状态效果：头顶小字（眩晕/护盾/减速等）
        effects = entity.status_effects.all
        if effects:
            labels = [EFFECT_DISPLAY_NAME[e.effect_type] for e in effects]
            text_surf = self.game.font.render(" ".join(labels), True, (255, 255, 255))
            screen.blit(text_surf, (sx + ts // 2 - text_surf.get_width() // 2, sy - 14))

    def _aura_overhead_icon(self, element) -> "pygame.Surface | None":
        """元素头顶小图标（16×16）：首次缩放后缓存，避免每帧创建 Surface。"""
        if element not in self._aura_icon_cache:
            full = get_element_icon(element)
            icon = pygame.transform.scale(full, (16, 16)) if full is not None else None
            self._aura_icon_cache[element] = icon
        return self._aura_icon_cache[element]

    # ========== 阶段 5：受控实体头像栏（友方单位列表） ==========

    def _draw_actor_bar(self, screen) -> None:
        """绘制底部头像栏：玩家/伙伴头像 + HP 条 + 状态徽标。
        选中者金色边框高亮；伙伴死亡后头像变灰（不可点击）。
        按 allies 列表渲染，新增友方单位自动多出一个头像格。"""
        if self.mode != PlayMode.BATTLE or self.battle is None:
            return
        bar_y = config.SCREEN_HEIGHT - 56
        x = 10
        for a in self.battle.allies:
            if a is self.player:
                label, color = "玩", config.COLOR_PLAYER
            else:
                label, color = "伴", config.COLOR_COMPANION
            self._draw_actor_slot(screen, x, bar_y, a, label, color)
            x += 44 + 8

    def _draw_actor_slot(self, screen, x: int, bar_y: int, actor, label: str, color) -> None:
        """画单个头像格（44×44）+ HP 条；选中者金色加粗边框 + 顶部三角；死亡灰化。"""
        assert self.battle is not None and self.player is not None
        size = 44
        dead = actor.stats.hp <= 0
        selected = (not dead) and self.battle.current_actor is actor
        rect = pygame.Rect(x, bar_y, size, size)
        bg = (70, 100, 65) if selected else (30, 30, 40)
        pygame.draw.rect(screen, bg, rect, border_radius=6)
        if selected:
            border = config.COLOR_TEXT_HIGHLIGHT  # 金色边框高亮
            pygame.draw.rect(screen, border, rect, 3, border_radius=6)
            # 顶部小三角指示当前受控
            tri = [
                (rect.centerx - 6, rect.y - 6),
                (rect.centerx + 6, rect.y - 6),
                (rect.centerx, rect.y + 2),
            ]
            pygame.draw.polygon(screen, config.COLOR_TEXT_HIGHLIGHT, tri)
        else:
            border = (90, 90, 100) if dead else config.GRAY
            pygame.draw.rect(screen, border, rect, 2, border_radius=6)
        # 主体色块（占位头像）+ 名字首字；死亡时整体灰化
        body_color = (60, 60, 60) if dead else color
        pygame.draw.rect(screen, body_color, rect.inflate(-10, -10), border_radius=4)
        if dead:
            text = self.game.font_small.render("亡", True, (120, 120, 120))
        else:
            text = self.game.font_small.render(label, True, (255, 255, 255))
        screen.blit(text, (rect.centerx - text.get_width() // 2, rect.y + 2))
        # HP 条（格下方）；死亡为空条
        hp_ratio = 0.0 if dead else max(0.0, actor.stats.hp / actor.stats.max_hp)
        pygame.draw.rect(screen, (60, 20, 20), (rect.x + 2, rect.bottom + 2, size - 4, 4))
        if hp_ratio > 0:
            pygame.draw.rect(
                screen, (120, 220, 120),
                (rect.x + 2, rect.bottom + 2, int((size - 4) * hp_ratio), 4),
            )
        # 选中者右侧显示独立 AP（按受控实体各自池读取：玩家 5 / 伙伴 2）
        if selected:
            ap_surf = self.game.font_small.render(
                f"AP {actor.stats.ap}/{actor.stats.max_ap}",
                True, (190, 220, 255),
            )
            screen.blit(ap_surf, (rect.right + 6, rect.centery - ap_surf.get_height() // 2))
        # 状态徽标（头像格上方）：显示该实体当前挂载的状态效果
        if not dead:
            self._draw_status_badges(screen, rect, actor)

    def _draw_status_badges(self, screen, rect: pygame.Rect, actor) -> None:
        """在头像格上方画一排状态徽标（眩晕/护盾/减速等，每类 16×16 色块 + 首字）。"""
        effects = actor.status_effects.all
        if not effects:
            return
        badge_color = {
            EffectType.STUN: (255, 200, 60),      # 眩晕：金黄
            EffectType.SHIELD: (80, 160, 255),    # 护盾：蓝
            EffectType.FREEZE: (170, 220, 255),   # 冻结：淡蓝
            EffectType.SHOCK: (120, 200, 255),    # 感电：亮蓝
            EffectType.DEF_DOWN: (255, 120, 80),  # 破甲：橙红
            EffectType.SLOW: (180, 130, 255),     # 减速：紫
            EffectType.MELT: (255, 90, 60),       # 融化：红橙
            EffectType.OVERLOAD: (255, 150, 40),  # 超载：橙
            EffectType.TAUNT: (255, 80, 80),      # 嘲讽：红
        }
        bsize = 16
        gap = 2
        y0 = rect.y - bsize - 3
        for i, e in enumerate(effects[:4]):
            bx = rect.x + i * (bsize + gap)
            pygame.draw.rect(
                screen, badge_color.get(e.effect_type, (200, 200, 200)),
                (bx, y0, bsize, bsize), border_radius=3,
            )
            ch = EFFECT_DISPLAY_NAME.get(e.effect_type, "?")[0]
            t = self.game.font_small.render(ch, True, (20, 20, 30))
            screen.blit(t, (bx + bsize // 2 - t.get_width() // 2, y0 + 1))
        if len(effects) > 4:
            more = self.game.font_small.render(f"+{len(effects) - 4}", True, (230, 230, 230))
            screen.blit(more, (rect.x + 4 * (bsize + gap) + 2, y0))

    def _handle_actor_bar_click(self, mouse_pos) -> bool:
        """点击头像格 → 切换受控实体；命中返回 True，未命中返回 False。
        伙伴死亡后头像灰化：命中但不可切换（吞掉点击，避免误触战场）。"""
        if self.mode != PlayMode.BATTLE or self.battle is None:
            return False
        bar_y = config.SCREEN_HEIGHT - 56
        x = 10
        for a in self.battle.allies:
            if pygame.Rect(x, bar_y, 44, 44).collidepoint(mouse_pos):
                if a.alive:
                    self._switch_actor(a)
                return True
            x += 44 + 8
        return False

    def _draw_skill_bar(self, screen) -> None:
        """绘制技能选择栏：图形图标 + 快捷键角标；悬停图标显示技能说明。"""
        assert self.player
        skills = (
            self.battle.current_actor.skills
            if self.battle is not None
            else self.player.skills
        )
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
            # AP 不足时整格灰显（图标灰化，AP 文字在格下方不受影响）
            if self.player.stats.ap < skill.ap_cost:
                overlay = pygame.Surface((slot_size, slot_size), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 160))
                screen.blit(overlay, rect)
            # 图标下方居中显示 AP 消耗（始终可见；AP 不足时灰色）
            ap_color = (190, 220, 255) if self.player.stats.ap >= skill.ap_cost else (120, 120, 130)
            ap_surf = self.game.font_small.render(f"{skill.ap_cost}AP", True, ap_color)
            screen.blit(ap_surf, (rect.centerx - ap_surf.get_width() // 2, rect.bottom + 1))
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
        """在图标格内绘制技能图形：元素技能用贴图，无元素技能用手绘。"""
        cx, cy = rect.centerx, rect.centery
        if skill.element is not Element.NONE:
            icon = get_element_icon(skill.element)
            if icon is not None:
                # 32×32 素材放大到 40×40 居中（最近邻保持像素风）
                scaled = pygame.transform.scale(icon, (40, 40))
                screen.blit(scaled, (cx - 20, cy - 20))
                return
        if skill.id == "basic_attack":
            self._draw_sword(screen, cx, cy, (200, 200, 210))
        elif skill.id == "charge_slash":
            self._draw_sword(screen, cx, cy, (255, 160, 90), slash=True)
        elif skill.id == "taunt":
            self._draw_shield(screen, cx, cy, (255, 120, 120))
        elif skill.id == "counter_stance":
            self._draw_shield(screen, cx, cy, (120, 220, 160), bash=True)
        elif skill.id == "shield_bash":
            self._draw_shield(screen, cx, cy, (230, 190, 120), bash=True)
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
    def _draw_shield(screen, cx: int, cy: int, color, bash: bool = False) -> None:
        """盾牌图标。bash=True 时加白色撞击斜线（盾击）。"""
        points = [
            (cx - 12, cy - 10), (cx + 12, cy - 10),
            (cx + 8, cy + 6), (cx, cy + 14), (cx - 8, cy + 6),
        ]
        pygame.draw.polygon(screen, color, points)
        pygame.draw.polygon(screen, (20, 20, 30), points, 2)
        if bash:
            pygame.draw.line(screen, (255, 255, 255), (cx - 11, cy + 11), (cx + 11, cy - 11), 3)

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
        """悬停技能图标时绘制说明面板（元素技能标题前带元素小图标）。"""
        element_tag = "" if skill.element is Element.NONE else f"· {ELEMENT_NAME[skill.element]}属性"
        # 战棋化标签：AoE 形态 / 附加状态
        aoe_tag = {"splash": "  3×3溅射", "line": "  直线穿透"}.get(skill.aoe, "")
        effect_tag = f"  附加{EFFECT_DISPLAY_NAME[skill.apply_effect]}" if skill.apply_effect else ""
        title_color = (
            ELEMENT_COLOR[skill.element]
            if skill.element is not Element.NONE else config.COLOR_TEXT_HIGHLIGHT
        )
        # 元素小图标（16×16，标题左侧；无元素技能不画）
        icon = get_element_icon(skill.element) if skill.element is not Element.NONE else None
        icon_size = 16
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
        title_extra = icon_size + 6 if icon is not None else 0
        panel_w = max(
            font.size(t)[0] + (title_extra if idx == 0 else 0)
            for idx, (t, _, font) in enumerate(lines)
        ) + pad * 2
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
            tx = x + pad
            # 标题行左侧画元素图标，文本右移避开
            if idx == 0 and icon is not None:
                scaled = pygame.transform.scale(icon, (icon_size, icon_size))
                screen.blit(scaled, (tx, y + pad - 2))
                tx += icon_size + 6
            surf = font.render(text, True, color)
            screen.blit(surf, (tx, y + pad + idx * line_h))

    def _use_first_potion(self) -> None:
        """H 键：使用背包里第一个药水，目标为当前受控实体（Tab 切到伙伴后 H 即给伙伴）。"""
        from src.items.item import ItemType
        inv = self.player.inventory
        target = self.player
        if self.battle is not None and self.battle.current_actor is not None:
            target = self.battle.current_actor
        for i in range(inv.MAX_SLOTS):
            item = inv.get_item(i)
            if item is not None and item.item_type == ItemType.POTION:
                self._use_item_on(i, target)
                return

    def _use_inventory_item(self, slot: int) -> None:
        """从背包界面使用物品。药水且伙伴存活 → 弹「使用对象」菜单；否则直接对主角使用。"""
        item = self.player.inventory.get_item(slot)
        if item is None:
            return
        from src.items.item import ItemType
        if item.item_type == ItemType.POTION:
            c = self._companion
            if c is not None and c.alive:
                self._pending_potion_slot = slot
                self._potion_target_menu = PotionTargetMenu(
                    self.player, c,
                    on_use=self._use_potion_on_target,
                )
                return
        self._use_item_on(slot, self.player)

    def _use_potion_on_target(self, target) -> None:
        """药水对象选择确认：对所选目标用药并关闭菜单。"""
        slot = self._pending_potion_slot
        self._close_potion_target()
        if slot >= 0 and self.player.inventory.get_item(slot) is not None:
            self._use_item_on(slot, target)

    def _close_potion_target(self) -> None:
        """关闭药水使用对象菜单。"""
        self._potion_target_menu = None
        self._pending_potion_slot = -1

    def _use_item_on(self, slot: int, target) -> None:
        """对指定目标使用槽位物品；药水回血时在目标头上生成绿色飘字。"""
        inv = self.player.inventory
        item = inv.get_item(slot)
        if item is None:
            return
        from src.items.item import ItemType
        hp_before = target.stats.hp
        inv.use_item(slot, target)
        if item.item_type == ItemType.POTION:
            healed = target.stats.hp - hp_before
            desc = f"使用 {item.name}" if healed <= 0 else f"使用 {item.name}，回复 {healed} HP"
            self._last_loot_desc = desc
            if healed > 0:
                # 在目标头上生成绿色治疗飘字
                ts = config.TILE_SIZE
                sx = (target.visual_pos.x - self.camera.x) * ts + ts // 4
                sy = (target.visual_pos.y - self.camera.y) * ts - 4
                self._floating_texts.append(
                    FloatingText(f"+{healed}", sx, sy, (100, 255, 100))
                )
            if self.battle is not None:
                self.battle.last_action_desc = desc
                self._compute_battle_highlights()

    def _close_inventory(self) -> None:
        """关闭背包界面（B 键 / 关闭按钮 / Esc 共用的单一出口）。"""
        self._inventory_menu = None

    # ========== 伙伴生命周期（阶段 4：独立 AP 池，每回合 2 点） ==========

    @property
    def _companion(self):
        """当前第一个伙伴（兼容旧引用）；无伙伴时返回 None。
        新增同类角色时 append 进 _allies，此处无需改动。"""
        return self._allies[0] if self._allies else None

    def _companion_spawn_position(self) -> tuple[int, int]:
        """找玩家身边可走空位放置伙伴（优先右侧；全堵回退玩家脚下）。

        召唤发生在探索模式（无敌人），只需校验可行走；战斗内放置
        由 _start_battle 按敌人占位进一步排除。
        """
        assert self.player and self.floor
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            gx, gy = self.player.grid_x + dx, self.player.grid_y + dy
            if self.floor.tilemap.is_walkable(gx, gy):
                return gx, gy
        return self.player.grid_x, self.player.grid_y

    def _spawn_companion(self) -> None:
        """创建伙伴并挂载（测试模式 / 休息房天赋共用入口）。
        伙伴独立 AP 池：每回合固定 2 点，不消耗主角 AP（不再 +1 主角上限）。"""
        from src.entities.companion import Companion
        if self._companion is not None:
            return
        gx, gy = self._companion_spawn_position()
        companion = Companion(position=Vector2(gx, gy))
        # 未来新增同类角色：在此追加到 _allies（战斗/回合/UI 全部自动生效）
        self._allies.append(companion)

    def _companion_follow_step(self) -> None:
        """探索模式下伙伴自动跟随：玩家每走一步，伙伴沿 BFS 最短路径走一步。

        保证伙伴不掉队（否则进入新房间触发战斗时，_start_battle 按玩家身边
        空位放置伙伴会因敌人占位失败，导致伙伴以旧房间坐标参战卡死）。
        战斗内/已在玩家身边（含对角、同格）时跳过。
        """
        assert self.player is not None and self.floor is not None
        c = self._companion
        if c is None or self.battle is not None or self.mode != PlayMode.EXPLORE:
            return
        if not c.alive:
            return
        if max(abs(c.grid_x - self.player.grid_x), abs(c.grid_y - self.player.grid_y)) <= 1:
            return
        path = self.floor.tilemap.find_path(
            (c.grid_x, c.grid_y), (self.player.grid_x, self.player.grid_y)
        )
        if len(path) > 1:
            nx, ny = path[1]
            c.move_to(nx, ny, instant=True)
            if c.animator is not None:
                c.play_anim("walk")

    def _on_companion_death(self) -> None:
        """伙伴死亡：本局永久消失（独立 AP 池，无需回退主角 AP 上限）。
        多伙伴时按实体逐个移除，此处仅处理当前第一个伙伴。"""
        if self._companion is None:
            return
        self._allies = [a for a in self._allies if a is not self._companion]
        self._last_loot_desc = "伙伴阵亡了"

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
            # 阶段 3/4：测试模式挂载伙伴（正式入口在阶段 6 休息房天赋）
            if self._companion is None:
                self._spawn_companion()
                if self._companion is not None:
                    # 测试模式顺带学盾击，便于本阶段验收三个伙伴技能
                    self._companion.learn_skill("shield_bash")
                self._last_loot_desc = "[测试模式] 全套物品+100金币+伙伴(嘲讽/反击姿态/盾击)，按 I 开背包"
            else:
                self._last_loot_desc = "[测试模式] 已获得全套物品+100金币，按 I 开背包"
        else:
            self._last_loot_desc = "[测试模式] 关闭"
