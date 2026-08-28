"""
背包系统模块。

功能说明：
    Inventory 管理玩家的物品栏与装备槽。
    - 物品栏：最多 10 个槽位（可堆叠物品合并）
    - 装备槽：武器槽 1 个
    - 装备武器时将 stat_modifiers 应用到玩家 stats
    - 使用药水时调用 item.use() 并消耗一个

接口设计：
    add(item)        → 添加物品（堆叠或占新槽）
    remove(slot)     → 移除指定槽位物品
    equip_weapon(w)  → 装备武器，应用属性加成
    use_potion(slot, target) → 使用药水
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.items.item import Item, ItemType
from src.items.weapon import StatModifier, Weapon

if TYPE_CHECKING:
    from src.entities.entity import Entity


class Inventory:
    """背包系统。"""

    MAX_SLOTS = 10  # 物品栏上限

    def __init__(self, owner: "Entity"):
        self.owner = owner
        # 物品栏：list[Item | None]，固定长度
        self.slots: list[Item | None] = [None] * self.MAX_SLOTS
        # 装备槽
        self.equipped_weapon: Weapon | None = None
        # 记录当前武器提供的属性加成（卸下时减去）
        self._weapon_mod: StatModifier | None = None

    # ========== 物品栏操作 ==========

    def add(self, item: Item) -> bool:
        """
        添加物品到背包。
        可堆叠物品（stackable）尝试合并到已有堆栈；否则占新槽。
        背包满返回 False。
        """
        # 可堆叠：尝试合并
        if item.stackable:
            for i, existing in enumerate(self.slots):
                if existing is not None and existing.id == item.id:
                    existing.count += item.count
                    return True
        # 占新槽
        for i in range(self.MAX_SLOTS):
            if self.slots[i] is None:
                self.slots[i] = item
                return True
        return False  # 背包满

    def remove(self, slot: int) -> Item | None:
        """移除指定槽位的物品（整个移除，不管数量）。"""
        if 0 <= slot < self.MAX_SLOTS:
            item = self.slots[slot]
            self.slots[slot] = None
            return item
        return None

    def get_item(self, slot: int) -> Item | None:
        """获取指定槽位的物品（不移除）。"""
        if 0 <= slot < self.MAX_SLOTS:
            return self.slots[slot]
        return None

    @property
    def used_slots(self) -> int:
        """已使用的槽位数。"""
        return sum(1 for s in self.slots if s is not None)

    @property
    def is_full(self) -> bool:
        return self.used_slots >= self.MAX_SLOTS

    # ========== 装备系统 ==========

    def equip_weapon(self, weapon: Weapon) -> Weapon | None:
        """
        装备武器。应用属性加成到 owner.stats。
        返回被替换下来的旧武器（如果有），None 表示没有旧武器。
        """
        old_weapon = None
        # 先卸下旧武器
        if self.equipped_weapon is not None:
            old_weapon = self._unequip_weapon_internal()
        # 装备新武器
        self.equipped_weapon = weapon
        mod = weapon.stat_modifiers
        self._weapon_mod = mod
        # 应用加成
        self.owner.stats.atk += mod.atk_bonus
        self.owner.stats.def_ += mod.def_bonus
        self.owner.stats.max_hp += mod.max_hp_bonus
        # max_hp 变化时同步 hp
        if mod.max_hp_bonus > 0:
            self.owner.stats.hp += mod.max_hp_bonus
        return old_weapon

    def unequip_weapon(self) -> Weapon | None:
        """卸下武器，减去属性加成。返回卸下的武器。"""
        return self._unequip_weapon_internal()

    def _unequip_weapon_internal(self) -> Weapon | None:
        """内部卸载逻辑。"""
        if self.equipped_weapon is None or self._weapon_mod is None:
            return None
        mod = self._weapon_mod
        # 减去加成
        self.owner.stats.atk = max(0, self.owner.stats.atk - mod.atk_bonus)
        self.owner.stats.def_ = max(0, self.owner.stats.def_ - mod.def_bonus)
        if mod.max_hp_bonus > 0:
            self.owner.stats.max_hp -= mod.max_hp_bonus
            self.owner.stats.hp = min(self.owner.stats.hp, self.owner.stats.max_hp)
        old = self.equipped_weapon
        self.equipped_weapon = None
        self._weapon_mod = None
        return old

    # ========== 使用消耗品 ==========

    def use_item(self, slot: int, target: "Entity | None" = None) -> bool:
        """
        使用指定槽位的物品。
        - 药水：调用 use()，数量 -1，归零则移除
        - 武器：装备
        返回是否使用成功。
        """
        item = self.get_item(slot)
        if item is None:
            return False
        target = target or self.owner
        if item.item_type == ItemType.POTION:
            if item.use(target):
                item.count -= 1
                if item.count <= 0:
                    self.slots[slot] = None
                return True
            return False
        elif item.item_type == ItemType.WEAPON:
            # 装备：先从背包移除，再装备
            self.slots[slot] = None
            old_weapon = self.equip_weapon(item)
            # 旧武器放回背包
            if old_weapon is not None:
                self.add(old_weapon)
            return True
        return False
