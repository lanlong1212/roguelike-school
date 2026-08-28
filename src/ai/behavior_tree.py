"""
行为树模块。

功能说明：
    BehaviorTree 是 AI 的大脑容器。持有 root 节点，每回合由
    BattleManager.step_enemy_turn() 调用 tick()，驱动敌人行动。

执行模型：
    tick(actor, ctx) 从 root 开始遍历，按节点类型（Selector/Sequence/
    Condition/Action）执行逻辑，返回 NodeStatus。
    一个 tick 代表敌人做一次决策（移动 1 格或攻击 1 次）。
    BattleManager 反复调用 tick 直到敌人 AP 耗尽。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.nodes import BTNode, NodeStatus

if TYPE_CHECKING:
    from src.combat.battle_manager import BattleManager
    from src.entities.entity import Entity


class BehaviorTree:
    """行为树。持有 root 节点，执行 tick。"""

    def __init__(self, root: BTNode):
        self.root = root

    def tick(self, actor: "Entity", ctx: "BattleManager") -> NodeStatus:
        """从 root 执行一次 tick。"""
        return self.root.tick(actor, ctx)
