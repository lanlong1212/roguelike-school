"""
角色属性模块。

功能说明：
    定义实体的核心战斗属性（HP/ATK/DEF/AP/移动范围/暴击等）。
    Stats 作为 Entity 的组合成员，Day 3 用于玩家移动（move_range），
    Day 4 起战斗系统会读取 ATK/DEF/AP 计算伤害与行动点。

数值基线参考 PRD 第 4.5 节"数值平衡表"。
"""
from __future__ import annotations

from src.core import config


class Stats:
    """角色战斗属性容器。所有数值均为整数，便于网格/伤害计算。"""

    __slots__ = (
        "max_hp", "hp",
        "max_ap", "ap",
        "atk", "def_",
        "crit_rate",      # 暴击率，0.0~1.0
        "crit_damage",    # 暴击伤害倍率（1.5 = 150%）
        "move_range",     # 每回合可移动格数（默认 3 格）
        "attack_range",   # 攻击范围格数（默认 1 格），
    )

    def __init__(
        self,
        max_hp: int = 30,
        atk: int = 6,
        def_: int = 2,
        max_ap: int = config.AP_MAX,      # 默认 5
        move_range: int = config.MOVE_RANGE,  # 默认 3
        crit_rate: float = 0.10,
        crit_damage: float = 1.5,
    ):
        self.max_hp = max_hp
        self.hp = max_hp
        self.max_ap = max_ap
        self.ap = max_ap
        self.atk = atk
        self.def_ = def_  # def 是关键字，加下划线
        self.crit_rate = crit_rate
        self.crit_damage = crit_damage
        self.move_range = move_range
        self.attack_range = 1

    # ========== HP 操作 ==========

    def take_damage(self, amount: int) -> int:
        """扣血，返回实际扣血量（不低于 0）。"""
        amount = max(0, amount)
        old_hp = self.hp
        self.hp = max(0, self.hp - amount)
        return old_hp - self.hp

    def heal(self, amount: int) -> int:
        """回血，返回实际回血量（不超过 max_hp）。"""
        amount = max(0, amount)
        old_hp = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - old_hp

    def is_dead(self) -> bool:
        return self.hp <= 0

    # ========== AP 操作 ==========

    def spend_ap(self, cost: int) -> bool:
        """消耗 AP，若不足返回 False 不扣。"""
        if self.ap < cost:
            return False
        self.ap -= cost
        return True

    def refund_ap(self, cost: int) -> None:
        """退还 AP（撤销行动用，MVP 暂不撤销但留接口）。"""
        self.ap = min(self.max_ap, self.ap + cost)

    def reset_ap(self) -> None:
        """回合开始时重置 AP 到上限。"""
        self.ap = self.max_ap

    # ========== 复制 ==========

    def copy(self) -> "Stats":
        """返回深拷贝。用于存档、临时计算等不污染原对象的场景。"""
        s = Stats.__new__(Stats)
        s.max_hp = self.max_hp
        s.hp = self.hp
        s.max_ap = self.max_ap
        s.ap = self.ap
        s.atk = self.atk
        s.def_ = self.def_
        s.crit_rate = self.crit_rate
        s.crit_damage = self.crit_damage
        s.move_range = self.move_range
        return s

    def __repr__(self) -> str:
        return (
            f"Stats(hp={self.hp}/{self.max_hp}, ap={self.ap}/{self.max_ap}, "
            f"atk={self.atk}, def={self.def_}, move={self.move_range})"
        )
