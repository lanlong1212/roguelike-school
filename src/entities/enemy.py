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
        # 行走结束后的静止计时（超时回待机动画，避免原地循环踏步）
        self._idle_t: float = 0.0
        # 本回合是否已攻击：攻击后 AI 移动节点不再走位，避免攻击动画
        # 起手即被后续走位的 walk 覆盖（演出上只见移动不见攻击）
        self.attacked_this_turn: bool = False
        # 面朝方向：动画素材默认朝右，玩家在自身左侧时渲染前水平翻转镜像。
        # 每帧由状态层根据玩家坐标更新（仅影响视觉，不影响移动/攻击/AI）。
        self.facing_left: bool = False
        # 翻转帧缓存：原帧 id → 翻转帧，避免同一帧每帧重复 flip
        self._flip_cache: dict[int, "pygame.Surface"] = {}

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

    def tick_fx(self, dt: float) -> None:
        """子类特效动画层推进钩子（如 Boss AOE 粒子），默认无。"""
        fx = getattr(self, "fx_animator", None)
        if fx is not None:
            fx.update(dt)

    def tick_idle(self, dt: float, threshold: float = 0.7) -> None:
        """
        行走结束静止超时 → 回待机动画。

        MoveAction 播的 walk 是循环动画，移动到位（视觉插值完成）后若不
        处理会原地循环踏步。仅打断 walk 前缀动画，不碰 attack/death；
        再次移动时 _move_t 归零，计时自动重置。
        """
        if self.animator is None:
            return
        if self._move_t >= 1.0 and self.animator.current.startswith("walk"):
            self._idle_t += dt
            if self._idle_t > threshold:
                self.play_anim("idle")
        else:
            self._idle_t = 0.0

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
