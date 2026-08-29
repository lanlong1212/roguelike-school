"""
基础敌人 AI 行为树模块。

功能说明：
    提供两种可复用的 AI 行为树：
    - create_melee_ai():  近战 AI（史莱姆用）
        逻辑：玩家在攻击范围(1格)? 攻击 : 朝玩家移动 1 格
    - create_ranged_ai(): 远程 AI（骷髅用）
        逻辑：玩家在攻击范围(4格)? 攻击 :
              玩家太近(<=2格)? 后退 1 格 : 朝玩家移动 1 格

AI 行动消耗 AP，由 BattleManager 控制 tick 次数直到 AP 耗尽。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.behavior_tree import BehaviorTree
from src.ai.nodes import Action, BTNode, Condition, NodeStatus, Selector, Sequence
from src.combat.action import AttackAction, MoveAction
from src.utils.vector import Vector2

if TYPE_CHECKING:
    from src.combat.battle_manager import BattleManager
    from src.entities.entity import Entity


def _distance(a: "Entity", b: "Entity") -> int:
    """切比雪夫距离（8 方向最大距离）。"""
    return max(abs(a.grid_x - b.grid_x), abs(a.grid_y - b.grid_y))


# ========== 近战 AI ==========

def _is_player_in_attack_range(actor: "Entity", ctx: "BattleManager") -> bool:
    """玩家在相邻 1 格（切比雪夫距离 <= 1）。"""
    return _distance(actor, ctx.player) <= 1


def _attack_player(actor: "Entity", ctx: "BattleManager") -> bool:
    """对玩家执行攻击。"""
    if actor.stats.ap < 2:
        return False
    action = AttackAction(
        actor=actor,
        target=ctx.player,
        ap_cost=2,
        multiplier=1.0,
        skill_name="撕咬",
    )
    return ctx.execute_enemy_action(actor, action)


def _move_toward_player(actor: "Entity", ctx: "BattleManager") -> bool:
    """朝玩家方向移动 1 格（贪心：先 dx 后 dy）。"""
    if actor.stats.ap < 1:
        return False
    dx = _sign(ctx.player.grid_x - actor.grid_x)
    dy = _sign(ctx.player.grid_y - actor.grid_y)
    # 优先走距离差更大的轴
    if abs(ctx.player.grid_x - actor.grid_x) >= abs(ctx.player.grid_y - actor.grid_y):
        if dx != 0 and _try_move(actor, ctx, dx, 0):
            return True
        if dy != 0 and _try_move(actor, ctx, 0, dy):
            return True
    else:
        if dy != 0 and _try_move(actor, ctx, 0, dy):
            return True
        if dx != 0 and _try_move(actor, ctx, dx, 0):
            return True
    return False


def _try_move(actor: "Entity", ctx: "BattleManager", dx: int, dy: int) -> bool:
    """尝试移动到相邻格子。"""
    nx, ny = actor.grid_x + dx, actor.grid_y + dy
    if not ctx.tilemap.is_walkable(nx, ny):
        return False
    # 不能踩在玩家或其他敌人身上
    if (nx, ny) == ctx.player.grid_pos:
        return False
    for e in ctx.enemies:
        if e is not actor and not e.stats.is_dead() and e.grid_pos == (nx, ny):
            return False
    action = MoveAction(actor=actor, target=Vector2(nx, ny), ap_cost=1)
    return ctx.execute_enemy_action(actor, action)


def _sign(v: int) -> int:
    if v > 0: return 1
    if v < 0: return -1
    return 0


def create_melee_ai() -> BehaviorTree:
    """
    近战 AI：
        Selector
          Sequence: [玩家在攻击范围? 攻击玩家]
          Sequence: [玩家可见? 朝玩家移动]
    """
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_in_attack_range, "玩家在攻击范围"),
            Action(_attack_player, "攻击玩家"),
        ]),
        Sequence([
            Condition(lambda a, c: True, "玩家可见"),  # MVP: 总是可见
            Action(_move_toward_player, "朝玩家移动"),
        ]),
    ])
    return BehaviorTree(root)


# ========== 远程 AI ==========

def _is_player_in_ranged_range(actor: "Entity", ctx: "BattleManager") -> bool:
    """玩家在 4 格内且视线无遮挡（障碍柱/墙会挡箭）。"""
    if _distance(actor, ctx.player) > 4:
        return False
    return ctx.tilemap.has_line_of_sight(
        actor.grid_x, actor.grid_y, ctx.player.grid_x, ctx.player.grid_y
    )


def _is_player_too_close(actor: "Entity", ctx: "BattleManager") -> bool:
    """玩家太近（2 格内）需要后退。"""
    return _distance(actor, ctx.player) <= 2


def _ranged_attack(actor: "Entity", ctx: "BattleManager") -> bool:
    """远程攻击玩家。"""
    if actor.stats.ap < 2:
        return False
    action = AttackAction(
        actor=actor,
        target=ctx.player,
        ap_cost=2,
        multiplier=1.0,
        skill_name="射箭",
    )
    return ctx.execute_enemy_action(actor, action)


def _move_away_from_player(actor: "Entity", ctx: "BattleManager") -> bool:
    """远离玩家 1 格。"""
    if actor.stats.ap < 1:
        return False
    dx = _sign(actor.grid_x - ctx.player.grid_x)
    dy = _sign(actor.grid_y - ctx.player.grid_y)
    if dx != 0 and _try_move(actor, ctx, dx, 0):
        return True
    if dy != 0 and _try_move(actor, ctx, 0, dy):
        return True
    return False


def create_ranged_ai() -> BehaviorTree:
    """
    远程 AI：
        Selector
          Sequence: [玩家在攻击范围且不太近? 远程攻击]
          Sequence: [玩家太近? 后退]
          Sequence: [玩家太远? 朝玩家移动]
    """
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_in_ranged_range, "玩家在射程内"),
            Condition(lambda a, c: not _is_player_too_close(a, c), "距离安全"),
            Action(_ranged_attack, "远程攻击"),
        ]),
        Sequence([
            Condition(_is_player_too_close, "玩家太近"),
            Action(_move_away_from_player, "后退"),
        ]),
        Sequence([
            Action(_move_toward_player, "朝玩家靠近"),
        ]),
    ])
    return BehaviorTree(root)
