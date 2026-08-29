"""
敌人基类模块。

功能说明：
    Enemy 继承 Entity，作为所有敌人的基类。持有 behavior_tree 引用
    （Day 6 注入）。Day 4 仅作为占位实体存在，用于战斗框架联调：
    进入战斗房后会生成 1-2 个 Enemy 占位，玩家可以"攻击"它们
    （Day 4 不扣血，Day 5 接入伤害）。

Day 6 会接入 AI：
    - 简单 AI：巡逻→发现玩家→追击→攻击
    - 远程 AI：保持距离→远程攻击
    - Boss AI：多阶段技能切换
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.nodes import NodeStatus  # noqa: E402 (避免循环导入由 TYPE_CHECKING 保护)
from src.core import config
from src.entities.entity import Entity
from src.entities.stats import Stats
from src.utils.vector import Vector2

if TYPE_CHECKING:
    from src.ai.behavior_tree import BehaviorTree


class Enemy(Entity):
    """敌人基类。"""

    def __init__(
        self,
        position: Vector2 | None = None,
        stats: Stats | None = None,
        name: str = "Enemy",
        color: tuple[int, int, int] = config.COLOR_ENEMY,
    ):
        # 默认数值：史莱姆基线（PRD 第 4.5 节）
        if stats is None:
            stats = Stats(
                max_hp=8,
                atk=3,
                def_=1,
                max_ap=3,
                move_range=2,
            )
        super().__init__(position=position, stats=stats, color=color, name=name)
        # 行为树引用，Day 6 注入
        self.behavior_tree: "BehaviorTree | None" = None
        # 击杀掉落金币（商店经济系统，子类覆盖）
        self.gold_reward: int = 0

    # ========== AI 接口（Day 6 实现） ==========

    def set_behavior_tree(self, tree: "BehaviorTree") -> None:
        """注入行为树。Day 6 调用。"""
        self.behavior_tree = tree

    def take_ai_turn(self, manager) -> "NodeStatus | None":
        """
        敌人执行一次 AI tick。
        Day 6：调用 behavior_tree.tick()，返回节点状态。
        """
        if self.behavior_tree is not None:
            return self.behavior_tree.tick(self, manager)
        return None

    # ========== 渲染 ==========

    def render(self, screen, cam_x: float, cam_y: float) -> None:
        """先按动画帧渲染（无素材时基类回退色块），再画头顶 HP 条。"""
        import pygame
        super().render(screen, cam_x, cam_y)
        ts = config.TILE_SIZE
        sx = int((self.position.x - cam_x) * ts)
        sy = int((self.position.y - cam_y) * ts)

        # 头顶 HP 条（仅在受伤时显示）
        if self.stats.hp < self.stats.max_hp:
            bar_w = ts - 6
            bar_h = 3
            bar_x = sx + 3
            bar_y = sy - 5
            # 背景（红）
            pygame.draw.rect(screen, (60, 0, 0), (bar_x, bar_y, bar_w, bar_h))
            # 前景（绿，按比例）
            ratio = self.stats.hp / self.stats.max_hp
            pygame.draw.rect(
                screen, (80, 220, 80),
                (bar_x, bar_y, int(bar_w * ratio), bar_h),
            )
