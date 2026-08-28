"""
行为树节点模块。

功能说明：
    实现行为树（Behavior Tree）的 4 种节点：
    - BTNode:     基类，定义 tick(actor, ctx) 接口
    - Selector:   选择节点，依次尝试子节点，第一个 SUCCESS 即返回（类似 OR）
    - Sequence:   顺序节点，依次执行子节点，全部 SUCCESS 才算 SUCCESS（类似 AND）
    - Condition:  条件节点，调用谓词函数返回 SUCCESS/FAILURE
    - Action:      行动节点，执行具体行动（移动/攻击等）

节点返回状态：
    SUCCESS: 行动成功或条件成立
    FAILURE: 行动失败或条件不成立
    RUNNING:  未完成但仍在进行（MVP 暂不用，留作扩展）

设计考量：
    行为树让 AI 逻辑可组合、可复用。复杂 AI（Boss 多阶段）通过
    组合多个 Selector/Sequence 即可实现，无需改框架。
"""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.combat.battle_manager import BattleManager
    from src.entities.entity import Entity


class NodeStatus(Enum):
    """节点执行状态。"""
    SUCCESS = auto()
    FAILURE = auto()
    RUNNING = auto()


class BTNode:
    """行为树节点基类。"""

    def tick(self, actor: "Entity", ctx: "BattleManager") -> NodeStatus:
        """执行此节点。子类必须覆盖。"""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


# ========== 选择节点 ==========

class Selector(BTNode):
    """
    选择节点：依次尝试子节点，第一个 SUCCESS 即返回。
    全部 FAILURE 才返回 FAILURE。类似逻辑或。
    """

    def __init__(self, children: list[BTNode]):
        self.children = children

    def tick(self, actor: "Entity", ctx: "BattleManager") -> NodeStatus:
        for child in self.children:
            status = child.tick(actor, ctx)
            if status != NodeStatus.FAILURE:
                return status
        return NodeStatus.FAILURE


# ========== 顺序节点 ==========

class Sequence(BTNode):
    """
    顺序节点：依次执行子节点，全部 SUCCESS 才返回 SUCCESS。
    任一 FAILURE 即返回 FAILURE。类似逻辑与。
    """

    def __init__(self, children: list[BTNode]):
        self.children = children

    def tick(self, actor: "Entity", ctx: "BattleManager") -> NodeStatus:
        for child in self.children:
            status = child.tick(actor, ctx)
            if status != NodeStatus.SUCCESS:
                return status
        return NodeStatus.SUCCESS


# ========== 条件节点 ==========

class Condition(BTNode):
    """
    条件节点：调用谓词函数判断 SUCCESS/FAILURE。
    predicate 签名: (actor, ctx) -> bool
    """

    def __init__(self, predicate: Callable[["Entity", "BattleManager"], bool], name: str = ""):
        self.predicate = predicate
        self.name = name

    def tick(self, actor: "Entity", ctx: "BattleManager") -> NodeStatus:
        if self.predicate(actor, ctx):
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


# ========== 行动节点 ==========

class Action(BTNode):
    """
    行动节点：执行一个行动函数，返回 SUCCESS/FAILURE。
    action_fn 签名: (actor, ctx) -> bool  (True=SUCCESS)
    """

    def __init__(self, action_fn: Callable[["Entity", "BattleManager"], bool], name: str = ""):
        self.action_fn = action_fn
        self.name = name

    def tick(self, actor: "Entity", ctx: "BattleManager") -> NodeStatus:
        if self.action_fn(actor, ctx):
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE
