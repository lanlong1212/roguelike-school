"""
战斗行动模块。

Day 5 扩展：
    - AttackAction 接入 damage.apply_damage()，真正扣血
    - AttackAction 支持 multiplier（技能倍率），与玩家选中技能联动
    - 伤害结果通过 manager.last_damage_result 暴露给 UI 生成飘字
    - 添加 SkillAction 接入伤害计算
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.combat.damage import apply_damage
from src.combat.element import ELEMENT_NAME, REACTION_NAME, Element
from src.utils.vector import Vector2

if TYPE_CHECKING:
    from src.combat.battle_manager import BattleManager
    from src.entities.entity import Entity


class Action(ABC):
    """行动基类。所有具体行动继承此类并实现 execute()。"""

    def __init__(self, actor: "Entity", ap_cost: int = 0):
        self.actor = actor
        self.ap_cost = ap_cost

    @abstractmethod
    def execute(self, manager: "BattleManager") -> None:
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(actor={self.actor.name}, cost={self.ap_cost})"


# ========== 移动行动 ==========

class MoveAction(Action):
    """移动到目标瓦片。"""

    def __init__(self, actor: "Entity", target: Vector2, ap_cost: int = 1):
        super().__init__(actor, ap_cost)
        self.target = target

    def execute(self, manager: "BattleManager") -> None:
        self.actor.move_to(int(self.target.x), int(self.target.y))


# ========== 攻击行动 ==========

class AttackAction(Action):
    """
    对目标实体进行攻击。
    Day 5：调用 damage.apply_damage() 真正扣血，
    结果存入 manager.last_damage_result 供 UI 生成飘字。
    """

    def __init__(
        self,
        actor: "Entity",
        target: "Entity",
        ap_cost: int = 2,
        multiplier: float = 1.0,
        skill_name: str = "攻击",
        element: Element = Element.NONE,
    ):
        super().__init__(actor, ap_cost)
        self.target = target
        self.multiplier = multiplier
        self.skill_name = skill_name
        self.element = element

    def execute(self, manager: "BattleManager") -> None:
        # 计算伤害并扣血（含元素附着/反应/护盾）
        result = apply_damage(self.actor, self.target, self.multiplier, self.element)
        # 暴击/元素/反应描述
        crit_str = " 暴击!" if result.is_crit else ""
        reaction_str = f" 触发{REACTION_NAME[result.reaction]}!" if result.reaction else ""
        manager.last_action_desc = (
            f"{self.actor.name} 使用 {self.skill_name} → "
            f"{self.target.name} -{result.damage} HP{crit_str}{reaction_str}"
        )
        # 暴露给 UI 用于飘字
        manager.last_damage_result = result
        manager.last_damage_target = self.target


# ========== 技能行动 ==========

class SkillAction(Action):
    """
    使用主动技能。Day 5 接入伤害计算。
    技能效果通过 multiplier 区分（基础攻击 1.0×，冲锋斩 1.8×，火球术 2.0×）。
    """

    def __init__(
        self,
        actor: "Entity",
        target: "Entity | None",
        skill_id: str,
        multiplier: float,
        ap_cost: int = 3,
        skill_name: str = "技能",
        element: Element = Element.NONE,
    ):
        super().__init__(actor, ap_cost)
        self.target = target
        self.skill_id = skill_id
        self.multiplier = multiplier
        self.skill_name = skill_name
        self.element = element

    def execute(self, manager: "BattleManager") -> None:
        if self.target is None:
            manager.last_action_desc = f"{self.actor.name} 释放 {self.skill_name}（无目标）"
            return
        # 与 AttackAction 共用伤害逻辑（含元素附着/反应/护盾）
        result = apply_damage(self.actor, self.target, self.multiplier, self.element)
        crit_str = " 暴击!" if result.is_crit else ""
        reaction_str = f" 触发{REACTION_NAME[result.reaction]}!" if result.reaction else ""
        manager.last_action_desc = (
            f"{self.actor.name} 释放 {self.skill_name} → "
            f"{self.target.name} -{result.damage} HP{crit_str}{reaction_str}"
        )
        manager.last_damage_result = result
        manager.last_damage_target = self.target


# ========== 道具行动（Day 7 接入） ==========

class UseItemAction(Action):
    """使用消耗品。Day 7 实现具体道具效果。"""

    def __init__(self, actor: "Entity", item_id: str, ap_cost: int = 1):
        super().__init__(actor, ap_cost)
        self.item_id = item_id

    def execute(self, manager: "BattleManager") -> None:
        manager.last_action_desc = f"{self.actor.name} 使用 {self.item_id}"


# ========== 结束回合 ==========

class EndTurnAction(Action):
    """结束当前回合。"""

    def __init__(self, actor: "Entity"):
        super().__init__(actor, ap_cost=0)

    def execute(self, manager: "BattleManager") -> None:
        manager.last_action_desc = f"{self.actor.name} 结束回合"
