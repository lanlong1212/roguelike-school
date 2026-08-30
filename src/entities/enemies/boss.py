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
        self.gold_reward = config.GOLD_BOSS
        # 元素抗性：弱雷 / 抗火、抗冰
        from src.combat.element import Element
        self.element_resist = {
            Element.LIGHTNING: 1.25,
            Element.FIRE: 0.75,
            Element.ICE: 0.75,
        }
        # 动画注册（横向帧表位于 assets/images/entities/boss/，文件名首字母大写）：
        # idle 8fps / walk 10fps 循环；attack(普攻/双连击) 12fps / hurt 12fps
        # 播完回 idle；attack_rage(阶段3 AOE 震击) 12fps 播完回 idle；death 10fps
        # 播完停留。get_actor_frames 以 idle 本体高度为统一缩放基准：idle 满
        # 格显示，攻击大动作（跳起/横扫）同比例缩放、本体大小一致，溢出部分
        # 由加宽加高的画布承载、渲染时自然溢出格子。素材缺失时该动画不在
        # 结果中、add 自动忽略，全部缺失则走 Entity 色块回退，不影响战斗逻辑。
        from src.core.asset_manager import assets
        from src.entities.animation import Animator
        frames = assets.get_actor_frames({
            "idle": "entities/boss/Idle",
            "walk": "entities/boss/Walk",
            "attack": "entities/boss/Attack0",
            "attack_rage": "entities/boss/Attack1",
            "hurt": "entities/boss/Hurt",
            "death": "entities/boss/Death",
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
        # AOE 特效层：attack1 的粒子效果单独帧表（Attack1_fx.png，可选）。
        # 本体帧表只含角色动作（包围盒与 idle 接近，独立缩放不跳变）；
        # 粒子按原始像素尺寸渲染、居中叠加于 Boss 格子，覆盖范围由素材
        # 决定。特效素材缺失时 fx_animator 为 None，行为与无特效一致。
        self.fx_animator: "Animator | None" = None
        fx_frames = assets.get_raw_frames("entities/boss/Attack1_fx")
        if fx_frames:
            fx = Animator()
            fx.add("attack_rage_fx", fx_frames, 12, loop=False)
            fx.play("attack_rage_fx")
            self.fx_animator = fx
        # AOE 尘土粒子（程序化，无素材）：震击时在攻击范围（周围 8 格 +
        # 自身）地板生成向上飘的棕色小点，随寿命收缩变浅消散
        self._particles: list[dict] = []
        # 阶段攻击动画名：action 层播放攻击时动态读取（阶段 1 近战与阶段 2
        # 双连击共用普攻动作，阶段 3 AOE 震击切换大动作帧表）
        self.attack_anim_name: str = "attack"
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
                self.attack_anim_name = "attack"      # 近战 → Attack0
            elif new_phase == 2:
                self.behavior_tree = self._phase2_tree
                self.attack_anim_name = "attack"      # 双连击 → 同款挥击动作
            else:
                self.behavior_tree = self._phase3_tree
                self.attack_anim_name = "attack_rage" # AOE 震击 → Attack1

    def take_ai_turn(self, manager) -> NodeStatus | None:
        """每回合 tick 前检查阶段切换。"""
        self._update_phase()
        return super().take_ai_turn(manager)

    def play_anim(self, state: str, restart: bool = False) -> None:
        """播放本体动画；进入 AOE 震击时同步触发尘土粒子，死亡时清空。"""
        super().play_anim(state, restart)
        if state == "attack_rage":
            if self.fx_animator is not None:
                self.fx_animator.play("attack_rage_fx", restart=True)
            self._spawn_aoe_particles()
        elif state == "death":
            self._particles.clear()

    def _spawn_aoe_particles(self) -> None:
        """在攻击范围（切比雪夫距离 ≤3，与全屏震击判定一致）地板随机
        生成向上飘的棕色尘点。"""
        import random
        ts = config.TILE_SIZE
        radius = 3  # 与 boss_ai._is_player_in_ranged_range 的判定范围一致
        self._particles.clear()
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                gx = self.grid_x + dx
                gy = self.grid_y + dy
                for _ in range(2):  # 每格 2 个尘点（49 格共 98 个）
                    self._particles.append({
                        "x": (gx + random.random()) * ts,      # 世界像素坐标
                        "y": (gy + random.random()) * ts,
                        "vy": -(20.0 + random.random() * 25.0),  # 20~45 px/s 向上飘
                        "life": 0.5 + random.random() * 0.5,     # 0.5~1.0s
                        "age": 0.0,
                        "size": 2.0 + random.random() * 2.0,     # 2~4px
                        "shade": random.random(),                # 棕色深浅
                    })

    def tick_fx(self, dt: float) -> None:
        """推进素材特效层与程序化尘土粒子。"""
        super().tick_fx(dt)
        for p in self._particles:
            p["age"] += dt
            p["y"] += p["vy"] * dt
        self._particles = [p for p in self._particles if p["age"] < p["life"]]

    def render(self, screen, cam_x: float, cam_y: float) -> None:
        """本体 + HP 条之后，叠加 AOE 尘土粒子与素材特效（若有）。"""
        super().render(screen, cam_x, cam_y)
        import pygame
        ts = config.TILE_SIZE
        # 尘土粒子：世界坐标直接减相机；随寿命收缩并向浅色靠拢模拟消散
        for p in self._particles:
            t = p["age"] / p["life"]
            base = (110 + 70 * p["shade"], 75 + 45 * p["shade"], 40 + 25 * p["shade"])
            color = tuple(int(b + (200 - b) * t * 0.6) for b in base)
            r = max(1, round(p["size"] * (1 - t * 0.7)))
            sx = int(p["x"] - cam_x * ts)
            sy = int(p["y"] - cam_y * ts)
            pygame.draw.circle(screen, color, (sx, sy), r)
        fx = self.fx_animator
        if fx is None or fx.is_finished:
            return
        frame = fx.surface
        if frame is None:
            return
        sx = int((self.visual_pos.x - cam_x) * ts)
        sy = int((self.visual_pos.y - cam_y) * ts)
        fw, fh = frame.get_size()
        # 特效按原始像素尺寸、以 Boss 格子为中心叠加（可覆盖周围格子）
        screen.blit(frame, (sx + (ts - fw) // 2, sy + (ts - fh) // 2))
