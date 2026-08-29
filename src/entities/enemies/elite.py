"""
精英敌人模块。

功能说明：
    精英守卫（Elite）是高威胁的中型敌人，拥有三阶段 AI：
    - 阶段 1（100%~70%）：远程消耗（保持距离 + 能量箭）
    - 阶段 2（70%~40%）：召唤小怪（场上小怪 < 2 时召唤史莱姆）
    - 阶段 3（40%~0%）：狂暴（贴脸双连击 + 主动追击）

    精英的 take_ai_turn 会根据当前 HP 百分比动态切换行为树。

数值（PRD 第 4.5 节）：
    HP 20 / ATK 5 / DEF 2 / AP 4 / Move 3
"""
from __future__ import annotations

from src.ai.behavior_tree import BehaviorTree
from src.ai.behaviors.elite_ai import (
    create_elite_phase1_tree, create_elite_phase2_tree, create_elite_phase3_tree,
)
from src.ai.nodes import NodeStatus
from src.core import config
from src.entities.enemy import Enemy
from src.entities.stats import Stats
from src.utils.vector import Vector2


class Elite(Enemy):
    """精英守卫：三阶段 AI 的中型敌人。"""

    def __init__(self, position: Vector2 | None = None, name: str = "Elite"):
        super().__init__(
            position=position,
            stats=Stats(
                max_hp=20,
                atk=5,
                def_=2,
                max_ap=4,
                move_range=3,
            ),
            name=name,
            color=config.COLOR_ELITE,
        )
        # 初始化为阶段 1
        self._phase = 1
        # 召唤物标记（false = 非召唤物）
        self.is_summoned = False
        self.gold_reward = config.GOLD_ELITE
        # 元素抗性：弱雷 / 抗火
        from src.combat.element import Element
        self.element_resist = {
            Element.LIGHTNING: 1.25,
            Element.FIRE: 0.75,
        }
        self._phase1_tree: BehaviorTree = create_elite_phase1_tree()
        self._phase2_tree: BehaviorTree = create_elite_phase2_tree()
        self._phase3_tree: BehaviorTree = create_elite_phase3_tree()
        self.behavior_tree = self._phase1_tree

    @property
    def phase(self) -> int:
        """当前阶段（1/2/3）。"""
        return self._phase

    def _update_phase(self) -> None:
        """根据 HP 百分比更新阶段，切换行为树。"""
        hp_pct = self.stats.hp / self.stats.max_hp
        if hp_pct > 0.7:
            new_phase = 1
        elif hp_pct > 0.4:
            new_phase = 2
        else:
            new_phase = 3
        if new_phase != self._phase:
            self._phase = new_phase
            if new_phase == 1:
                self.behavior_tree = self._phase1_tree
            elif new_phase == 2:
                self.behavior_tree = self._phase2_tree
            else:
                self.behavior_tree = self._phase3_tree

    def take_ai_turn(self, manager) -> NodeStatus | None:
        """每回合 tick 前检查阶段切换。"""
        self._update_phase()
        return super().take_ai_turn(manager)
