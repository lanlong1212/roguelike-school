"""
怪物元素攻击 + 护盾技能单元测试。

覆盖：
- 怪物攻击元素定义：史莱姆水、骷髅火、精英（仅阶段 3 冰）、Boss 雷/震击火
- 怪物攻击自动附着元素（持续 2 回合，走 damage 管道反应链）
- 玩家初始技能含护盾；护盾施放附加吸收状态；吸收伤害；2 回合后消失
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from src.combat.action import AttackAction, SkillAction
from src.combat.battle_manager import BattleManager
from src.combat.damage import apply_damage
from src.combat.element import Element
from src.combat.status_effect import EffectType
from src.core import config
from src.entities.enemies.boss import Boss
from src.entities.enemies.elite import Elite
from src.entities.enemies.skeleton import Skeleton
from src.entities.enemies.slime import Slime
from src.entities.enemy import Enemy
from src.entities.player import Player
from src.entities.stats import Stats
from src.utils.vector import Vector2
from src.world.tilemap import TileMap


def _make_battle():
    """玩家 + 1 个普通敌人 + 空地图（测试怪物元素攻击与护盾用）。"""
    tm = TileMap(20, 20)
    player = Player(position=Vector2(5, 5))
    enemy = Enemy(
        position=Vector2(3, 5),
        stats=Stats(max_hp=60, atk=4, def_=0, max_ap=5, move_range=5),
    )
    enemy.stats.crit_rate = 0.0
    battle = BattleManager(player, [enemy], tm)
    return battle, player, enemy


def _shield_action(player):
    return SkillAction(
        actor=player, target=player, skill_id="shield",
        multiplier=0.0, ap_cost=1, skill_name="护盾",
    )


# ========== 怪物攻击元素定义 ==========

def test_slime_attack_element_is_water():
    assert Slime().attack_element is Element.WATER


def test_skeleton_attack_element_is_fire():
    assert Skeleton().attack_element is Element.FIRE


def test_elite_attack_element_only_phase3_ice():
    """精英：阶段 1/2 物理，阶段 3（血量 <40%）附着冰。"""
    elite = Elite()
    elite.stats.hp = int(elite.stats.max_hp * 0.8)
    elite._update_phase()
    assert elite.phase == 1
    assert elite.attack_element is Element.NONE
    elite.stats.hp = int(elite.stats.max_hp * 0.5)
    elite._update_phase()
    assert elite.phase == 2
    assert elite.attack_element is Element.NONE
    elite.stats.hp = int(elite.stats.max_hp * 0.3)
    elite._update_phase()
    assert elite.phase == 3
    assert elite.attack_element is Element.ICE


def test_boss_attack_elements():
    boss = Boss()
    assert boss.attack_element is Element.LIGHTNING   # 普攻/连击
    assert boss.attack_aoe_element is Element.FIRE     # 全屏震击


# ========== 怪物攻击自动附着元素 ==========

def test_monster_attack_attaches_element():
    """带元素的怪物攻击自动附着 2 回合（伤害管道内）。"""
    battle, player, enemy = _make_battle()
    slime = Slime(position=Vector2(4, 5))
    AttackAction(
        actor=slime, target=player, ap_cost=2, multiplier=1.0,
        skill_name="撕咬", element=slime.attack_element,
    ).execute(battle)
    assert player.status_effects.aura is Element.WATER
    assert player.status_effects.aura_remaining == 2


# ========== 护盾技能 ==========

def test_player_initial_skills_include_shield():
    p = Player()
    assert [s.id for s in p.skills] == ["basic_attack", "ember", "shield"]


def test_shield_skill_applies_and_absorbs():
    """护盾施放：附加吸收 SHIELD_ABSORB 点、2 回合；受伤时优先被护盾吸收。"""
    battle, player, enemy = _make_battle()
    _shield_action(player).execute(battle)
    shield = player.status_effects.get(EffectType.SHIELD)
    assert shield is not None
    assert shield.magnitude == config.SHIELD_ABSORB
    assert shield.duration == 2
    # ATK4 vs DEF2 → 3 点伤害，护盾全吸收，HP 不变
    hp0 = player.stats.hp
    apply_damage(enemy, player, 1.0)
    assert player.stats.hp == hp0
    assert player.status_effects.get(EffectType.SHIELD).magnitude == config.SHIELD_ABSORB - 3


def test_shield_expires_after_two_turn_ends():
    """护盾 2 回合后自动消失（on_turn_end 倒计时）。"""
    battle, player, enemy = _make_battle()
    _shield_action(player).execute(battle)
    assert player.status_effects.has(EffectType.SHIELD)
    player.status_effects.on_turn_end(player)  # 回合结束 → 剩 1
    assert player.status_effects.has(EffectType.SHIELD)
    player.status_effects.on_turn_end(player)  # 再结束 → 归零消失
    assert not player.status_effects.has(EffectType.SHIELD)
