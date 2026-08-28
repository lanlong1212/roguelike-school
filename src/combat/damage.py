"""
伤害计算模块。

功能说明：
    实现战斗伤害公式，包含攻击力、防御减伤、技能倍率、暴击。
    所有伤害计算集中于此，便于数值平衡调整与单元测试。

伤害公式（PRD 第 4.5 节）：
    基础伤害 = max(1, ATK × 倍率 - DEF × 0.5)
    暴击伤害 = round(基础伤害 × crit_damage)
    最终伤害 = 暴击 ? 暴击伤害 : 基础伤害

    说明：DEF 采用 0.5 系数减伤（非完全抵消），保证低 ATK 也能打出伤害。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.entities.entity import Entity
    from src.entities.stats import Stats


@dataclass
class DamageResult:
    """一次伤害计算的完整结果。"""
    damage: int          # 最终扣血量
    is_crit: bool        # 是否暴击
    attacker_atk: int    # 攻击者 ATK（供飘字显示）
    target_def: int      # 目标 DEF


def calculate_damage(
    attacker: "Entity",
    target: "Entity",
    multiplier: float = 1.0,
    ignore_def: bool = False,
) -> DamageResult:
    """
    计算攻击者对目标造成的伤害。

    参数：
        attacker:    攻击者实体（读取 atk, crit_rate, crit_damage）
        target:      目标实体（读取 def_）
        multiplier:  技能倍率（1.0=普攻，1.8=冲锋斩，2.0=火球术）
        ignore_def:  是否无视防御（特殊技能用，MVP 暂不启用）
    """
    atk = attacker.stats.atk
    def_ = 0 if ignore_def else target.stats.def_

    # 基础伤害
    base = max(1, int(atk * multiplier - def_ * 0.5))

    # 暴击判定
    is_crit = _roll_crit(attacker.stats.crit_rate)
    if is_crit:
        final = round(base * attacker.stats.crit_damage)
    else:
        final = base

    return DamageResult(
        damage=final,
        is_crit=is_crit,
        attacker_atk=atk,
        target_def=def_,
    )


def _roll_crit(crit_rate: float) -> bool:
    """判定是否触发暴击。crit_rate ∈ [0.0, 1.0]。"""
    import random
    return random.random() < crit_rate


def apply_damage(
    attacker: "Entity",
    target: "Entity",
    multiplier: float = 1.0,
) -> DamageResult:
    """
    计算伤害并直接对目标扣血。
    返回 DamageResult，调用方可据其生成飘字。
    """
    result = calculate_damage(attacker, target, multiplier)
    target.stats.take_damage(result.damage)
    return result
