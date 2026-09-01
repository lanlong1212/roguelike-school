"""
状态效果模块。

功能说明：
    实现战斗中的状态效果系统（元素反应系统的副产物状态也在此）：
    - STUN   眩晕：跳过下一回合行动
    - SHIELD 护盾：吸收下 X 点伤害，持续到吸收完
    - FREEZE 冻结：跳过下一回合行动（冰+水 反应）
    - SHOCK  感电：受击伤害 ×1.5（雷+水 反应）
    - DEF_DOWN 破甲：防御 -50%（雷+冰 反应）
    - SLOW   减速：下回合 AP 上限 -1（寒冰箭附加）
    - MELT   融化：受击伤害 ×1.25（火+冰 反应）
    - OVERLOAD 超载：回合结束受到 magnitude 点雷伤（雷+火 反应）
    - TAUNT   嘲讽：强制敌人 AI 以伙伴为目标（伙伴技能"嘲讽"附加）

    状态附加到实体上，由战斗管理器在回合开始/结束时统一处理。
    容器同时负责元素附着的存储（_aura），由 element 模块读写。
"""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.combat.element import Element
    from src.entities.entity import Entity


class EffectType(Enum):
    """状态效果类型。"""
    STUN = auto()      # 眩晕
    SHIELD = auto()    # 护盾
    FREEZE = auto()    # 冻结
    SHOCK = auto()     # 感电
    DEF_DOWN = auto()  # 破甲
    SLOW = auto()      # 减速（AP 上限 -1）
    MELT = auto()      # 融化：受击伤害 ×1.25
    OVERLOAD = auto()  # 超载：回合结束受到 magnitude 点雷伤
    TAUNT = auto()     # 嘲讽：强制 AI 以伙伴为目标


# 类型 → 显示名（用于 UI）
EFFECT_DISPLAY_NAME: dict[EffectType, str] = {
    EffectType.STUN: "眩晕",
    EffectType.SHIELD: "护盾",
    EffectType.FREEZE: "冻结",
    EffectType.SHOCK: "感电",
    EffectType.DEF_DOWN: "破甲",
    EffectType.SLOW: "减速",
    EffectType.MELT: "融化",
    EffectType.OVERLOAD: "超载",
    EffectType.TAUNT: "嘲讽",
}


class StatusEffect:
    """单个状态效果实例。"""

    __slots__ = ("effect_type", "duration", "magnitude", "source_name")

    def __init__(
        self,
        effect_type: EffectType,
        duration: int = 1,
        magnitude: int = 0,
        source_name: str = "",
    ):
        self.effect_type = effect_type
        self.duration = duration       # 剩余持续回合数
        self.magnitude = magnitude      # 效果数值（护盾量等）
        self.source_name = source_name  # 来源（技能名/反应名，用于调试）

    def __repr__(self) -> str:
        return f"{EFFECT_DISPLAY_NAME[self.effect_type]}({self.magnitude}, {self.duration}回合)"


class StatusEffectContainer:
    """
    实体的状态效果容器 + 元素附着容器。挂在 Entity 上。
    提供 add / has / tick / absorb / aura 接口。
    """

    def __init__(self):
        self._effects: list[StatusEffect] = []
        # 元素附着（由 element 模块读写）
        self._aura: "Element | None" = None
        self._aura_remaining: int = 0

    # ========== 查询 ==========

    def has(self, effect_type: EffectType) -> bool:
        """是否拥有某类效果。"""
        return any(e.effect_type == effect_type for e in self._effects)

    def get(self, effect_type: EffectType) -> StatusEffect | None:
        """获取某类效果实例（取第一个）。"""
        for e in self._effects:
            if e.effect_type == effect_type:
                return e
        return None

    @property
    def all(self) -> list[StatusEffect]:
        """返回所有效果（只读视图）。"""
        return list(self._effects)

    def is_disabled(self) -> bool:
        """是否处于眩晕/冻结（本回合不能行动）。"""
        return self.has(EffectType.STUN) or self.has(EffectType.FREEZE)

    # ========== 元素附着 ==========

    @property
    def aura(self) -> "Element | None":
        """当前附着元素（None=无附着）。"""
        return self._aura

    def set_aura(self, element: "Element", duration: int) -> None:
        """设置/刷新附着元素。"""
        self._aura = element
        self._aura_remaining = duration

    def clear_aura(self) -> None:
        """清除附着（反应消耗后调用）。"""
        self._aura = None
        self._aura_remaining = 0

    def tick_aura(self) -> None:
        """附着持续回合 -1，归零后消失（每回合调用一次）。"""
        if self._aura is not None:
            self._aura_remaining -= 1
            if self._aura_remaining <= 0:
                self._aura = None
                self._aura_remaining = 0

    # ========== 添加/移除 ==========

    def add(self, effect: StatusEffect) -> None:
        """
        添加效果。同类效果刷新持续时间和数值（取较大者）。
        护盾特殊处理：叠加数值。
        """
        existing = self.get(effect.effect_type)
        if existing is None:
            self._effects.append(effect)
        elif effect.effect_type == EffectType.SHIELD:
            existing.magnitude += effect.magnitude
            existing.duration = max(existing.duration, effect.duration)
        else:
            existing.duration = max(existing.duration, effect.duration)
            existing.magnitude = max(existing.magnitude, effect.magnitude)

    def remove(self, effect_type: EffectType) -> None:
        """移除某类效果。"""
        self._effects = [e for e in self._effects if e.effect_type != effect_type]

    # ========== 回合处理 ==========

    def on_turn_start(self, entity: "Entity") -> list[str]:
        """
        回合开始时调用。返回本次 tick 产生的日志消息列表（供 HUD 显示）。
        眩晕/冻结不在此处扣时长（在 on_turn_end 扣），确保整回合无法行动。
        """
        logs: list[str] = []
        if self.is_disabled():
            logs.append(f"{entity.name} 无法行动")
        return logs

    def on_turn_end(self, entity: "Entity") -> list[str]:
        """回合结束时调用：超载结算雷伤，随后所有效果时长 -1，归零移除。
        护盾同样倒计时（护盾技能持续 2 回合），与"吸收完消失"双重约束。"""
        logs: list[str] = []
        # 超载：回合结束受到 magnitude 点雷伤（先结算再倒计时）
        overload = self.get(EffectType.OVERLOAD)
        if overload is not None and not entity.stats.is_dead():
            dmg = max(1, overload.magnitude)
            entity.stats.take_damage(dmg)
            logs.append(f"超载雷爆对 {entity.name} 造成 {dmg} 点伤害")
        remaining: list[StatusEffect] = []
        for e in self._effects:
            e.duration -= 1
            if e.duration > 0:
                remaining.append(e)
        self._effects = remaining
        return logs

    def absorb_damage(self, amount: int) -> int:
        """
        护盾吸收伤害。返回护盾吸收后的剩余伤害量（未被吸收的部分）。
        """
        shield = self.get(EffectType.SHIELD)
        if shield is None or shield.magnitude <= 0:
            return amount
        absorbed = min(shield.magnitude, amount)
        shield.magnitude -= absorbed
        if shield.magnitude <= 0:
            self.remove(EffectType.SHIELD)
        return amount - absorbed
