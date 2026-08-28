"""
史莱姆敌人模块。

功能说明：
    近战型基础敌人。低 HP、低 ATK、慢速，使用近战 AI。
    出现在 BATTLE 房间。MVP 阶段数量较多，作为玩家熟悉战斗的练习对象。

数值（PRD 第 4.5 节）：
    HP 8 / ATK 3 / DEF 1 / AP 3 / Move 2
"""
from __future__ import annotations

from src.core import config
from src.entities.enemy import Enemy
from src.entities.stats import Stats
from src.utils.vector import Vector2


class Slime(Enemy):
    """史莱姆：近战型敌人。"""

    def __init__(self, position: Vector2 | None = None, name: str = "Slime"):
        super().__init__(
            position=position,
            stats=Stats(
                max_hp=8,
                atk=3,
                def_=1,
                max_ap=3,
                move_range=2,
            ),
            name=name,
            color=(120, 200, 80),  # 绿色
        )
        # 注入近战 AI
        from src.ai.behaviors.basic_enemy_ai import create_melee_ai
        self.set_behavior_tree(create_melee_ai())
