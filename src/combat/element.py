"""
元素系统模块。

功能说明：
    实现元素附着与元素反应系统：
    - 元素类型：火 / 水 / 冰 / 雷（+ 物理 NONE）
    - 元素技能命中敌人会附着元素（持续 AURA_DURATION 回合，同元素命中刷新）
    - 敌人同时只保留一种附着；命中元素与已有附着构成反应对时触发元素反应，
      反应后附着消耗（双方都消失）：

        火 + 水 → 蒸发   本次伤害 ×1.5
        冰 + 水 → 冻结   目标跳过下一回合
        雷 + 水 → 感电   追加雷伤 + 感电状态（受击伤害 ×1.5，2 回合）
        雷 + 冰 → 超导   追加伤害 + 破甲状态（防御 -50%，2 回合）

    说明：反应结算接口对攻防双方开放（敌人后续也可附加元素），
    由 damage.apply_damage 统一调用，便于后续给怪物加入元素技能。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from src.combat.status_effect import EffectType, StatusEffect

if TYPE_CHECKING:
    from src.entities.entity import Entity


class Element(Enum):
    """元素类型。NONE 表示物理/无元素。"""
    NONE = auto()
    FIRE = auto()
    WATER = auto()
    ICE = auto()
    LIGHTNING = auto()


# 元素 → 显示名
ELEMENT_NAME: dict[Element, str] = {
    Element.NONE: "物理",
    Element.FIRE: "火",
    Element.WATER: "水",
    Element.ICE: "冰",
    Element.LIGHTNING: "雷",
}

# 元素 → 飘字颜色
ELEMENT_COLOR: dict[Element, tuple[int, int, int]] = {
    Element.NONE: (220, 220, 220),
    Element.FIRE: (255, 120, 40),
    Element.WATER: (80, 160, 255),
    Element.ICE: (120, 220, 255),
    Element.LIGHTNING: (255, 220, 80),
}

AURA_DURATION = 2  # 元素附着持续回合数


class Reaction(Enum):
    """元素反应类型。"""
    VAPORIZE = auto()        # 蒸发：火+水 / 水+火
    FROZEN = auto()          # 冻结：冰+水
    ELECTRO_CHARGED = auto() # 感电：雷+水
    SUPERCONDUCT = auto()    # 超导：雷+冰


REACTION_NAME: dict[Reaction, str] = {
    Reaction.VAPORIZE: "蒸发",
    Reaction.FROZEN: "冻结",
    Reaction.ELECTRO_CHARGED: "感电",
    Reaction.SUPERCONDUCT: "超导",
}


@dataclass
class ElementImpact:
    """一次元素命中（附着/反应）的结算结果。"""
    element: Element                # 命中元素
    reaction: Reaction | None = None  # 触发的反应（None=无）
    damage_multiplier: float = 1.0    # 反应倍率（蒸发 1.5）
    bonus_damage: int = 0             # 反应追加伤害（感电/超导）
    aura_after: Element | None = None # 命中后目标剩余附着（None=无）


def _reaction_for(existing: Element, incoming: Element) -> Reaction | None:
    """根据已有附着与命中元素判定反应（无反应返回 None）。"""
    pair = frozenset((existing, incoming))
    if pair == frozenset((Element.FIRE, Element.WATER)):
        return Reaction.VAPORIZE
    if pair == frozenset((Element.ICE, Element.WATER)):
        return Reaction.FROZEN
    if pair == frozenset((Element.LIGHTNING, Element.WATER)):
        return Reaction.ELECTRO_CHARGED
    if pair == frozenset((Element.LIGHTNING, Element.ICE)):
        return Reaction.SUPERCONDUCT
    return None


def _apply_reaction_status(
    target: "Entity",
    reaction: Reaction,
    impact: ElementImpact,
    attacker_atk: int,
) -> None:
    """反应附带效果：追加伤害 / 附加状态。"""
    if reaction is Reaction.VAPORIZE:
        impact.damage_multiplier = 1.5
    elif reaction is Reaction.FROZEN:
        target.status_effects.add(
            StatusEffect(EffectType.FREEZE, duration=1, source_name="冻结")
        )
    elif reaction is Reaction.ELECTRO_CHARGED:
        impact.bonus_damage = 2 + attacker_atk
        target.status_effects.add(
            StatusEffect(EffectType.SHOCK, duration=2, magnitude=1, source_name="感电")
        )
    elif reaction is Reaction.SUPERCONDUCT:
        impact.bonus_damage = 1 + attacker_atk
        target.status_effects.add(
            StatusEffect(EffectType.DEF_DOWN, duration=2, magnitude=2, source_name="超导")
        )


def apply_element_impact(
    attacker: "Entity",
    target: "Entity",
    element: Element,
) -> ElementImpact:
    """
    处理一次元素命中：附着 / 刷新 / 触发反应。

    规则：
    - 物理（NONE）直接返回，不参与附着与反应
    - 目标无附着或同元素 → 附着/刷新该元素
    - 目标有异元素附着 → 判定反应；有反应则触发（附着消耗），
      无反应则用新元素替换附着
    """
    impact = ElementImpact(element=element)
    if element is Element.NONE:
        return impact

    aura = target.status_effects.aura
    if aura is None or aura is element:
        target.status_effects.set_aura(element, AURA_DURATION)
        impact.aura_after = element
        return impact

    reaction = _reaction_for(aura, element)
    if reaction is None:
        # 无反应对：直接替换附着
        target.status_effects.set_aura(element, AURA_DURATION)
        impact.aura_after = element
        return impact

    impact.reaction = reaction
    _apply_reaction_status(target, reaction, impact, attacker.stats.atk)
    # 反应后附着消耗
    target.status_effects.clear_aura()
    impact.aura_after = None
    return impact
