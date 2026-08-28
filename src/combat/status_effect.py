"""
状态效果模块。

功能说明：
    实现战斗中的状态效果系统：中毒、燃烧、眩晕、护盾。
    每个状态有持续回合数与每回合 tick 效果。状态附加到实体上，
    在回合开始/结束时统一处理。Day 5 实现基础框架与 4 种效果，
    Day 6+ AI 与 Day 7 道具会使用。

效果定义（PRD 第 4.5 节）：
    POISON  中毒：每回合开始扣 X 点 HP，持续 N 回合
    BURN    燃烧：每回合开始扣 X 点 HP（数值更高但持续短）
    STUN    眩晕：跳过下一回合行动
    SHIELD  护盾：吸收下 X 点伤害，持续到吸收完或回合结束
"""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.entities.entity import Entity


class EffectType(Enum):
    """状态效果类型。"""
    POISON = auto()
    BURN = auto()
    STUN = auto()
    SHIELD = auto()


# 类型 → 显示名（用于 UI）
EFFECT_DISPLAY_NAME: dict[EffectType, str] = {
    EffectType.POISON: "中毒",
    EffectType.BURN: "燃烧",
    EffectType.STUN: "眩晕",
    EffectType.SHIELD: "护盾",
}


class StatusEffect:
    """单个状态效果实例。"""

    __slots__ = ("effect_type", "duration", "magnitude", "source_name")

    def __init__(
        self,
        effect_type: EffectType,
        duration: int = 3,
        magnitude: int = 0,
        source_name: str = "",
    ):
        self.effect_type = effect_type
        self.duration = duration       # 剩余持续回合数
        self.magnitude = magnitude      # 效果数值（伤害量/护盾量）
        self.source_name = source_name # 来源（技能名/道具名，用于调试）

    def __repr__(self) -> str:
        return f"{EFFECT_DISPLAY_NAME[self.effect_type]}({self.magnitude}, {self.duration}回合)"


class StatusEffectContainer:
    """
    实体的状态效果容器。挂在 Entity 上（Day 5 后由 Entity 持有一个实例）。
    提供 add / has / tick 接口。
    """

    def __init__(self):
        self._effects: list[StatusEffect] = []

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

    @property
    def is_stunned(self) -> bool:
        """是否处于眩晕状态（回合开始时查询）。"""
        return self.has(EffectType.STUN)

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
        回合开始时调用。处理中毒/燃烧的持续伤害，眩晕标记消耗。
        返回本次 tick 产生的日志消息列表（供 HUD 显示）。
        """
        logs: list[str] = []
        remaining: list[StatusEffect] = []
        for e in self._effects:
            if e.effect_type == EffectType.POISON:
                actual = entity.stats.take_damage(e.magnitude)
                logs.append(f"{entity.name} 中毒，受到 {actual} 点伤害")
                e.duration -= 1
            elif e.effect_type == EffectType.BURN:
                actual = entity.stats.take_damage(e.magnitude)
                logs.append(f"{entity.name} 燃烧，受到 {actual} 点伤害")
                e.duration -= 1
            elif e.effect_type == EffectType.STUN:
                # 眩晕在本回合消耗，本回合不能行动
                logs.append(f"{entity.name} 眩晕，无法行动")
                e.duration -= 1
            elif e.effect_type == EffectType.SHIELD:
                # 护盾在回合开始不触发，在受到伤害时吸收
                pass
            if e.duration > 0:
                remaining.append(e)
        self._effects = remaining
        return logs

    def on_turn_end(self, entity: "Entity") -> list[str]:
        """回合结束时调用。MVP 暂无 end tick 逻辑。"""
        return []

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
