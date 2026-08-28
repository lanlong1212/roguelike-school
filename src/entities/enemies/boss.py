"""
Boss 实体模块。

功能说明：
    Boss 是精英级敌人，拥有三阶段 AI：
    - 阶段 1（100%~70%）：近战 + 追击
    - 阶段 2（70%~40%）：2 连击
    - 阶段 3（40%~0%）：AOE 震击

    Boss 的 take_ai_turn 会根据当前 HP 百分比动态切换行为树。

数值（PRD 第 4.5 节）：
    HP 60 / ATK 8 / DEF 3 / AP 4 / Move 2
"""
from __future__ import annotations

from src.ai.behavior_tree import BehaviorTree
from src.ai.behaviors.boss_ai import (
    create_phase1_tree, create_phase2_tree, create_phase3_tree,
)
from src.ai.nodes import NodeStatus
from src.core import config
from src.entities.enemy import Enemy
from src.entities.stats import Stats
from src.utils.vector import Vector2


class Boss(Enemy):
    """Boss 实体。三阶段 AI。"""

    def __init__(self, position: Vector2 | None = None, name: str = "Boss"):
        super().__init__(
            position=position,
            stats=Stats(
                max_hp=80,  # Day 9: 60→80，延长 Boss 战让阶段切换更有节奏
                atk=8,
                def_=3,
                max_ap=4,
                move_range=2,
            ),
            name=name,
            color=config.COLOR_BOSS,
        )
        # 初始化为阶段 1
        self._phase = 1
        self._phase1_tree: BehaviorTree = create_phase1_tree()
        self._phase2_tree: BehaviorTree = create_phase2_tree()
        self._phase3_tree: BehaviorTree = create_phase3_tree()
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
