"""
药水模块。

功能说明：
    药水是消耗品，使用后从背包移除。MVP 提供两种：
    - health_potion 治疗药水: 回复 15 HP
    - strength_potion 力量药水: ATK +2（持续本场战斗，通过状态效果实现）
"""
from __future__ import annotations

from src.combat.status_effect import EffectType, StatusEffect
from src.items.item import Item, ItemType, Rarity


class Potion(Item):
    """药水。使用后消耗。"""

    def __init__(self, id: str, name: str, description: str, rarity: Rarity = Rarity.COMMON):
        super().__init__(
            id=id,
            name=name,
            item_type=ItemType.POTION,
            rarity=rarity,
            description=description,
            stackable=True,
            count=1,
        )


# ========== 预设药水 ==========

class HealthPotion(Potion):
    """治疗药水：回复 15 HP。"""

    HEAL_AMOUNT = 15

    def __init__(self):
        super().__init__(
            id="health_potion",
            name="治疗药水",
            description=f"回复 {self.HEAL_AMOUNT} 点生命值",
        )

    def use(self, target) -> bool:
        target.stats.heal(self.HEAL_AMOUNT)
        return True


class StrengthPotion(Potion):
    """力量药水：ATK +2，持续 5 回合（通过临时状态标记实现）。"""

    def __init__(self):
        super().__init__(
            id="strength_potion",
            name="力量药水",
            description="攻击力 +2，持续整场战斗",
            rarity=Rarity.UNCOMMON,
        )

    def use(self, target) -> bool:
        # MVP：直接加 stats.atk，战斗结束后由 Inventory.restore 复原
        target.stats.atk += 2
        return True
