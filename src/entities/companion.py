"""
可控伙伴模块。

定位：肉盾/辅助单位，与主角共享回合与共享 AP 池。
来源：休息房天赋"召唤伙伴"（后续阶段接入）。
属性：初始固定 15HP / 3ATK / 3DEF / 移 3 格，成长只走休息房伙伴阶段。
技能：
    taunt        嘲讽    1 AP  3 格  无伤害，施加"嘲讽"状态强制敌人攻击伙伴
    shield_bash  盾击    2 AP  1 格  0.8× 物理伤害，50% 眩晕 1 回合
说明：本模块做数据层（实体 + 技能配置），技能执行与状态
      效果已由 SkillAction / StatusEffect 链路支持（阶段 4）。
"""
from __future__ import annotations

from src.combat.element import Element
from src.combat.status_effect import EffectType
from src.core import config
from src.entities.entity import Entity
from src.entities.player import Skill 
from src.entities.stats import Stats
from src.utils.vector import Vector2


# ========== 伙伴技能池 ==========
# 嘲讽 multiplier=0.0 无伤害，仅附加"嘲讽"状态（AI 强制以伙伴为目标）
_COMPANION_SKILLS: list[Skill] = [
    Skill(
        id="taunt",
        name="嘲讽",
        ap_cost=1,
        range_cells=3,
        multiplier=0.0,
        desc="嘲讽 3 格内敌人，强制其 2 回合内攻击伙伴",
        element=Element.NONE,
        apply_effect=EffectType.TAUNT,
        effect_duration=2,
    ),
    Skill(
        id="shield_bash",
        name="盾击",
        ap_cost=2,
        range_cells=1,
        multiplier=0.8,
        desc="对相邻敌人造成 ATK×0.8 物理伤害，50% 概率眩晕 1 回合",
        element=Element.NONE,
        apply_effect=EffectType.STUN,
        effect_duration=1,
        effect_chance=0.5,
    ),
]


class Companion(Entity):
    """可控伙伴。肉盾/辅助定位，与主角共享回合与 AP 池。"""

    def __init__(self, position: Vector2 | None = None):
        # 伙伴 AP 字段仅占位（战斗走共享池，见阶段 2），数值填默认即可
        stats = Stats(
            max_hp=15,
            atk=3,
            def_=3,
            max_ap=config.AP_MAX,
            move_range=3,
        )
        super().__init__(
            position=position,
            stats=stats,
            color=config.COLOR_COMPANION,
            name="Companion",
        )
        # 初始技能：仅嘲讽（深拷贝，避免与池共享）
        self.skills: list[Skill] = [Skill(**s.__dict__) for s in _COMPANION_SKILLS[:1]]
        self.selected_skill: Skill | None = None
        self.learned_shield_bash: bool = False
        self.alive: bool = True
        # 渲染镜像用：伙伴在主角左侧时水平翻转（与 Enemy 的 facing_left 逻辑一致）
        self.facing_left: bool = False

    # ========== 技能接口（与 Player 保持一致，供阶段 2 战斗管理器复用） ==========

    def get_skill(self, skill_id: str) -> Skill | None:
        """按 id 查询技能。"""
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    @property
    def active_skill(self) -> Skill:
        """当前生效的技能（未选中则用第一个：嘲讽）。"""
        if self.selected_skill is None:
            return self.skills[0]
        return self.selected_skill

    def select_skill(self, skill_id: str | None) -> None:
        """选中技能（None 表示用默认）。"""
        if skill_id is None:
            self.selected_skill = None
            return
        skill = self.get_skill(skill_id)
        self.selected_skill = skill if skill is not None else None

    def learn_skill(self, skill_id: str) -> bool:
        """学习伙伴技能（盾击每局仅一次，重复学返回 False）。"""
        if self.get_skill(skill_id) is not None:
            return False
        for s in _COMPANION_SKILLS:
            if s.id == skill_id:
                self.skills.append(Skill(**s.__dict__))
                if skill_id == "shield_bash":
                    self.learned_shield_bash = True
                return True
        return False

    # ========== 成长接口（阶段 5 休息房强化调用） ==========

    def upgrade_stats(self) -> None:
        """休息房强化：最大 HP +3，攻击力 +1（可重复）。"""
        self.stats.max_hp += 3
        self.stats.hp += 3
        self.stats.atk += 1
