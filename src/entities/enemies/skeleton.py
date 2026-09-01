"""
骷髅敌人模块。

功能说明：
    远程型基础敌人。中 HP、中 ATK，使用弓箭远程攻击。
    AI 会保持距离，玩家靠近时后退，在 4 格内开弓射击。

数值（PRD 第 4.5 节）：
    HP 12 / ATK 4 / DEF 1 / AP 3 / Move 2
"""
from __future__ import annotations

from src.core import config
from src.entities.enemy import Enemy
from src.entities.stats import Stats
from src.utils.vector import Vector2


class Skeleton(Enemy):
    """骷髅：远程型敌人。"""

    def __init__(self, position: Vector2 | None = None, name: str = "Skeleton"):
        super().__init__(
            position=position,
            stats=Stats(
                max_hp=12,
                atk=4,
                def_=1,
                max_ap=3,
                move_range=2,
            ),
            name=name,
            color=(220, 220, 200),  # 骨白色
        )
        # 注入远程 AI
        from src.ai.behaviors.basic_enemy_ai import create_ranged_ai
        self.set_behavior_tree(create_ranged_ai())
        self.gold_reward = config.GOLD_SKELETON
        # 元素抗性：弱冰 / 抗火
        from src.combat.element import Element
        self.element_resist = {
            Element.ICE: 1.25,
            Element.FIRE: 0.75,
        }
        # 攻击元素：远程箭矢附着火元素（自动走附着/反应链）
        self.attack_element: Element = Element.FIRE
        # 动画（横向帧表）：idle 4 / walk 8 / attack 9 / hurt 4 / death 6 帧
        from src.core.asset_manager import assets
        from src.entities.animation import Animator
        anim = Animator()
        anim.add("idle", assets.get_frames("entities/skeleton/idle"), 8)
        anim.add("walk", assets.get_frames("entities/skeleton/walk"), 10)
        anim.add("attack", assets.get_frames("entities/skeleton/attack"), 12, loop=False, on_finish="idle")
        anim.add("hurt", assets.get_frames("entities/skeleton/hurt"), 12, loop=False, on_finish="idle")
        anim.add("death", assets.get_frames("entities/skeleton/death"), 10, loop=False)
        anim.play("idle")
        self.animator = anim
