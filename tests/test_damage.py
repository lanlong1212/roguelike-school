"""
伤害公式与元素反应单元测试。

覆盖：
- 基础伤害公式（攻击×倍率 - 防御×0.5，最低 1 点）
- 暴击（crit_rate 两端 0/1，避免随机性）
- 元素抗性（弱点 1.25 / 抗性 0.75）
- 破甲状态（防御减半）
- 元素附着与六种反应（附着/刷新/消耗/追加伤害/附加状态）
- 感电/融化受击增伤、护盾吸收、apply_damage 完整管道
"""
from src.combat.damage import apply_damage, calculate_damage
from src.combat.element import Element, Reaction, apply_element_impact
from src.combat.status_effect import EffectType, StatusEffect
from src.entities.entity import Entity
from src.entities.stats import Stats


def make_entity(hp=100, atk=10, def_=2, crit_rate=0.0, crit_damage=1.5) -> Entity:
    """构造测试用实体（暴击率默认 0 保证确定性，需要时显式传 1.0）。"""
    stats = Stats(
        max_hp=hp,
        atk=atk,
        def_=def_,
        crit_rate=crit_rate,
        crit_damage=crit_damage,
    )
    return Entity(stats=stats, name="test")


def add_status(target: Entity, effect: EffectType, duration=2, magnitude=1) -> None:
    """给目标附加测试状态。"""
    target.status_effects.add(
        StatusEffect(effect, duration=duration, magnitude=magnitude, source_name="测试")
    )


# ========== 基础公式 ==========

def test_basic_damage_formula():
    """base = ATK×倍率 - DEF×0.5。atk=10, def=2 → 10-1=9。"""
    a, t = make_entity(atk=10), make_entity(def_=2)
    result = calculate_damage(a, t, multiplier=1.0)
    assert result.damage == 9
    assert not result.is_crit


def test_minimum_damage_is_one():
    """防御高于攻击时保底 1 点伤害。"""
    a, t = make_entity(atk=2), make_entity(def_=100)
    assert calculate_damage(a, t, multiplier=1.0).damage == 1


def test_multiplier_scales_attack():
    """倍率线性放大攻击力：atk=10, mult=2.0, def=0 → 20。"""
    a, t = make_entity(atk=10), make_entity(def_=0)
    assert calculate_damage(a, t, multiplier=2.0).damage == 20


def test_crit_always_and_never():
    """crit_rate=1.0 必暴击（×crit_damage），crit_rate=0 从不暴击。"""
    a0 = make_entity(atk=10, crit_rate=0.0, crit_damage=2.0)
    a1 = make_entity(atk=10, crit_rate=1.0, crit_damage=2.0)
    t = make_entity(def_=0)
    assert calculate_damage(a0, t).damage == 10
    assert calculate_damage(a1, t).damage == 20
    assert calculate_damage(a1, t).is_crit


def test_element_resist_multiplier():
    """弱点 ×1.25，抗性 ×0.75。atk=8, def=0 → 正常 8 / 弱点 10 / 抗性 6。"""
    attacker = make_entity(atk=8)
    weak = make_entity(def_=0)
    weak.element_resist[Element.FIRE] = 1.25
    resist = make_entity(def_=0)
    resist.element_resist[Element.FIRE] = 0.75
    normal = make_entity(def_=0)
    assert calculate_damage(attacker, normal, element=Element.FIRE).damage == 8
    assert calculate_damage(attacker, weak, element=Element.FIRE).damage == 10
    assert calculate_damage(attacker, resist, element=Element.FIRE).damage == 6


def test_def_down_halves_defense():
    """破甲状态：有效防御减半。atk=10, def=4 → 正常 8 / 破甲 9。"""
    a = make_entity(atk=10)
    t = make_entity(def_=4)
    assert calculate_damage(a, t).damage == 8
    add_status(t, EffectType.DEF_DOWN, duration=2)
    assert calculate_damage(a, t).damage == 9


# ========== 元素附着与反应 ==========

def test_aura_attachment_and_refresh():
    """首次命中附着；同元素再次命中刷新附着。"""
    a, t = make_entity(), make_entity()
    impact = apply_element_impact(a, t, Element.FIRE)
    assert impact.reaction is None
    assert impact.aura_after is Element.FIRE
    impact2 = apply_element_impact(a, t, Element.FIRE)
    assert impact2.reaction is None
    assert impact2.aura_after is Element.FIRE


def test_physical_never_attaches():
    """物理（NONE）不参与附着与反应。"""
    a, t = make_entity(), make_entity()
    impact = apply_element_impact(a, t, Element.NONE)
    assert impact.aura_after is None
    assert impact.reaction is None


