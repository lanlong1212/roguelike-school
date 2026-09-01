"""
伙伴系统单元测试。

覆盖：
- 嘲讽 0 AP + 每回合限 1 次（第二次施放被 can_execute 拒绝，新回合重置）
- 守护光环：伙伴存活时主角每回合首次受伤 -2，第二次不触发，伙伴阵亡失效
- 反击姿态：近战攻击触发反弹 50% 伤害、远程不触发、下回合清除
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from src.combat.action import AttackAction, SkillAction
from src.combat.battle_manager import BattleManager
from src.combat.damage import apply_damage
from src.combat.status_effect import EffectType
from src.entities.companion import Companion
from src.entities.enemy import Enemy
from src.entities.player import Player
from src.entities.stats import Stats
from src.utils.vector import Vector2
from src.world.tilemap import TileMap


def _make_battle():
    """玩家 + 伙伴 + 1 敌人 + 空地图。"""
    tm = TileMap(20, 20)
    player = Player(position=Vector2(5, 5))
    companion = Companion(position=Vector2(4, 5))
    enemy = Enemy(
        position=Vector2(3, 5),
        stats=Stats(max_hp=60, atk=4, def_=0, max_ap=5, move_range=5),
    )
    # 固定暴击率 0，保证伤害断言不受随机暴击影响
    enemy.stats.crit_rate = 0.0
    companion.stats.crit_rate = 0.0
    battle = BattleManager(player, [enemy], tm, companions=[companion])
    return battle, player, companion, enemy


def _taunt_action(actor, target):
    return SkillAction(
        actor=actor, target=target, skill_id="taunt", ap_cost=0,
        multiplier=0.0, skill_name="嘲讽", apply_effect=EffectType.TAUNT,
        effect_duration=2,
    )


def test_taunt_free_ap_once_per_turn():
    """嘲讽 0 AP；每回合限 1 次；新回合重置。"""
    battle, player, companion, enemy = _make_battle()
    assert companion.get_skill("taunt").ap_cost == 0
    # 切到伙伴受控（模拟 Tab），第一次施放成功并标记
    assert battle.switch_actor(companion)
    assert battle.execute_action(_taunt_action(companion, enemy))
    assert companion.taunt_used_this_turn is True
    # 第二次被拒绝（AP 充足也拒绝）
    assert not battle.can_execute(_taunt_action(companion, enemy))
    # 走完敌人回合 → 玩家新回合开始，限次标记重置
    battle.end_player_turn()
    while battle.is_enemy_turn:
        battle.step_enemy_turn()
    assert companion.taunt_used_this_turn is False
    assert battle.can_execute(_taunt_action(companion, enemy))


def test_guardian_halo_reduces_first_hit_only():
    """守护光环：伙伴存活时玩家每回合首次受伤 -2，第二次不减。"""
    battle, player, companion, enemy = _make_battle()
    assert player.guardian_halo_active is True
    hp0 = player.stats.hp
    # 第一次受伤：ATK4 vs DEF2 → 3 点，光环 -2 → 1
    apply_damage(enemy, player, 1.0)
    assert player.stats.hp == hp0 - 1
    assert player.guardian_halo_used is True
    # 第二次受伤：无减伤，掉 3
    hp1 = player.stats.hp
    apply_damage(enemy, player, 1.0)
    assert player.stats.hp == hp1 - 3


def test_guardian_halo_disabled_when_companion_dead():
    """伙伴阵亡后守护光环失效（后续受伤不再减伤）。"""
    battle, player, companion, enemy = _make_battle()
    companion.stats.hp = 0
    battle._handle_ally_death()
    assert companion.alive is False
    assert player.guardian_halo_active is False
    hp0 = player.stats.hp
    apply_damage(enemy, player, 1.0)
    assert player.stats.hp == hp0 - 3  # 无减伤


def test_counter_stance_retaliates_melee():
    """反击姿态：近战攻击伙伴 → 对攻击者反弹所受伤害的 50%。"""
    battle, player, companion, enemy = _make_battle()
    action = SkillAction(
        actor=companion, target=companion, skill_id="counter_stance",
        ap_cost=1, multiplier=0.0, skill_name="反击姿态",
    )
    assert battle.execute_action(action)
    assert companion.counter_stance_active is True
    # 敌人贴脸普攻：ATK4 vs 伙伴 DEF3 → 2 点；反击 = max(1, 2*0.5) = 1
    enemy_hp = enemy.stats.hp
    AttackAction(actor=enemy, target=companion, ap_cost=2, multiplier=1.0).execute(battle)
    assert enemy.stats.hp == enemy_hp - 1
    assert companion.counter_stance_active is True  # 本回合仍有效


def test_counter_stance_no_retaliate_ranged():
    """反击姿态：远程攻击（距离 >1）不触发反击。"""
    battle, player, companion, enemy = _make_battle()
    enemy.move_to(10, 5)
    companion.counter_stance_active = True
    enemy_hp = enemy.stats.hp
    AttackAction(actor=enemy, target=companion, ap_cost=2, multiplier=1.0).execute(battle)
    assert enemy.stats.hp == enemy_hp
    assert battle.last_counter_result is None


def test_counter_stance_clears_next_turn():
    """反击姿态仅本回合有效：新回合开始时清除。"""
    battle, player, companion, enemy = _make_battle()
    companion.counter_stance_active = True
    battle.end_player_turn()
    while battle.is_enemy_turn:
        battle.step_enemy_turn()
    assert companion.counter_stance_active is False
