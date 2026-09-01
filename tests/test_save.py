"""
存档系统单元测试。

覆盖：
- save_game → load_game 数据往返一致
- apply_save_to_player 恢复属性/金币/背包/装备/技能
- 武器加成剔除与重挂（装备后保存，读档后加成不翻倍）
- clear_save 后无存档；损坏存档文件容错返回 None

存档路径指向临时目录（tempfile），不污染真实存档。
"""
import os
import tempfile

from src.core import save_manager
from src.entities.player import Player
from src.items.potion import HealthPotion
from src.items.weapon import create_iron_sword
from src.utils.vector import Vector2


class _SaveDirGuard:
    """把 save_manager 的存档路径临时指向新目录，结束时自动恢复。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="roguelike_test_save_")
        self._old_dir = save_manager.SAVE_DIR
        self._old_file = save_manager.SAVE_FILE
        save_manager.SAVE_DIR = self.dir
        save_manager.SAVE_FILE = os.path.join(self.dir, "save.json")

    def cleanup(self):
        save_manager.SAVE_DIR = self._old_dir
        save_manager.SAVE_FILE = self._old_file


def _do_save(p: Player, cleared=None) -> None:
    save_manager.save_game(
        player=p,
        level=3,
        floor_seed=12345,
        pos=Vector2(12, 34),
        kills=8,
        cleared_rooms=cleared or set(),
    )


def _make_player() -> Player:
    """带金币/受伤/药水的玩家。"""
    p = Player()
    p.gold = 77
    p.stats.hp = 15
    p.inventory.add(HealthPotion())
    return p


def test_save_load_roundtrip():
    """保存后读取，字段全部一致。"""
    guard = _SaveDirGuard()
    try:
        _do_save(_make_player(), cleared={(5, 6), (7, 8)})
        data = save_manager.load_game()
        assert data is not None
        assert data["level"] == 3
        assert data["floor_seed"] == 12345
        assert data["kills"] == 8
        assert data["player"]["x"] == 12
        assert data["player"]["y"] == 34
        assert data["player"]["gold"] == 77
        assert data["player"]["hp"] == 15
        assert data["player"]["max_hp"] == 20  # 当前初始血量
        assert {(c[0], c[1]) for c in data["cleared_rooms"]} == {(5, 6), (7, 8)}
        assert save_manager.has_save()
    finally:
        guard.cleanup()


def test_apply_save_restores_player():
    """apply_save_to_player 恢复属性/金币/背包/技能到新玩家对象。"""
    guard = _SaveDirGuard()
    try:
        p = _make_player()
        p.stats.atk = 13
        p.stats.def_ = 5
        p.learn_skill("fireball")
        _do_save(p)

        fresh = Player()
        fresh.stats.max_hp = 20  # 与保存时基础 max_hp 对齐
        data = save_manager.load_game()
        save_manager.apply_save_to_player(fresh, data)

        assert fresh.stats.hp == 15
        assert fresh.stats.atk == 13
        assert fresh.stats.def_ == 5
        assert fresh.gold == 77
        item_ids = [s.id for s in fresh.inventory.slots if s is not None]
        assert "health_potion" in item_ids
        assert any(s.id == "fireball" for s in fresh.skills)
    finally:
        guard.cleanup()


def test_weapon_bonus_not_doubled():
    """装备武器保存：序列化剔除加成；读档重挂后总属性一致（不翻倍）。"""
    guard = _SaveDirGuard()
    try:
        p = _make_player()
        sword = create_iron_sword()
        p.inventory.equip_weapon(sword)
        total_atk = p.stats.atk
        _do_save(p)

        fresh = Player()
        fresh.stats.max_hp = 20
        data = save_manager.load_game()
        save_manager.apply_save_to_player(fresh, data)

        # 序列化的是基础值（不含武器加成）
        assert data["player"]["atk"] == total_atk - sword.stat_modifiers.atk_bonus
        # 读档重挂后总攻击力一致
        assert fresh.stats.atk == total_atk
        assert fresh.inventory.equipped_weapon is not None
        assert fresh.inventory.equipped_weapon.id == "iron_sword"
    finally:
        guard.cleanup()


def test_clear_save():
    """清档后 has_save 为 False，文件已删除。"""
    guard = _SaveDirGuard()
    try:
        _do_save(_make_player())
        assert save_manager.has_save()
        save_manager.clear_save()
        assert not save_manager.has_save()
        assert not os.path.exists(save_manager.SAVE_FILE)
    finally:
        guard.cleanup()


def test_corrupted_save_returns_none():
    """存档损坏（非法 JSON）时 load 返回 None 而非抛异常。"""
    guard = _SaveDirGuard()
    try:
        os.makedirs(save_manager.SAVE_DIR, exist_ok=True)
        with open(save_manager.SAVE_FILE, "w", encoding="utf-8") as f:
            f.write("{broken json!!")
        assert save_manager.load_game() is None
        assert not save_manager.has_save()
    finally:
        guard.cleanup()


def test_no_save_returns_none():
    """从未存档时 load 返回 None。"""
    guard = _SaveDirGuard()
    try:
        assert save_manager.load_game() is None
    finally:
        guard.cleanup()


def test_companion_save_roundtrip():
    """存活伙伴：存档写入属性/位置/技能；AP 加成标志为 True。"""
    from src.core import config
    from src.entities.companion import Companion
    guard = _SaveDirGuard()
    try:
        p = _make_player()
        c = Companion(position=Vector2(5, 6))
        c.learn_skill("shield_bash")
        c.stats.hp = 10
        c.stats.max_hp = 18  # 模拟成长
        p.stats.max_ap = config.AP_MAX + 1  # 其他改动（与伙伴无关，仅验证存档一致性）
        save_manager.save_game(
            player=p, level=3, floor_seed=12345,
            pos=Vector2(12, 34), kills=8, companion=c,
        )
        data = save_manager.load_game()
        comp = data["companion"]
        assert comp["exists"] is True
        assert comp["alive"] is True
        assert comp["ap_bonus_active"] is True
        assert comp["x"] == 5 and comp["y"] == 6
        assert comp["hp"] == 10 and comp["max_hp"] == 18
        assert comp["atk"] == 3 and comp["def_"] == 3
        assert comp["skills"] == ["taunt", "counter_stance", "shield_bash"]
    finally:
        guard.cleanup()


def test_companion_death_saved_and_not_revived():
    """伙伴死亡：存档 alive=False、ap_bonus_active=False（读档不复活、不加 AP）。"""
    from src.entities.companion import Companion
    guard = _SaveDirGuard()
    try:
        p = _make_player()
        c = Companion(position=Vector2(5, 6))
        c.alive = False
        c.stats.hp = 0
        save_manager.save_game(
            player=p, level=3, floor_seed=12345,
            pos=Vector2(12, 34), kills=8, companion=c,
        )
        data = save_manager.load_game()
        comp = data["companion"]
        assert comp["exists"] is True
        assert comp["alive"] is False
        assert comp["ap_bonus_active"] is False
    finally:
        guard.cleanup()


def test_summon_talent_replay_no_ap_duplicate():
    """读档重放 summon_companion 天赋不叠加 AP（加成只由伙伴存活决定，
    _apply_talent_effect 对召唤天赋无属性分支，实体恢复才 +1）。"""
    from src.core import config
    guard = _SaveDirGuard()
    try:
        p = _make_player()
        p.learn_talent("summon_companion")
        _do_save(p)

        fresh = Player()
        fresh.stats.max_hp = 20
        data = save_manager.load_game()
        save_manager.apply_save_to_player(fresh, data)

        # 天赋重放只记录已学，不改变 AP（伙伴实体由 play_state 恢复层挂载）
        assert fresh.stats.max_ap == config.AP_MAX
        assert "summon_companion" in fresh.talents
        assert all(t.id != "summon_companion" for t in fresh.unlearned_talents())
    finally:
        guard.cleanup()
