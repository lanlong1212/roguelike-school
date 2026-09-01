"""
玩家角色模块。

Day 5 扩展：
    - 增加 skills 技能列表（1 基础攻击 + 2 主动技能）
    - 技能数据类 Skill 含 id/name/ap_cost/range/multiplier/desc
    - 提供 get_skill(id) 与默认技能配置

元素系统扩展：
    - Skill 增加 element 字段（物理/火/水/冰/雷）
    - 新增寒冰箭/水弹/雷击，凑齐 4 种元素技能用于元素反应

休息房间扩展（技能学习）：
    - 玩家初始只拥有 basic_attack
    - _SKILL_POOL 定义可学习技能池，休息房间"强化"从中学习
    - learn_skill(skill_id) 将技能加入已学列表（去重）

战棋化扩展（AoE / 附加状态）：
    - Skill 增加 aoe 字段：none 单体 / splash 3×3 溅射 / line 直线穿透
    - Skill 增加 apply_effect 字段：命中附加状态（寒冰箭→减速）
    - 远程技能需视线判定（tilemap.has_line_of_sight），可被障碍柱阻挡

技能配置：
    basic_attack  基础攻击  2 AP  相邻 1 格  1.0×  物理   （初始自带）
    ember         火苗术    2 AP  2 格      1.0×  火          （初始自带，习得火球术后移除）
    charge_slash  冲锋斩    3 AP  相邻 1 格  1.8×  物理
    fireball      火球术    3 AP  5 格      1.8×  火  3×3 溅射
    ice_arrow     寒冰箭    3 AP  4 格      1.6×  冰  附加减速
    water_shot    水弹      2 AP  3 格      1.2×  水
    lightning     雷击      3 AP  4 格      1.7×  雷  直线穿透
"""
from __future__ import annotations

from dataclasses import dataclass

from src.combat.element import Element
from src.combat.status_effect import EffectType
from src.core import config
from src.entities.entity import Entity
from src.entities.stats import Stats
from src.items.inventory import Inventory
from src.utils.vector import Vector2
from src.world.tilemap import TileMap


@dataclass
class Skill:
    """技能数据类。"""
    id: str            # 技能标识
    name: str          # 显示名
    ap_cost: int       # AP 消耗
    range_cells: int   # 攻击距离（格）
    multiplier: float  # 伤害倍率
    desc: str           # 技能描述
    element: Element = Element.NONE  # 技能元素（命中附着，触发反应）
    aoe: str = "none"  # 范围形态：none 单体 / splash 3×3 / line 直线穿透
    apply_effect: "EffectType | None" = None  # 命中附加状态（如减速）
    effect_duration: int = 1    # 附加状态的持续回合数（默认 1）
    effect_chance: float = 1.0  # 附加状态的触发概率 0~1（默认 100%）


# ========== 可学习技能池 ==========
# 玩家初始只拥有 basic_attack，其余技能通过休息房间"强化"从池中学习。
_SKILL_POOL: list[Skill] = [
    Skill(
        id="basic_attack",
        name="基础攻击",
        ap_cost=2,
        range_cells=1,
        multiplier=1.0,
        desc="对相邻敌人造成 ATK×1.0 物理伤害",
    ),
    Skill(
        id="ember",
        name="火苗术",
        ap_cost=2,
        range_cells=2,
        multiplier=1.0,
        desc="对 2 格内单体造成 ATK×1.0 火伤，附着火元素",
        element=Element.FIRE,
    ),
    Skill(
        id="shield",
        name="护盾",
        ap_cost=1,
        range_cells=0,
        multiplier=0.0,
        desc="给自身附加护盾，吸收 6 点伤害，持续 2 回合",
        apply_effect=EffectType.SHIELD,
        effect_duration=2,
    ),
    Skill(
        id="charge_slash",
        name="冲锋斩",
        ap_cost=3,
        range_cells=1,
        multiplier=1.8,
        desc="对相邻敌人造成 ATK×1.8 物理伤害",
    ),
    Skill(
        id="fireball",
        name="火球术",
        ap_cost=3,
        range_cells=5,
        multiplier=1.8,
        desc="对 5 格内目标及周围 3×3 造成 ATK×1.8 火伤，附着火元素",
        element=Element.FIRE,
        aoe="splash",
    ),
    Skill(
        id="ice_arrow",
        name="寒冰箭",
        ap_cost=3,
        range_cells=4,
        multiplier=1.6,
        desc="对 4 格内单体造成 ATK×1.6 冰伤，附着冰元素并减速 1 回合",
        element=Element.ICE,
        apply_effect=EffectType.SLOW,
    ),
    Skill(
        id="water_shot",
        name="水弹",
        ap_cost=2,
        range_cells=3,
        multiplier=1.2,
        desc="对 3 格内单体造成 ATK×1.2 水伤，附着水元素",
        element=Element.WATER,
    ),
    Skill(
        id="lightning",
        name="雷击",
        ap_cost=3,
        range_cells=4,
        multiplier=1.7,
        desc="对 4 格内直线全体造成 ATK×1.7 雷伤，附着雷元素",
        element=Element.LIGHTNING,
        aoe="line",
    ),
]


