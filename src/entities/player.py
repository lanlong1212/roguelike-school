"""
玩家角色模块。

Day 5 扩展：
    - 增加 skills 技能列表（1 基础攻击 + 2 主动技能）
    - 技能数据类 Skill 含 id/name/ap_cost/range/multiplier/desc
    - 提供 get_skill(id) 与默认技能配置

技能配置（PRD 第 4.4 节）：
    basic_attack  基础攻击  2 AP  相邻 8 格  1.0×
    charge_slash  冲锋斩    3 AP  相邻 8 格  1.8×
    fireball      火球术    3 AP  5 格直线  2.0×（Day 5 简化为远程单体）
"""
from __future__ import annotations

from dataclasses import dataclass

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


# 玩家默认技能列表
_DEFAULT_SKILLS: list[Skill] = [
    Skill(
        id="basic_attack",
        name="基础攻击",
        ap_cost=2,
        range_cells=1,
        multiplier=1.0,
        desc="对相邻敌人造成 ATK×1.0 伤害",
    ),
    Skill(
        id="charge_slash",
        name="冲锋斩",
        ap_cost=3,
        range_cells=1,
        multiplier=1.8,
        desc="对相邻敌人造成 ATK×1.8 伤害",
    ),
    Skill(
        id="fireball",
        name="火球术",
        ap_cost=3,
        range_cells=5,
        multiplier=2.0,
        desc="对 5 格内单体造成 ATK×2.0 伤害",
    ),
]


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
        # 技能列表（深拷贝避免共享）
        self.skills: list[Skill] = [Skill(**s.__dict__) for s in _DEFAULT_SKILLS]
        # 当前选中的技能（None=未选中，使用基础攻击）
        self.selected_skill: Skill | None = None
        # Day 7：背包系统
        self.inventory: Inventory = Inventory(self)
        # 本局货币（商店购买用，初始 START_GOLD）
        self.gold: int = config.START_GOLD

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
