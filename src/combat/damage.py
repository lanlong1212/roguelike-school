"""
伤害计算模块。

功能说明：
    实现战斗伤害公式，包含攻击力、防御减伤、技能倍率、暴击、元素抗性，
    以及元素附着/反应、感电增伤、破甲减防、护盾吸收。
    所有伤害计算集中于此，便于数值平衡调整与单元测试。

伤害公式（PRD 第 4.5 节，元素系统扩展）：
    基础伤害 = max(1, ATK × 倍率 - DEF_有效 × 0.5)
        DEF_有效 = DEF × 0.5（破甲状态下）
    暴击伤害 = round(基础伤害 × crit_damage)
    元素伤害 = 暴击伤害 × 元素抗性系数（弱点 1.25 / 抗性 0.75）
    反应倍率：蒸发 ×1.5；感电/超导追加额外伤害
    感电状态：受击伤害 ×1.5
    最终扣血 = 经过护盾吸收后的伤害

    说明：DEF 采用 0.5 系数减伤（非完全抵消），保证低 ATK 也能打出伤害。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.combat.element import Element, apply_element_impact
from src.combat.status_effect import EffectType

if TYPE_CHECKING:
    from src.combat.element import Reaction
    from src.entities.entity import Entity
    from src.entities.stats import Stats


@dataclass
class DamageResult:
    """一次伤害计算的完整结果。"""
    damage: int          # 最终扣血量
    is_crit: bool        # 是否暴击
    attacker_atk: int    # 攻击者 ATK（供飘字显示）
    target_def: int      # 目标 DEF
    element: Element = Element.NONE      # 命中元素（供飘字着色）
    reaction: "Reaction | None" = None   # 触发的元素反应（供飘字显示）


def calculate_damage(
    attacker: "Entity",
    target: "Entity",
    multiplier: float = 1.0,
    ignore_def: bool = False,
    element: Element = Element.NONE,
) -> DamageResult:
    """
    计算攻击者对目标造成的伤害。

    参数：
        attacker:    攻击者实体（读取 atk, crit_rate, crit_damage）
        target:      目标实体（读取 def_、元素抗性、破甲状态）
        multiplier:  技能倍率（1.0=普攻，1.8=冲锋斩，2.0=火球术）
        ignore_def:  是否无视防御（特殊技能用，MVP 暂不启用）
        element:     命中元素（元素抗性倍率由此判定）
    """
    atk = attacker.stats.atk
    # 破甲：防御减半
    def_mult = 0.5 if target.status_effects.has(EffectType.DEF_DOWN) else 1.0
    def_ = 0 if ignore_def else target.stats.def_ * def_mult

    # 基础伤害
    base = max(1, int(atk * multiplier - def_ * 0.5))

    # 暴击判定
    is_crit = _roll_crit(attacker.stats.crit_rate)
    if is_crit:
        final = round(base * attacker.stats.crit_damage)
    else:
        final = base

    # 元素抗性倍率（弱点 ×1.25 / 抗性 ×0.75 / 正常 ×1.0）
    resist = target.element_resist.get(element, 1.0)
    final = max(1, int(final * resist))

    return DamageResult(
        damage=final,
        is_crit=is_crit,
        attacker_atk=atk,
        target_def=int(def_),
        element=element,
    )


def _roll_crit(crit_rate: float) -> bool:
    """判定是否触发暴击。crit_rate ∈ [0.0, 1.0]。"""
    import random
    return random.random() < crit_rate


def apply_damage(
    attacker: "Entity",
    target: "Entity",
    multiplier: float = 1.0,
    element: Element = Element.NONE,
) -> DamageResult:
    """
    计算伤害并直接对目标扣血（完整管道）：
    元素抗性 → 元素附着/反应 → 感电增伤 → 护盾吸收 → 扣血。
    返回 DamageResult，调用方可据其生成飘字。
    """
    result = calculate_damage(attacker, target, multiplier, element=element)

    # 元素附着 / 反应（物理无此逻辑）
    impact = apply_element_impact(attacker, target, element)
    result.damage = int(result.damage * impact.damage_multiplier) + impact.bonus_damage
    result.reaction = impact.reaction

    # 感电：受击伤害 ×1.5
    if target.status_effects.has(EffectType.SHOCK):
        result.damage = int(result.damage * 1.5)

    # 护盾吸收
    remaining = target.status_effects.absorb_damage(result.damage)
    target.stats.take_damage(remaining)
    result.damage = remaining
    return result