def get_skill_pool() -> list[Skill]:
    """返回技能池副本（供休息房间"强化"选择）。"""
    return [Skill(**s.__dict__) for s in _SKILL_POOL]


def learn_fireball_replacing_ember(player: "Player") -> bool:
    """学习火球术并移除初始火苗术（供天赋/遗物等未来授予点统一调用）。

    内部复用 learn_skill 的 fireball 特判（先移除 ember 再添加）；
    已拥有火球术时返回 False，避免重复移除或添加。
    """
    return player.learn_skill("fireball")


# ========== 被动天赋（PRD 技能子系统：升级三选一节点） ==========

@dataclass
class Talent:
    """被动天赋数据类。学习即永久生效（直接修改 Stats）。"""
    id: str      # 天赋标识
    name: str    # 显示名
    desc: str    # 描述


# 天赋池：学习时按 id 应用到 Stats（攻击强化只走技能与武器，天赋不加攻击）
_TALENT_POOL: list[Talent] = [
    Talent(
        id="hp_up",
        name="生命增幅",
        desc="最大生命 +10%",
    ),
    Talent(
        id="ap_up",
        name="精力充沛",
        desc="AP 上限 +1",
    ),
    Talent(
        id="move_up",
        name="轻步疾行",
        desc="战斗移动范围 +1 格",
    ),
    Talent(
        id="summon_companion",
        name="召唤伙伴",
        desc="召唤一名伙伴加入战斗（独立 2 AP/回合，不消耗主角 AP）",
    ),
]


def get_talent_pool() -> list[Talent]:
    """返回天赋池副本。"""
    return [
        Talent(id=t.id, name=t.name, desc=t.desc) for t in _TALENT_POOL
    ]


def _apply_talent_effect(player: "Player", talent_id: str) -> None:
    """天赋学习效果：永久修改玩家属性。新增天赋时在此分支。"""
    if talent_id == "hp_up":
        increase = max(1, round(player.stats.max_hp * 0.10))
        player.stats.max_hp += increase
        player.stats.hp += increase
    elif talent_id == "ap_up":
        player.stats.max_ap += 1
    elif talent_id == "move_up":
        player.stats.move_range += 1


