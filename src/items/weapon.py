"""
武器模块。

功能说明：
    武器是装备槽物品，装备后影响玩家 stats（ATK 加成、攻击范围加成）。
    MVP 阶段提供两种武器：
    - iron_sword 铁剑:  ATK +3
    - long_bow   长弓:  ATK +1，攻击范围 +2（让基础攻击变远程）

设计考量：
    武器的 stat_modifiers 是数据驱动的，便于后续扩展词缀系统。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.items.item import Item, ItemType, Rarity


@dataclass
class StatModifier:
    """属性修饰器。装备时加到 stats 上，卸下时减去。"""
    atk_bonus: int = 0
    def_bonus: int = 0
    max_hp_bonus: int = 0
    attack_range_bonus: int = 0  # 攻击范围加成（格）


@dataclass
class Weapon(Item):
    """武器。装备后影响 stats。"""
    stat_modifiers: StatModifier = field(default_factory=StatModifier)

    def __post_init__(self):
        # 确保 item_type 为 WEAPON
        self.item_type = ItemType.WEAPON

    def use(self, target) -> bool:
        """
        武器的 use 是"装备"。具体装备逻辑由 Inventory 管理（替换装备槽）。
        这里返回 True 表示可装备。
        """
        return True


# ========== 预设武器 ==========

def create_iron_sword() -> Weapon:
    """铁剑：ATK +3。"""
    return Weapon(
        id="iron_sword",
        name="铁剑",
        item_type=ItemType.WEAPON,
        rarity=Rarity.COMMON,
        description="攻击力 +3",
        stat_modifiers=StatModifier(atk_bonus=3),
    )


def create_long_bow() -> Weapon:
    """长弓：ATK +1，攻击范围 +2。"""
    return Weapon(
        id="long_bow",
        name="长弓",
        item_type=ItemType.WEAPON,
        rarity=Rarity.UNCOMMON,
        description="攻击力 +1，攻击范围 +2 格",
        stat_modifiers=StatModifier(atk_bonus=1, attack_range_bonus=2),
    )
