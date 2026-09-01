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
        # 动画注册（横向帧表位于 assets/images/entities/elite_mob/）：
        # idle 8fps / walk 10fps 循环；attack(阶段1 远程) 12fps / hurt 12fps
        # 播完回 idle；attack_rage(阶段3 狂暴) 12fps 播完回 idle；death 10fps
        # 播完停留。get_actor_frames 跨动画统一缩放，避免攻击动作（包围盒
        # 大）导致切换动画时角色突然缩小；素材缺失时该动画不在结果中、
        # add 自动忽略，全部缺失则走 Entity 色块回退，不影响战斗逻辑。
        from src.core.asset_manager import assets
        from src.entities.animation import Animator
        frames = assets.get_actor_frames({
            "idle": "entities/elite_mob/idle",
            "walk": "entities/elite_mob/walk",
            "attack": "entities/elite_mob/attack0",
            "attack_rage": "entities/elite_mob/attack1",
            "hurt": "entities/elite_mob/hurt",
            "death": "entities/elite_mob/death",
        })
        anim = Animator()
        anim.add("idle", frames.get("idle", []), 8)
        anim.add("walk", frames.get("walk", []), 10)
        anim.add("attack", frames.get("attack", []), 12, loop=False, on_finish="idle")
        anim.add("attack_rage", frames.get("attack_rage", []), 12, loop=False, on_finish="idle")
        anim.add("hurt", frames.get("hurt", []), 12, loop=False, on_finish="idle")
        anim.add("death", frames.get("death", []), 10, loop=False)
        anim.play("idle")
        self.animator = anim
        # 阶段攻击动画名：action 层播放攻击时动态读取（阶段 2 召唤/施法无专门
        # 动作，播放 idle 表示原地对空引导）
        self.attack_anim_name: str = "attack"
        self._phase1_tree: BehaviorTree = create_elite_phase1_tree()
        self._phase2_tree: BehaviorTree = create_elite_phase2_tree()
        self._phase3_tree: BehaviorTree = create_elite_phase3_tree()
        self.behavior_tree = self._phase1_tree

    @property
    def phase(self) -> int:
        """当前阶段（1/2/3）。"""
        return self._phase

    @property
    def attack_element(self):
        """攻击元素：仅阶段 3 狂暴（血量 <40%）附着冰元素，其余阶段物理。"""
        from src.combat.element import Element
        return Element.ICE if self._phase == 3 else Element.NONE

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
                self.attack_anim_name = "attack"      # 远程消耗 → attack0
            elif new_phase == 2:
                self.behavior_tree = self._phase2_tree
                self.attack_anim_name = "idle"        # 召唤/施法 → 原地待机姿态
            else:
                self.behavior_tree = self._phase3_tree
                self.attack_anim_name = "attack_rage" # 狂暴连击 → attack1

    def take_ai_turn(self, manager) -> NodeStatus | None:
        """每回合 tick 前检查阶段切换。"""
        self._update_phase()
        return super().take_ai_turn(manager)