class Player(Entity):
    """玩家角色。"""

    def __init__(self, position: Vector2 | None = None):
        stats = Stats(
            max_hp=20,  # 初始血量 20
            atk=6,
            def_=2,
            max_ap=config.AP_MAX,
            move_range=config.MOVE_RANGE,
        )
        super().__init__(
            position=position,
            stats=stats,
            color=config.COLOR_PLAYER,
            name="Player",
        )
        # 技能列表（深拷贝避免共享）：初始为基础攻击 + 火苗术 + 护盾。
        # 火苗术是 L1 初始元素手段，习得火球术后自动移除（见 learn_skill）。
        self.skills: list[Skill] = [Skill(**s.__dict__) for s in _SKILL_POOL[:3]]
        # 当前选中的技能（None=未选中，使用基础攻击）
        self.selected_skill: Skill | None = None
        # Day 7：背包系统
        self.inventory: Inventory = Inventory(self)
        # 本局货币（商店购买用，初始 START_GOLD）
        self.gold: int = config.START_GOLD
        # 已学天赋 id 列表（被动天赋，学习即生效）
        self.talents: list[str] = []
        # ========== 遗物系统（docs/遗物系统） ==========
        # 当前携带的遗物 ID 列表（效果跨战斗持续，随存档保存）
        self.relics: list[str] = []
        # 本局已获得过的遗物 ID 集合（图鉴解锁用；重复掉落不再计数）
        self.owned_relics: set[str] = set()
        # 本回合是否已移动（轻羽靴：每回合首次移动不耗 AP；回合开始由战斗管理器重置）
        self.moved_this_turn: bool = False
        # 本层守护符是否已使用（守护符：每层首次受伤免疫；下楼重置）
        self.layer_guard_used: bool = False
        # 已应用"获得即改属性"效果的遗物 ID 集合（读档重放幂等保护；
        # 只影响属性类遗物如巨人之力，被动类遗物按 ID 实时查询不在此列）
        self._applied_relic_effects: set[str] = set()
        # 守护光环（伙伴天生被动）：伙伴存活时主角每回合首次受伤 -2。
        # guardian_halo_active 由 battle_manager 在回合开始/伙伴阵亡时维护；
        # guardian_halo_used 每回合首次受伤后置 True，回合开始重置。
        self.guardian_halo_active: bool = False
        self.guardian_halo_used: bool = False
        # 动画：idle/walk/attack × 4 朝向（目录帧序列，缺素材自动跳过）
        self._build_animator()

    def _build_animator(self) -> None:
        """从 assets/images/entities/player/ 构建四向动画状态机。"""
        from src.core.asset_manager import assets
        from src.entities.animation import Animator

        anim = Animator()
        # walk 15fps：长按行走每格 0.15s（约 2.25 帧/格），脚步节奏与移动频率匹配
        for state, fps in (("idle", 5), ("walk", 15), ("attack", 14)):
            for d in ("down", "up", "left", "right"):
                anim.add(
                    f"{state}_{d}",
                    assets.get_frames(f"entities/player/{state}/{d}"),
                    fps,
                    loop=(state != "attack"),
                    on_finish=f"idle_{d}" if state == "attack" else None,
                )
        anim.play("idle_down")
        self.animator = anim

    # ========== 技能学习接口 ==========

    def learn_skill(self, skill_id: str) -> bool:
        """从技能池学习一个技能（已学会返回 False）。"""
        if self.get_skill(skill_id) is not None:
            return False
        # 火球术取代初始火苗术：先移除 ember 再添加，保持技能栏顺序合理
        if skill_id == "fireball":
            self.skills = [s for s in self.skills if s.id != "ember"]
        for s in _SKILL_POOL:
            if s.id == skill_id:
                self.skills.append(Skill(**s.__dict__))
                return True
        return False

    # ========== 天赋接口 ==========

    def learn_talent(self, talent_id: str) -> bool:
        """学习天赋：属性永久生效（重复学习返回 False）。"""
        if talent_id in self.talents:
            return False
        if not any(t.id == talent_id for t in _TALENT_POOL):
            return False
        self.talents.append(talent_id)
        _apply_talent_effect(self, talent_id)
        return True

    def unlearned_talents(self) -> list[Talent]:
        """返回尚未学习的天赋列表（供休息房间强化）。"""
        return [
            Talent(id=t.id, name=t.name, desc=t.desc)
            for t in _TALENT_POOL if t.id not in self.talents
        ]

    # ========== 遗物接口 ==========

    def apply_relic_effects(self) -> None:
        """重放"获得即改属性"遗物的效果（读档恢复 relics 后调用一次）。

        幂等设计：已应用过加成的遗物先反向还原回基础值，再统一重新应用，
        重复调用结果一致，不会叠加；与天赋"先重放再由存档值精确覆盖"
        的模式配合，避免读档后属性翻倍。
        """
        from src.items.relics import apply_relic_effect, revert_relic_effect

        # 1. 已应用过加成的遗物先还原回基础值
        for rid in self.relics:
            if rid in self._applied_relic_effects:
                revert_relic_effect(self, rid)
                self._applied_relic_effects.discard(rid)
        # 2. 统一重新应用（被动类遗物无属性分支，自然跳过）
        for rid in self.relics:
            if rid not in self._applied_relic_effects:
                apply_relic_effect(self, rid)
                self._applied_relic_effects.add(rid)

    # ========== 技能接口 ==========

    def get_skill(self, skill_id: str) -> Skill | None:
        """按 id 查询技能。"""
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def select_skill(self, skill_id: str | None) -> None:
        """
        选中技能（None 或 "basic_attack" 表示用基础攻击）。
        selected_skill 用于 UI 高亮与点击时确定使用哪个技能。
        """
        if skill_id is None:
            self.selected_skill = None
            return
        skill = self.get_skill(skill_id)
        if skill is None:
            self.selected_skill = None
        else:
            self.selected_skill = skill

    @property
    def active_skill(self) -> Skill:
        """当前生效的技能（未选中则返回基础攻击）。"""
        if self.selected_skill is None:
            return self.skills[0]  # basic_attack
        return self.selected_skill

    # ========== 探索模式：WASD 移动 ==========

    def try_move_explore(
        self,
        dx: int,
        dy: int,
        tilemap: TileMap,
    ) -> bool:
        if dx == 0 and dy == 0:
            return False
        target_gx = self.grid_x + dx
        target_gy = self.grid_y + dy
        if not tilemap.is_walkable(target_gx, target_gy):
            return False
        self.move_to(target_gx, target_gy)
        return True

