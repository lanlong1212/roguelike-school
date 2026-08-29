"""
玩家角色模块。

Day 5 扩展：
    - 增加 skills 技能列表（1 基础攻击 + 2 主动技能）
    - 技能数据类 Skill 含 id/name/ap_cost/range/multiplier/desc
    - 提供 get_skill(id) 与默认技能配置

元素系统扩展：
    - Skill 增加 element 字段（物理/火/水/冰/雷）
    - 新增寒冰箭/水弹/雷击，凑齐 4 种元素技能用于元素反应

休息房间扩展（技能学习）：
    - 玩家初始只拥有 basic_attack
    - _SKILL_POOL 定义可学习技能池，休息房间"强化"从中学习
    - learn_skill(skill_id) 将技能加入已学列表（去重）

技能配置：
    basic_attack  基础攻击  2 AP  相邻 1 格  1.0×  物理   （初始自带）
    charge_slash  冲锋斩    3 AP  相邻 1 格  1.8×  物理
    fireball      火球术    3 AP  5 格      1.8×  火
    ice_arrow     寒冰箭    3 AP  4 格      1.6×  冰
    water_shot    水弹      2 AP  3 格      1.2×  水
    lightning     雷击      3 AP  4 格      1.7×  雷
"""
from __future__ import annotations

from dataclasses import dataclass

from src.combat.element import Element
from src.core import config
from src.entities.entity import Entity
from src.entities.stats import Stats
from src.items.inventory import Inventory
from src.utils.vector import Vector2
from src.world.tilemap import TileMap


@dataclass
class Skill:
    """技能数据类。"""
    id: str            # 技能标识
    name: str          # 显示名
    ap_cost: int       # AP 消耗
    range_cells: int   # 攻击距离（格）
    multiplier: float  # 伤害倍率
    desc: str           # 技能描述
    element: Element = Element.NONE  # 技能元素（命中附着，触发反应）


# ========== 可学习技能池 ==========
# 玩家初始只拥有 basic_attack，其余技能通过休息房间"强化"从池中学习。
_SKILL_POOL: list[Skill] = [
    Skill(
        id="basic_attack",
        name="基础攻击",
        ap_cost=2,
        range_cells=1,
        multiplier=1.0,
        desc="对相邻敌人造成 ATK×1.0 物理伤害",
    ),
    Skill(
        id="charge_slash",
        name="冲锋斩",
        ap_cost=3,
        range_cells=1,
        multiplier=1.8,
        desc="对相邻敌人造成 ATK×1.8 物理伤害",
    ),
    Skill(
        id="fireball",
        name="火球术",
        ap_cost=3,
        range_cells=5,
        multiplier=1.8,
        desc="对 5 格内单体造成 ATK×1.8 火伤，附着火元素",
        element=Element.FIRE,
    ),
    Skill(
        id="ice_arrow",
        name="寒冰箭",
        ap_cost=3,
        range_cells=4,
        multiplier=1.6,
        desc="对 4 格内单体造成 ATK×1.6 冰伤，附着冰元素",
        element=Element.ICE,
    ),
    Skill(
        id="water_shot",
        name="水弹",
        ap_cost=2,
        range_cells=3,
        multiplier=1.2,
        desc="对 3 格内单体造成 ATK×1.2 水伤，附着水元素",
        element=Element.WATER,
    ),
    Skill(
        id="lightning",
        name="雷击",
        ap_cost=3,
        range_cells=4,
        multiplier=1.7,
        desc="对 4 格内单体造成 ATK×1.7 雷伤，附着雷元素",
        element=Element.LIGHTNING,
    ),
]


def get_skill_pool() -> list[Skill]:
    """返回技能池副本（供休息房间"强化"选择）。"""
    return [Skill(**s.__dict__) for s in _SKILL_POOL]


class Player(Entity):
    """玩家角色。"""

    def __init__(self, position: Vector2 | None = None):
        stats = Stats(
            max_hp=40,  # Day 9: 30→40，让玩家能扛住 Boss 多回合
            atk=6,
            def_=2,
            max_ap=config.AP_MAX,
            move_range=config.MOVE_RANGE,
        )
        super().__init__(
            position=position,
            stats=stats,
            color=config.COLOR_PLAYER,
            name="Player",
        )
        # 技能列表（深拷贝避免共享）：初始仅基础攻击
        self.skills: list[Skill] = [Skill(**s.__dict__) for s in _SKILL_POOL[:1]]
        # 当前选中的技能（None=未选中，使用基础攻击）
        self.selected_skill: Skill | None = None
        # Day 7：背包系统
        self.inventory: Inventory = Inventory(self)
        # 本局货币（商店购买用，初始 START_GOLD）
        self.gold: int = config.START_GOLD

    # ========== 技能学习接口 ==========

    def learn_skill(self, skill_id: str) -> bool:
        """从技能池学习一个技能（已学会返回 False）。"""
        if self.get_skill(skill_id) is not None:
            return False
        for s in _SKILL_POOL:
            if s.id == skill_id:
                self.skills.append(Skill(**s.__dict__))
                return True
        return False

    # ========== 技能接口 ==========

    def get_skill(self, skill_id: str) -> Skill | None:
        """按 id 查询技能。"""
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def select_skill(self, skill_id: str | None) -> None:
        """
        选中技能（None 或 "basic_attack" 表示用基础攻击）。
        selected_skill 用于 UI 高亮与点击时确定使用哪个技能。
        """
        if skill_id is None:
            self.selected_skill = None
            return
        skill = self.get_skill(skill_id)
        if skill is None:
            self.selected_skill = None
        else:
            self.selected_skill = skill

    @property
    def active_skill(self) -> Skill:
        """当前生效的技能（未选中则返回基础攻击）。"""
        if self.selected_skill is None:
            return self.skills[0]  # basic_attack
        return self.selected_skill

    # ========== 探索模式：WASD 移动 ==========

    def try_move_explore(
        self,
        dx: int,
        dy: int,
        tilemap: TileMap,
    ) -> bool:
        if dx == 0 and dy == 0:
            return False
        target_gx = self.grid_x + dx
        target_gy = self.grid_y + dy
        if not tilemap.is_walkable(target_gx, target_gy):
            return False
        self.move_to(target_gx, target_gy)
        return True

    # ========== 渲染 ==========

    def render(self, screen, cam_x: float, cam_y: float) -> None:
        import pygame
        ts = config.TILE_SIZE
        sx = int((self.position.x - cam_x) * ts)
        sy = int((self.position.y - cam_y) * ts)
        inset = 3
        rect = pygame.Rect(
            sx + inset, sy + inset, ts - inset * 2, ts - inset * 2
        )
        pygame.draw.rect(screen, self.color, rect, border_radius=8)
        pygame.draw.rect(screen, config.WHITE, rect, 2, border_radius=8)
        cx = sx + ts // 2
        cy = sy + ts // 2
        pygame.draw.circle(screen, config.WHITE, (cx, cy), 3)
