"""
精英敌人 AI 行为树模块。

功能说明：
    精英守卫三阶段 AI，根据自身 HP 百分比切换行为树：
    - 阶段 1（100%~70%）：远程消耗 —— 保持距离 + 远程攻击
    - 阶段 2（70%~40%）：召唤小怪 —— 场上小怪不足时召唤史莱姆，配合远程攻击
    - 阶段 3（40%~0%）：狂暴 —— 高倍率连击 + 主动追击

    精英的 take_ai_turn 会根据当前 HP 百分比动态切换行为树。
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
    return max(abs(a.grid_x - b.grid_x), abs(a.grid_y - b.grid_y))


def _sign(v: int) -> int:
    if v > 0: return 1
    if v < 0: return -1
    return 0


# ========== 通用行动 ==========

def _elite_move(actor: "Entity", ctx: "BattleManager", dx: int, dy: int) -> bool:
    """向 (dx, dy) 方向移动 1 格，失败返回 False。"""
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


def _elite_move_toward_player(actor: "Entity", ctx: "BattleManager") -> bool:
    """朝玩家移动 1 格。本回合已攻击则不再走位。"""
    if actor.stats.ap < 1 or getattr(actor, "attacked_this_turn", False):
        return False
    dx = _sign(ctx.player.grid_x - actor.grid_x)
    dy = _sign(ctx.player.grid_y - actor.grid_y)
    if abs(ctx.player.grid_x - actor.grid_x) >= abs(ctx.player.grid_y - actor.grid_y):
        if dx != 0 and _elite_move(actor, ctx, dx, 0):
            return True
        if dy != 0 and _elite_move(actor, ctx, 0, dy):
            return True
    else:
        if dy != 0 and _elite_move(actor, ctx, 0, dy):
            return True
        if dx != 0 and _elite_move(actor, ctx, dx, 0):
            return True
    return False


def _elite_move_away(actor: "Entity", ctx: "BattleManager") -> bool:
    """远离玩家 1 格。本回合已攻击则不再走位。"""
    if actor.stats.ap < 1 or getattr(actor, "attacked_this_turn", False):
        return False
    dx = _sign(actor.grid_x - ctx.player.grid_x)
    dy = _sign(actor.grid_y - ctx.player.grid_y)
    if dx != 0 and _elite_move(actor, ctx, dx, 0):
        return True
    if dy != 0 and _elite_move(actor, ctx, 0, dy):
        return True
    return False


def _elite_ranged_attack(actor: "Entity", ctx: "BattleManager", multiplier: float, name: str) -> bool:
    """远程攻击玩家（2 AP）。"""
    if actor.stats.ap < 2:
        return False
    action = AttackAction(
        actor=actor, target=ctx.player, ap_cost=2,
        multiplier=multiplier, skill_name=name,
    )
    return ctx.execute_enemy_action(actor, action)


# ========== 阶段 1：远程消耗 ==========

def _is_player_in_range1(actor: "Entity", ctx: "BattleManager") -> bool:
    """玩家在射程内且视线无遮挡（障碍柱/墙会挡能量箭）。"""
    if _distance(actor, ctx.player) > 4:
        return False
    return ctx.tilemap.has_line_of_sight(
        actor.grid_x, actor.grid_y, ctx.player.grid_x, ctx.player.grid_y
    )


def _is_player_too_close1(actor: "Entity", ctx: "BattleManager") -> bool:
    return _distance(actor, ctx.player) <= 2


def _attack_ranged1(actor: "Entity", ctx: "BattleManager") -> bool:
    return _elite_ranged_attack(actor, ctx, 1.2, "能量箭")


def create_elite_phase1_tree() -> BehaviorTree:
    """阶段 1（100%~70%）：远程消耗。保持 2 格距离远程射击。"""
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_in_range1, "玩家在射程内"),
            Condition(lambda a, c: not _is_player_too_close1(a, c), "距离安全"),
            Action(_attack_ranged1, "远程攻击"),
        ]),
        Sequence([
            Condition(_is_player_too_close1, "玩家太近"),
            Action(_elite_move_away, "后退"),
        ]),
        Sequence([
            Action(_elite_move_toward_player, "靠近"),
        ]),
    ])
    return BehaviorTree(root)


# ========== 阶段 2：召唤小怪 ==========

def _count_minions(actor: "Entity", ctx: "BattleManager") -> int:
    """统计场上存活的召唤物数量。"""
    count = 0
    for e in ctx.enemies:
        if getattr(e, "is_summoned", False) and not e.stats.is_dead():
            count += 1
    return count


def _is_low_minions(actor: "Entity", ctx: "BattleManager") -> bool:
    return _count_minions(actor, ctx) < 2


def _elite_summon(actor: "Entity", ctx: "BattleManager") -> bool:
    """
    召唤一只史莱姆（3 AP），放在自身相邻空格。
    场上召唤物 < 2 时才可召唤。
    """
    if actor.stats.ap < 3:
        return False
    if _count_minions(actor, ctx) >= 2:
        return False
    from src.entities.enemies.slime import Slime
    # 寻找相邻空格（上下左右优先）
    for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nx, ny = actor.grid_x + dx, actor.grid_y + dy
        if not ctx.tilemap.is_walkable(nx, ny):
            continue
        if (nx, ny) == ctx.player.grid_pos:
            continue
        if any(
            e is not actor and not e.stats.is_dead() and e.grid_pos == (nx, ny)
            for e in ctx.enemies
        ):
            continue
        minion = Slime(position=Vector2(nx, ny), name="小史莱姆")
        minion.is_summoned = True
        minion.stats.spend_ap(minion.stats.ap)  # 召唤物本回合不动
        ctx.enemies.append(minion)
        actor.stats.spend_ap(3)
        ctx.last_action_desc = "精英召唤了一只小史莱姆！"
        return True
    return False


def _attack_ranged2(actor: "Entity", ctx: "BattleManager") -> bool:
    return _elite_ranged_attack(actor, ctx, 1.2, "能量箭")


def create_elite_phase2_tree() -> BehaviorTree:
    """阶段 2（70%~40%）：召唤小怪 + 远程消耗。"""
    root: BTNode = Selector([
        Sequence([
            Condition(_is_low_minions, "场上小怪不足"),
            Action(_elite_summon, "召唤小怪"),
        ]),
        Sequence([
            Condition(_is_player_in_range1, "玩家在射程内"),
            Condition(lambda a, c: not _is_player_too_close1(a, c), "距离安全"),
            Action(_attack_ranged2, "远程攻击"),
        ]),
        Sequence([
            Condition(_is_player_too_close1, "玩家太近"),
            Action(_elite_move_away, "后退"),
        ]),
        Sequence([
            Action(_elite_move_toward_player, "靠近"),
        ]),
    ])
    return BehaviorTree(root)


# ========== 阶段 3：狂暴 ==========

def _is_player_adjacent3(actor: "Entity", ctx: "BattleManager") -> bool:
    return _distance(actor, ctx.player) <= 1


def _berserk_double_attack(actor: "Entity", ctx: "BattleManager") -> bool:
    """
    狂暴连击：贴脸时 1.6× + 1.3× 两连击。
    第一次 2 AP，第二次 2 AP，AP 不足则只打一次。
    """
    if actor.stats.ap < 2:
        return False
    action = AttackAction(
        actor=actor, target=ctx.player, ap_cost=2,
        multiplier=1.6, skill_name="狂暴连击一",
    )
    ok = ctx.execute_enemy_action(actor, action)
    if not ok:
        return False
    if actor.stats.ap >= 2:
        action2 = AttackAction(
            actor=actor, target=ctx.player, ap_cost=2,
            multiplier=1.3, skill_name="狂暴连击二",
        )
        ctx.execute_enemy_action(actor, action2)
    return True


def create_elite_phase3_tree() -> BehaviorTree:
    """阶段 3（40%~0%）：狂暴。贴脸双连击，否则追击。"""
    root: BTNode = Selector([
        Sequence([
            Condition(_is_player_adjacent3, "玩家贴脸"),
            Action(_berserk_double_attack, "狂暴连击"),
        ]),
        Sequence([
            Action(_elite_move_toward_player, "追击"),
        ]),
    ])
    return BehaviorTree(root)
