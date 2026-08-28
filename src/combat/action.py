"""
战斗行动模块。

功能说明：
    定义回合制战斗中所有可执行行动的基类与子类。每个 Action 携带
    actor（执行者）、cost（AP 消耗）、execute()（执行效果）。
    BattleManager 按顺序执行 Action 队列。

行动类型与 AP 消耗（PRD 第 4.3 节）：
    MoveAction       1 AP/格
    AttackAction     2 AP
    SkillAction      3 AP  （Day 5 接入）
    UseItemAction    1 AP  （Day 7 接入）
    EndTurnAction    0 AP  （自动切回合）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

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
        """在 BattleManager 上下文中执行此行动。"""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(actor={self.actor.name}, cost={self.ap_cost})"


# ========== 移动行动 ==========

class MoveAction(Action):
    """移动到目标瓦片。Day 4 仅改坐标，Day 5+ 可能触发陷阱。"""

    def __init__(self, actor: "Entity", target: Vector2, ap_cost: int = 1):
        super().__init__(actor, ap_cost)
        self.target = target

    def execute(self, manager: "BattleManager") -> None:
        self.actor.move_to(int(self.target.x), int(self.target.y))


# ========== 攻击行动 ==========

class AttackAction(Action):
    """
    对目标实体进行基础攻击。
    Day 4：只扣 AP，不真正造成伤害（Day 5 接入 damage 公式）。
    """

    def __init__(self, actor: "Entity", target: "Entity", ap_cost: int = 2):
        super().__init__(actor, ap_cost)
        self.target = target

    def execute(self, manager: "BattleManager") -> None:
        # Day 5 会调用 damage.calculate() 并对 target.stats.take_damage()
        # Day 4 占位：仅记录一次"攻击发生"
        manager.last_action_desc = f"{self.actor.name} 攻击 {self.target.name}"


# ========== 技能行动（Day 5 接入） ==========

class SkillAction(Action):
    """使用主动技能。Day 5 实现具体技能效果。"""

    def __init__(self, actor: "Entity", target: "Entity | None", skill_id: str, ap_cost: int = 3):
        super().__init__(actor, ap_cost)
        self.target = target
        self.skill_id = skill_id

    def execute(self, manager: "BattleManager") -> None:
        manager.last_action_desc = f"{self.actor.name} 释放技能 {self.skill_id}"


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
    """结束当前回合，不消耗 AP。"""

    def __init__(self, actor: "Entity"):
        super().__init__(actor, ap_cost=0)

    def execute(self, manager: "BattleManager") -> None:
        manager.last_action_desc = f"{self.actor.name} 结束回合"
