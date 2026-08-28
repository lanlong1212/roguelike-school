"""
物品基类模块。

功能说明：
    定义 Item 基类与 ItemType 枚举。所有具体物品（武器、药水、遗物）
    继承 Item 并实现 use() 方法。
    MVP 阶段实现 WEAPON（武器）与 POTION（药水）两种类型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.entities.entity import Entity


class ItemType(Enum):
    """物品类型。"""
    WEAPON = auto()   # 武器（装备槽）
    POTION = auto()   # 药水（消耗品）
    RELIC = auto()    # 遗物（被动效果，Day 8+ 实现）


class Rarity(Enum):
    """稀有度。"""
    COMMON = auto()    # 白色
    UNCOMMON = auto()  # 绿色
    RARE = auto()      # 蓝色
    EPIC = auto()      # 紫色


@dataclass
class Item:
    """
    物品基类。
    子类应覆盖 use() 实现具体效果。
    """
    id: str            # 物品标识
    name: str          # 显示名
    item_type: ItemType
    rarity: Rarity = Rarity.COMMON
    description: str = ""
    stackable: bool = False  # 是否可堆叠（药水可堆叠）
    count: int = 1          # 堆叠数量

    def use(self, target: "Entity") -> bool:
        """
        使用物品。返回是否使用成功。
        基类默认返回 False（不可使用）。
        """
        return False

    def __repr__(self) -> str:
        return f"{self.name}({self.item_type.name}, {self.rarity.name})"
