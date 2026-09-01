"""
战斗行动模块。

Day 5 扩展：
    - AttackAction 接入 damage.apply_damage()，真正扣血
    - AttackAction 支持 multiplier（技能倍率），与玩家选中技能联动
    - 伤害结果通过 manager.last_damage_result 暴露给 UI 生成飘字
    - 添加 SkillAction 接入伤害计算
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.combat.damage import DamageResult, apply_damage
from src.combat.element import ELEMENT_NAME, REACTION_NAME, Element
from src.combat.status_effect import EFFECT_DISPLAY_NAME, EffectType, StatusEffect
from src.core import config
from src.utils.vector import Vector2

if TYPE_CHECKING:
    from src.combat.battle_manager import BattleManager
    from src.entities.entity import Entity


def _trigger_counter_stance(
    manager: "BattleManager",
    attacker: "Entity",
    target: "Entity",
    damage: int,
) -> None:
    """反击姿态：目标开启反击且被近战（相邻格）攻击 → 对攻击者反弹所受伤害的 50%。

    近战判定：攻击者与被击者曼哈顿距离 1（贴脸攻击）；远程射击/AoE 不触发。
    反击结果单独存 last_counter_result（不覆盖主伤害），供 UI 同时显示两个飘字。
    """
    if damage <= 0 or not getattr(target, "counter_stance_active", False):
        return
    if target.stats.is_dead():
        return
    if abs(attacker.grid_x - target.grid_x) + abs(attacker.grid_y - target.grid_y) != 1:
        return
    counter = max(1, int(damage * config.COUNTER_STANCE_RATIO))
    attacker.stats.take_damage(counter)
    manager.last_action_desc = f"{target.name} 反击 {attacker.name} -{counter} HP"
    manager.last_counter_result = DamageResult(
        damage=counter, is_crit=False, attacker_atk=0, target_def=0,
    )
    manager.last_counter_target = attacker


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
        # 朝向与行走动画（按移动方向）
        dx = int(self.target.x) - self.actor.grid_x
        dy = int(self.target.y) - self.actor.grid_y
        self.actor.face(dx, dy)
        self.actor.play_anim("walk", restart=True)
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
        # 朝向目标 + 攻击动画（播完自动回 idle；实体可用 attack_anim_name
        # 覆盖动作，如精英按阶段切换 attack0/idle/attack1）
        dx = self.target.grid_x - self.actor.grid_x
        dy = self.target.grid_y - self.actor.grid_y
        self.actor.face(dx, dy)
        self.actor.play_anim(getattr(self.actor, "attack_anim_name", "attack"), restart=True)
        # 标记本回合已攻击：AI 移动节点据此不再走位，保证攻击动画完整播出
        if hasattr(self.actor, "attacked_this_turn"):
            self.actor.attacked_this_turn = True
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
        # 反击姿态：伙伴被近战攻击且开启反击 → 对攻击者反弹伤害
        _trigger_counter_stance(manager, self.actor, self.target, result.damage)


# ========== 技能行动 ==========

class SkillAction(Action):
    """
    使用主动技能。Day 5 接入伤害计算。
    技能效果通过 multiplier 区分（基础攻击 1.0×，冲锋斩 1.8×，火球术 2.0×）。
    战棋化：AoE 副目标通过 ap_cost=0 的额外 SkillAction 直接 execute 结算；
    apply_effect 命中后给目标附加状态（如寒冰箭的减速）。
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
        apply_effect: "EffectType | None" = None,
        effect_duration: int = 1,
        effect_chance: float = 1.0,
    ):
        super().__init__(actor, ap_cost)
        self.target = target
        self.skill_id = skill_id
        self.multiplier = multiplier
        self.skill_name = skill_name
        self.element = element
        self.apply_effect = apply_effect
        self.effect_duration = effect_duration
        self.effect_chance = effect_chance

    def execute(self, manager: "BattleManager") -> None:
        if self.target is None:
            manager.last_action_desc = f"{self.actor.name} 释放 {self.skill_name}（无目标）"
            return
        # 反击姿态：自身 buff 技能（无伤害、无目标附加），本回合受近战攻击自动反击
        if self.skill_id == "counter_stance":
            setattr(self.actor, "counter_stance_active", True)
            manager.last_action_desc = (
                f"{self.actor.name} 进入反击姿态（本回合受近战攻击自动反击 50% 伤害）"
            )
            manager.last_damage_result = None
            manager.last_damage_target = None
            return
        # 嘲讽每回合限 1 次：施放即标记（0 AP 免费技能）
        if self.skill_id == "taunt":
            setattr(self.actor, "taunt_used_this_turn", True)
        # 朝向目标 + 攻击动画（播完自动回 idle；同 AttackAction 支持阶段动画覆盖）
        dx = self.target.grid_x - self.actor.grid_x
        dy = self.target.grid_y - self.actor.grid_y
        self.actor.face(dx, dy)
        self.actor.play_anim(getattr(self.actor, "attack_anim_name", "attack"), restart=True)
        # 标记本回合已攻击（同 AttackAction，防止后续走位打断攻击动画）
        if hasattr(self.actor, "attacked_this_turn"):
            self.actor.attacked_this_turn = True
        # 无伤害技能（如嘲讽 multiplier=0.0）：跳过伤害结算，仅附加状态
        result = None
        if self.multiplier > 0:
            result = apply_damage(self.actor, self.target, self.multiplier, self.element)
        crit_str = " 暴击!" if result is not None and result.is_crit else ""
        reaction_str = (
            f" 触发{REACTION_NAME[result.reaction]}!"
            if result is not None and result.reaction else ""
        )
        # 附加状态：按概率触发，持续 effect_duration 回合（寒冰箭减速 / 嘲讽 / 盾击眩晕）
        effect_str = ""
        if (
            self.apply_effect is not None
            and not self.target.stats.is_dead()
            and random.random() < self.effect_chance
        ):
            self.target.status_effects.add(
                StatusEffect(
                    self.apply_effect,
                    duration=self.effect_duration,
                    source_name=self.skill_name,
                )
            )
            effect_str = f" 附加{EFFECT_DISPLAY_NAME[self.apply_effect]}"
        if result is not None:
            manager.last_action_desc = (
                f"{self.actor.name} 释放 {self.skill_name} → "
                f"{self.target.name} -{result.damage} HP{crit_str}{reaction_str}{effect_str}"
            )
        else:
            manager.last_action_desc = (
                f"{self.actor.name} 释放 {self.skill_name} → {self.target.name}{effect_str}"
            )
        manager.last_damage_result = result
        manager.last_damage_target = self.target if result is not None else None
        # 反击姿态：伙伴被近战攻击且开启反击 → 对攻击者反弹伤害
        if result is not None:
            _trigger_counter_stance(manager, self.actor, self.target, result.damage)


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