def test_reaction_consumes_aura():
    """反应触发后附着消耗（双方消失）。"""
    a, t = make_entity(), make_entity()
    apply_element_impact(a, t, Element.FIRE)
    impact = apply_element_impact(a, t, Element.WATER)
    assert impact.reaction is Reaction.VAPORIZE
    assert impact.aura_after is None


def test_reaction_pairs_matrix():
    """全部反应对（双向）：火水蒸发 / 冰水冻结 / 雷水感电 / 雷冰超导 / 火冰融化 / 雷火超载。"""
    cases = [
        (Element.FIRE, Element.WATER, Reaction.VAPORIZE),
        (Element.WATER, Element.FIRE, Reaction.VAPORIZE),
        (Element.ICE, Element.WATER, Reaction.FROZEN),
        (Element.WATER, Element.ICE, Reaction.FROZEN),
        (Element.LIGHTNING, Element.WATER, Reaction.ELECTRO_CHARGED),
        (Element.WATER, Element.LIGHTNING, Reaction.ELECTRO_CHARGED),
        (Element.LIGHTNING, Element.ICE, Reaction.SUPERCONDUCT),
        (Element.ICE, Element.LIGHTNING, Reaction.SUPERCONDUCT),
        (Element.FIRE, Element.ICE, Reaction.MELT),
        (Element.ICE, Element.FIRE, Reaction.MELT),
        (Element.LIGHTNING, Element.FIRE, Reaction.OVERLOAD),
        (Element.FIRE, Element.LIGHTNING, Reaction.OVERLOAD),
    ]
    for existing, incoming, expected in cases:
        a, t = make_entity(), make_entity()
        apply_element_impact(a, t, existing)
        impact = apply_element_impact(a, t, incoming)
        assert impact.reaction is expected, f"{existing}+{incoming} 应为 {expected}"
        assert impact.aura_after is None


def test_vaporize_multiplier():
    """蒸发：本次伤害 ×1.5。atk=10, def=0 → 基础 10 → 蒸发 15。"""
    a, t = make_entity(atk=10), make_entity(def_=0)
    apply_element_impact(a, t, Element.WATER)
    result = apply_damage(a, t, multiplier=1.0, element=Element.FIRE)
    assert result.reaction is Reaction.VAPORIZE
    assert result.damage == 15


def test_electro_charged_bonus_and_status():
    """感电：追加 2+ATK 伤害并附加感电状态；本次伤害即被新增的感电增伤 ×1.5。"""
    a, t = make_entity(atk=5), make_entity(def_=0)
    apply_element_impact(a, t, Element.WATER)
    result = apply_damage(a, t, multiplier=1.0, element=Element.LIGHTNING)
    assert result.reaction is Reaction.ELECTRO_CHARGED
    assert t.status_effects.has(EffectType.SHOCK)
    # 基础 5 + 追加(2+atk5)=12，反应当场附加的感电状态随即生效：int(12×1.5)=18
    assert result.damage == 18


def test_shock_status_amplifies_subsequent_hits():
    """感电状态存在时，后续受击伤害 ×1.5。"""
    a = make_entity(atk=10)
    t = make_entity(def_=0)
    add_status(t, EffectType.SHOCK, duration=2)
    result = apply_damage(a, t, multiplier=1.0, element=Element.NONE)
    assert result.damage == 15


def test_melt_status_amplifies():
    """融化状态：受击伤害 ×1.25。atk=10, def=0 → 12。"""
    a = make_entity(atk=10)
    t = make_entity(def_=0)
    add_status(t, EffectType.MELT, duration=1)
    result = apply_damage(a, t, multiplier=1.0, element=Element.NONE)
    assert result.damage == 12


def test_shield_absorbs_damage():
    """护盾优先吸收伤害，超出部分才扣血。atk=10 def=0 → 基础 10：护盾吸 4 + 扣血 6。"""
    a, t = make_entity(atk=10), make_entity(hp=100, def_=0)
    add_status(t, EffectType.SHIELD, duration=3, magnitude=4)
    result = apply_damage(a, t, multiplier=1.0, element=Element.NONE)
    assert result.damage == 6
    assert t.stats.hp == 94


def test_apply_damage_reduces_hp_and_can_kill():
    """完整管道扣血；伤害≥HP 时死亡。"""
    a = make_entity(atk=50)
    t = make_entity(hp=30, def_=0)
    apply_damage(a, t, multiplier=1.0, element=Element.NONE)
    assert t.stats.is_dead()
