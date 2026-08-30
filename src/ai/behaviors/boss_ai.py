"""
Boss AI 行为树模块。

功能说明：
    Boss 三阶段 AI，根据自身 HP 百分比切换行为树：
    - 阶段 1（100%~70%）：近战攻击 + 朝玩家移动
    - 阶段 2（70%~40%）：每次行动 2 连击（AP 足够时攻击两次）
    - 阶段 3（40%~0%）：AOE 攻击（相邻 8 格全打）+ 移动

    Boss 的 take_ai_turn 会根据当前阶段动态选择子树。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.behavior_tree import BehaviorTree
from src.ai.nodes import Action, BTNode, Condition, NodeStatus, Selector, Sequence
from src.combat.action import AttackAction
from src.combat.battle_manager import BattleManager
from src.entities.entity import Entity

if TYPE_CHECKING:
    pass


def _distance(a: "Entity", b: "Entity") -> int:
    return max(abs(a.grid_x - b.grid_x), abs(a.grid_y - b.grid_y))


def _sign(v: int) -> int:
    if v > 0: return 1
    if v < 0: return -1
    return 0


def _boss_attack(actor: "Entity", ctx: "BattleManager") -> bool:
    """Boss 普通攻击（2 AP）。"""
    if actor.stats.ap < 2:
        return False
    action = AttackAction(
        actor=actor, target=ctx.player, ap_cost=2,
        multiplier=1.2, skill_name="重击",
    )
    return ctx.execute_enemy_action(actor, action)


def _boss_double_attack(actor: "Entity", ctx: "BattleManager") -> bool:
    """
    阶段 2 连击：尝试攻击两次。
    第一次 2 AP，第二次 2 AP。AP 不足时只打一次。
    """
    if actor.stats.ap < 2:
        return False
    # 第一次攻击
    action = AttackAction(
        actor=actor, target=ctx.player, ap_cost=2,
        multiplier=1.2, skill_name="连击一",
    )
    ok = ctx.execute_enemy_action(actor, action)
    if not ok:
        return False
    # AP 还够就再打一次
    if actor.stats.ap >= 2:
        action2 = AttackAction(
            actor=actor, target=ctx.player, ap_cost=2,
            multiplier=1.0, skill_name="连击二",
        )
        ctx.execute_enemy_action(actor, action2)
    return True


def _boss_aoe_attack(actor: "Entity", ctx: "BattleManager") -> bool:
    """
    阶段 3 AOE：消耗 3 AP，对玩家造成 1.5× 伤害。
    MVP 简化为单体高伤（真正的 8 格 AOE 需要改 damage 系统支持多目标）。
    """
    if actor.stats.ap < 3:
        return False
    action = AttackAction(
        actor=actor, target=ctx.player, ap_cost=3,
        multiplier=1.5, skill_name="全屏震击",
    )
    return ctx.execute_enemy_action(actor, action)


def _boss_move_toward_player(actor: "Entity", ctx: "BattleManager") -> bool:
    """Boss 朝玩家移动 1 格。本回合已攻击则不再走位。"""
    if actor.stats.ap < 1 or getattr(actor, "attacked_this_turn", False):
        return False
    dx = _sign(ctx.player.grid_x - actor.grid_x)
    dy = _sign(ctx.player.grid_y - actor.grid_y)
    if abs(ctx.player.grid_x - actor.grid_x) >= abs(ctx.player.grid_y - actor.grid_y):
        if dx != 0 and _try_boss_move(actor, ctx, dx, 0):
            return True
        if dy != 0 and _try_boss_move(actor, ctx, 0, dy):
            return True
    else:
        if dy != 0 and _try_boss_move(actor, ctx, 0, dy):
            return True
        if dx != 0 and _try_boss_move(actor, ctx, dx, 0):
            return True
    return False


def _try_boss_move(actor: "Entity", ctx: "BattleManager", dx: int, dy: int) -> bool:
    from src.combat.action import MoveAction
    from src.utils.vector import Vector2
    nx, ny = actor.grid_x + dx, actor.grid_y + dy
    if not ctx.tilemap.is_walkable(nx, ny):
        return False
    if (nx, ny) == ctx.player.grid_pos:
        return False
    for e in ctx.enemies:
        if e is not actor and not e.stats.is_dead() and e.grid_pos == (nx, ny):
            return False
    action = MoveAction(actor=actor, target=Vector2(nx, ny), ap_cost=1)
    return ctx.execute_enemy_action(actor, action)


def _is_player_adjacent(actor: "Entity", ctx: "BattleManager") -> bool:
    return _distance(actor, ctx.player) <= 1


def _is_player_in_ranged_range(actor: "Entity", ctx: "BattleManager") -> bool:
    return _distance(actor, ctx.player) <= 3


# ========== 三阶段行为树工厂 ==========

def create_phase1_tree() -> BehaviorTree:
    """阶段 1（100%~70%）：近战 + 追击。"""
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_adjacent, "玩家贴脸"),
            Action(_boss_attack, "重击"),
        ]),
        Sequence([
            Action(_boss_move_toward_player, "追击"),
        ]),
    ])
    return BehaviorTree(root)


def create_phase2_tree() -> BehaviorTree:
    """阶段 2（70%~40%）：2 连击 + 追击。"""
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_adjacent, "玩家贴脸"),
            Action(_boss_double_attack, "连击"),
        ]),
        Sequence([
            Action(_boss_move_toward_player, "追击"),
        ]),
    ])
    return BehaviorTree(root)


def create_phase3_tree() -> BehaviorTree:
    """阶段 3（40%~0%）：AOE + 追击。"""
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_in_ranged_range, "玩家在 3 格内"),
            Action(_boss_aoe_attack, "全屏震击"),
        ]),
        Sequence([
            Action(_boss_move_toward_player, "追击"),
        ]),
    ])
    return BehaviorTree(root)
