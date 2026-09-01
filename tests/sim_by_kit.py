"""
流派数值模拟器（无头蒙特卡洛）。

对每种战斗流派（元素反应连招 / 伙伴坦克 / 长弓放风等）用真实战斗系统
跑批量无头模拟，量化每层每类房间的战斗压力，用于流派强度对比与数值验证。

当前流派：
    electro  感电连击流：水弹挂水 → 雷击触发感电（雷+水 反应：追加 2+ATK 雷伤 +
             感电状态受击 ×1.5 持续 2 回合）。精英/Boss 弱雷再 ×1.25。
             雷击为直线穿透，束内多目标独立结算（同 play_state 规则）。
    frost    冻结控制流：水弹挂水 → 寒冰箭触发冻结（目标跳过下一回合）。
             骷髅弱冰 ×1.25；寒冰箭自带减速。单体强控，Boss 抗冰输出打折。
    superconduct 超导破甲流：寒冰箭挂冰（减速）+ 雷击触发超导（破甲 DEF-50%）。
             精英/Boss 弱雷，骷髅弱冰；破甲后雷击收割。
    overload 超载雷爆流：火苗挂火（初始自带）+ 雷击触发超载（追加雷伤 + 回合末雷爆）。
             L1 即可成型；精英/Boss/骷髅弱雷抗火，火苗仅为挂火工具。
    melt    融化蒸发流：寒冰箭/水弹挂元素 + 火球触发融化（×1.25）/蒸发（×1.5）。
             火球 3×3 溅射，副目标独立结算反应。
    tank    伙伴坦克流：伙伴嘲讽/反击姿态/挡前排 + 守护光环（主角每回合首击 -2），
             主角感电连招输出。
    archer  长弓放风流：长弓（ATK+1，普攻射程 3）纯普攻风筝，无技能兜底。

模拟规则（与 tests/balance_sim.py 一致）：
    - 战场 = 真实 Floor 生成的对应类型房间（含随机障碍柱，含边界墙）
    - 玩家策略（感电连招 + 打带跑）：
        1. 血量≤50% 且有药水 → 喝药（1 AP）
        2. 血量≤50% 且无护盾 → 护盾（1 AP，吸收 6 伤持续 2 回合）
        3. 射程内有"带水/雷附着"的敌人 → 用另一元素技能触发感电
        4. 射程内有"无附着"的敌人 → 水弹挂水（2 AP 便宜，留 AP 下回合触发）
        5. 雷击优先选束内敌人最多的目标（穿透收益）
        6. 危险 → 撤退；安全 → 朝集火目标移动
    - 雷击直线穿透按真实结算：副目标独立 SkillAction（不耗 AP），各自走元素反应链

运行方式：
    python tests/sim_by_kit.py [流派] [N]
        流派: electro（默认全部已实现流派）
        N:    每场景模拟场次，默认 200
"""
from __future__ import annotations

import random
import sys
from collections import deque
from dataclasses import dataclass

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402
pygame.init()  # noqa: E402

from src.combat.action import MoveAction, SkillAction  # noqa: E402
from src.combat.battle_manager import BattleManager  # noqa: E402
from src.combat.element import Element  # noqa: E402
from src.combat.status_effect import EffectType  # noqa: E402
from src.core import config  # noqa: E402
from src.entities.companion import Companion  # noqa: E402
from src.entities.enemies.boss import Boss  # noqa: E402
from src.entities.enemies.elite import Elite  # noqa: E402
from src.entities.enemies.skeleton import Skeleton  # noqa: E402
from src.entities.enemies.slime import Slime  # noqa: E402
from src.entities.player import Player, get_skill_pool  # noqa: E402
from src.items.potion import HealthPotion  # noqa: E402
from src.utils.vector import Vector2  # noqa: E402
from src.world.floor import Floor  # noqa: E402
from src.world.room import RoomType  # noqa: E402
from src.world.tilemap import TileMap  # noqa: E402


# ========== 构筑与流派定义 ==========

@dataclass
class Kit:
    """一个构筑：技能 id 列表 / AP 上限 / 携带药水数 / 武器 / 伙伴 / 策略函数。"""
    label: str
    skills: list[str]
    max_ap: int
    potions: int
    weapon: str = ""          # "" 无 / "iron_sword" / "long_bow"
    companion: bool = False   # 是否带伙伴
    attack: object = None     # 攻击决策函数 (player, alive, tm) -> (skill, target) | None


def _kit_electro(level: int) -> Kit:
    """感电连击流：水弹挂水 + 雷击触发感电（L3 加精力充沛 AP+1）。"""
    potions = 1 if level == 1 else 2
    return Kit(
        label=f"感电连击流 L{level}",
        skills=["basic_attack", "shield", "water_shot", "lightning"],
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        attack=_electro_attack,
    )


def _kit_frost(level: int) -> Kit:
    """冻结控制流：水弹挂水 + 寒冰箭冻结（目标跳过下回合；骷髅弱冰×1.25）。"""
    potions = 1 if level == 1 else 2
    return Kit(
        label=f"冻结控制流 L{level}",
        skills=["basic_attack", "shield", "water_shot", "ice_arrow"],
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        attack=_frost_attack,
    )


def _kit_superconduct(level: int) -> Kit:
    """超导破甲流：寒冰箭挂冰（自带减速）+ 雷击触发超导（破甲 DEF-50%）。
    精英/Boss 弱雷；骷髅弱冰。L1/L2 连招需 6AP 拆两回合。"""
    potions = 1 if level == 1 else 2
    return Kit(
        label=f"超导破甲流 L{level}",
        skills=["basic_attack", "shield", "ice_arrow", "lightning"],
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        attack=_superconduct_attack,
    )


def _kit_overload(level: int) -> Kit:
    """超载雷爆流：火苗挂火（初始自带，L1 即可成型）+ 雷击触发超载
    （追加 1+0.6×ATK 雷伤 + 回合末 2 点雷爆）。精英/Boss/骷髅弱雷抗火。"""
    potions = 1 if level == 1 else 2
    return Kit(
        label=f"超载雷爆流 L{level}",
        skills=["basic_attack", "shield", "ember", "lightning"],
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        attack=_overload_attack,
    )


def _kit_melt(level: int) -> Kit:
    """融化蒸发流：寒冰箭/水弹挂元素 + 火球触发融化（受击×1.25）/蒸发（×1.5）。
    火球 3×3 溅射，副目标独立结算反应。L1 学火球（替换火苗）+寒冰箭，L2 起补水弹。"""
    potions = 1 if level == 1 else 2
    skills = ["basic_attack", "shield", "fireball", "ice_arrow"]
    if level >= 2:
        skills.append("water_shot")
    return Kit(
        label=f"融化蒸发流 L{level}",
        skills=skills,
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        attack=_melt_attack,
    )


def _kit_tank(level: int) -> Kit:
    """伙伴坦克流：召唤伙伴（嘲讽/反击姿态/挡前排）+ 主角感电连招输出。
    守护光环：伙伴存活时主角每回合首次受伤 -2。"""
    potions = 1 if level == 1 else 2
    return Kit(
        label=f"伙伴坦克流 L{level}",
        skills=["basic_attack", "shield", "water_shot", "lightning"],
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        companion=True,
        attack=_electro_attack,
    )


def _kit_archer(level: int) -> Kit:
    """长弓放风流：长弓（ATK+1，普攻射程 3）纯普攻风筝，无技能兜底。"""
    potions = 1 if level == 1 else 2
    return Kit(
        label=f"长弓放风流 L{level}",
        skills=["basic_attack", "shield"],
        max_ap=5 + (1 if level >= 3 else 0),
        potions=potions,
        weapon="long_bow",
        attack=_archer_attack,
    )


# 流派注册表：名称 → 构筑工厂（后续流派在此追加）
KITS: dict[str, callable] = {
    "electro": _kit_electro,
    "frost": _kit_frost,
    "superconduct": _kit_superconduct,
    "overload": _kit_overload,
    "melt": _kit_melt,
    "tank": _kit_tank,
    "archer": _kit_archer,
}


# ========== 战场与实体生成 ==========

_ROOM_OF = {"battle": RoomType.BATTLE, "elite": RoomType.ELITE, "boss": RoomType.BOSS}


def _room_field(level: int, room_type: str, seed: int) -> tuple[TileMap, int, int]:
    """从真实 Floor 提取房间地形（含边界墙与障碍柱），返回 (tilemap, 宽, 高)。"""
    floor = Floor(level=level, seed=seed)
    want = _ROOM_OF[room_type]
    room = next(r for r in floor.rooms if r.room_type == want)
    w, h = room.x2 - room.x1 + 1, room.y2 - room.y1 + 1
    tm = TileMap(w, h)
    for gy in range(h):
        for gx in range(w):
            tm.set_tile(gx, gy, floor.tilemap.get_tile(room.x1 + gx, room.y1 + gy))
    return tm, w, h


def _make_player(kit: Kit, field_h: int) -> tuple[Player, list]:
    """按构筑创建玩家（出生在房间左缘中部）；返回 (玩家, 药水列表)。"""
    p = Player(position=Vector2(1, field_h // 2))
    pool = {s.id: s for s in get_skill_pool()}
    p.skills = [pool[sid] for sid in kit.skills]
    p.stats.max_ap = kit.max_ap
    p.stats.ap = kit.max_ap
    if kit.weapon == "iron_sword":
        from src.items.weapon import create_iron_sword
        p.inventory.equip_weapon(create_iron_sword())
    elif kit.weapon == "long_bow":
        from src.items.weapon import create_long_bow
        p.inventory.equip_weapon(create_long_bow())
    return p, [HealthPotion() for _ in range(kit.potions)]


def _make_enemies(room_type: str, level: int, w: int, h: int) -> list:
    """按房间类型与楼层缩放生成敌人（同 play_state._start_battle 规则）。"""
    scale = 1.0 + (level - 1) * 0.2

    def scaled(e):
        e.stats.max_hp = int(e.stats.max_hp * scale)
        e.stats.hp = e.stats.max_hp
        e.stats.atk = int(e.stats.atk * scale)
        return e

    if room_type == "boss":
        return [scaled(Boss(position=Vector2(w // 2 + 1, h // 2)))]
    if room_type == "elite":
        cx, cy = w // 2, h // 2
        return [
            scaled(Elite(position=Vector2(cx, cy))),
            scaled(Skeleton(position=Vector2(cx + 2, cy))),
        ]
    corners = [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)]
    enemies = [
        scaled(Slime(position=Vector2(*corners[0]))),
        scaled(Skeleton(position=Vector2(*corners[1]))),
    ]
    if level >= 2:  # L2 起战斗房 +1 骷髅（同 play_state 逻辑）
        enemies.append(scaled(Skeleton(position=Vector2(*corners[2]))))
    return enemies


def _make_companion(field_w: int, field_h: int) -> Companion:
    """创建伙伴（出生在玩家右侧，便于开局接战）。"""
    return Companion(position=Vector2(min(2, field_w - 2), field_h // 2))


# ========== 几何 / 寻路 / 威胁辅助 ==========

def _cheb(a: tuple, b: tuple) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _reachable(tm: TileMap, start: tuple, blocked: set, depth: int) -> list[tuple]:
    """BFS 返回 start 出发 depth 步内可到达的格子（不含起点）。"""
    seen = {start}
    out = []
    queue = deque([(start, 0)])
    while queue:
        (x, y), d = queue.popleft()
        if d >= depth:
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, y + dy)
            if nxt in seen or not (0 <= nxt[0] < tm.width and 0 <= nxt[1] < tm.height):
                continue
            if not tm.is_walkable(*nxt) or nxt in blocked:
                continue
            seen.add(nxt)
            out.append(nxt)
            queue.append((nxt, d + 1))
    return out


def _bfs_path(tm: TileMap, start: tuple, goal: tuple, blocked: set) -> list[tuple]:
    """BFS 寻路，返回逐步坐标列表（不含起点；goal 允许为敌人格作为终点）。"""
    if start == goal:
        return []
    prev: dict[tuple, tuple | None] = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if cur == goal:
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt in prev or not (0 <= nxt[0] < tm.width and 0 <= nxt[1] < tm.height):
                continue
            if nxt != goal and (not tm.is_walkable(*nxt) or nxt in blocked):
                continue
            prev[nxt] = cur
            queue.append(nxt)
    if goal not in prev:
        return []
    path = []
    node = goal
    while node != start:
        path.append(node)
        node = prev[node]
    path.reverse()
    return path


def _phase(e) -> int:
    """敌人当前阶段（Boss/精英有，普通怪视为 1）。"""
    ph = getattr(e, "phase", 1)
    return ph() if callable(ph) else ph


def _is_ranged(e) -> bool:
    """远程威胁敌人（骷髅；精英阶段 1/2 远程消耗）。"""
    kind = type(e).__name__
    if kind == "Skeleton":
        return True
    if kind == "Elite":
        return _phase(e) in (1, 2)
    return False


def _threat(e, player_pos: tuple, tm: TileMap) -> int:
    """敌人对玩家的威胁值（越小越危险，999=安全）。"""
    dist = _cheb(player_pos, e.grid_pos)
    if _is_ranged(e):
        if dist <= e.stats.move_range + 4 and tm.has_line_of_sight(
            e.grid_x, e.grid_y, player_pos[0], player_pos[1]
        ):
            return dist - e.stats.move_range
        return 999
    if type(e).__name__ == "Boss" and _phase(e) == 3:
        return dist - (e.stats.move_range + 3)
    return dist - (e.stats.move_range + 1)


def _line_beam_cells(tm: TileMap, start: tuple, target: tuple, max_range: int) -> list[tuple]:
    """直线穿透光束：从 start 经 target 沿同方向延伸至 max_range（同 play_state）。"""
    px, py = start
    tx, ty = target
    line = list(tm._line_cells(px, py, tx, ty))  # 含起点
    if len(line) < 2:
        return []
    cells = line[1:]  # 排除自身格
    sdx = line[-1][0] - line[-2][0]
    sdy = line[-1][1] - line[-2][1]
    cx, cy = line[-1]
    steps = 1
    while steps < max_range:
        cx += sdx
        cy += sdy
        if not (0 <= cx < tm.width and 0 <= cy < tm.height):
            break
        if not tm.is_walkable(cx, cy):
            break
        cells.append((cx, cy))
        steps += 1
    return cells


# ========== 技能施放（含 AoE 副目标结算） ==========

def _cast(actor, skill, target, battle: BattleManager, tm: TileMap) -> bool:
    """施放技能（主角或伙伴）：主目标 + AoE 副目标（不耗 AP、独立结算反应）。
    返回是否成功施放。"""
    if actor.stats.ap < skill.ap_cost:
        return False
    dist = _cheb(actor.grid_pos, target.grid_pos)
    if dist > 1 and not tm.has_line_of_sight(
        actor.grid_x, actor.grid_y, target.grid_x, target.grid_y
    ):
        return False
    kwargs = dict(
        actor=actor,
        target=target,
        skill_id=skill.id,
        multiplier=skill.multiplier,
        ap_cost=skill.ap_cost,
        skill_name=skill.name,
        element=skill.element,
        apply_effect=skill.apply_effect,
        effect_duration=skill.effect_duration,
        effect_chance=skill.effect_chance,
    )
    battle.execute_action(SkillAction(**kwargs))
    # AoE 副目标（雷击直线穿透 / 火球 3×3 溅射）：独立结算（ap_cost=0），
    # 各自走元素附着/反应链（同 play_state._aoe_secondary_enemies 规则）
    if skill.aoe == "line":
        cells = set(_line_beam_cells(tm, actor.grid_pos, target.grid_pos, skill.range_cells))
    elif skill.aoe == "splash":
        cells = {
            (target.grid_x + dx, target.grid_y + dy)
            for dx in range(-config.SPLASH_RADIUS, config.SPLASH_RADIUS + 1)
            for dy in range(-config.SPLASH_RADIUS, config.SPLASH_RADIUS + 1)
        }
    else:
        cells = set()
    for e in battle.enemies:
        if e is target or e.stats.is_dead():
            continue
        if e.grid_pos in cells:
            kwargs["target"] = e
            kwargs["ap_cost"] = 0
            battle.execute_action(SkillAction(**kwargs))
    return True


def _cast_shield(player: Player, battle: BattleManager) -> bool:
    """释放护盾（1 AP，自身增益）。"""
    if player.stats.ap < 1 or player.status_effects.get(EffectType.SHIELD) is not None:
        return False
    sk = player.get_skill("shield")
    if sk is None:
        return False
    return battle.execute_action(
        SkillAction(
            player, player,
            skill_id="shield",
            multiplier=0.0,
            ap_cost=sk.ap_cost,
            skill_name="护盾",
        )
    )


# ========== 流派攻击策略 ==========

def _in_range_skills(actor, alive: list, tm: TileMap, skill_ids: list[str]):
    """射程内（含视线）可命中的 (敌人, 技能) 列表，按距离升序。
    基础攻击受武器加成：长弓 attack_range=3 → 普攻射程 1+2=3（同 play_state）。"""
    pos = actor.grid_pos
    out = []
    for e in alive:
        for sid in skill_ids:
            sk = actor.get_skill(sid)
            if sk is None:
                continue
            bonus = (actor.stats.attack_range - 1) if sid == "basic_attack" else 0
            reach = sk.range_cells + bonus
            d = _cheb(pos, e.grid_pos)
            if d <= reach and actor.stats.ap >= sk.ap_cost:
                if d <= 1 or tm.has_line_of_sight(
                    actor.grid_x, actor.grid_y, e.grid_x, e.grid_y
                ):
                    out.append((e, sk))
    return sorted(out, key=lambda t: _cheb(pos, t[0].grid_pos))


def _electro_attack(player: Player, alive: list, tm: TileMap):
    """感电流攻击决策：返回 (skill, target) 或 None。

    优先级：
    1. 射程内目标带"水/雷"附着 → 用另一元素触发感电（雷+水，×1.5 + 追加雷伤）
    2. 射程内无附着目标 → 水弹挂水（2 AP，留 AP 下回合雷击触发）
    3. 雷击选束内敌人最多的目标（穿透收益），否则最近目标保底输出
    """
    pos = player.grid_pos
    in_range = _in_range_skills(player, alive, tm, ["lightning", "water_shot"])

    # 1. 触发感电：附着水→雷击；附着雷→水弹（谁先谁后均可触发感电）
    for e, sk in in_range:
        aura = e.status_effects.aura
        if aura == Element.WATER and sk.id == "lightning":
            return sk, e
        if aura == Element.LIGHTNING and sk.id == "water_shot":
            return sk, e
    # 2. 水弹挂水（无附着目标）
    for e, sk in in_range:
        if sk.id == "water_shot" and e.status_effects.aura is None:
            return sk, e
    # 3. 雷击穿透多目标优先，否则最近目标
    best_lightning = None
    best_n = 1
    for e, sk in in_range:
        if sk.id == "lightning":
            beam = set(_line_beam_cells(tm, pos, e.grid_pos, sk.range_cells))
            n = sum(1 for x in alive if x.grid_pos in beam)
            if n > best_n:
                best_lightning, best_n = (sk, e), n
    if best_lightning is not None:
        return best_lightning
    if in_range:
        e, sk = in_range[0]
        return sk, e
    return None


def _frost_attack(player: Player, alive: list, tm: TileMap):
    """冻结控制流攻击决策：返回 (skill, target) 或 None。

    优先级：
    1. 射程内目标带"水/冰"附着 → 用另一元素触发冻结（目标跳过下一回合）
    2. 射程内无附着目标 → 水弹挂水（2 AP，下回合寒冰箭冻结）
    3. 已被冻结/眩晕的目标 → 用最高倍率技能白嫖输出
    4. 最近目标保底输出（寒冰箭倍率 1.6 更高）
    """
    pos = player.grid_pos
    in_range = _in_range_skills(player, alive, tm, ["ice_arrow", "water_shot"])

    # 1. 触发冻结：附着水→寒冰箭；附着冰→水弹（谁先谁后均可触发冻结）
    for e, sk in in_range:
        aura = e.status_effects.aura
        if aura == Element.WATER and sk.id == "ice_arrow":
            return sk, e
        if aura == Element.ICE and sk.id == "water_shot":
            return sk, e
    # 2. 水弹挂水（无附着目标）
    for e, sk in in_range:
        if sk.id == "water_shot" and e.status_effects.aura is None:
            return sk, e
    # 3. 已被冻结/眩晕 → 优先输出（罚站白嫖，用倍率高的寒冰箭）
    for e, sk in in_range:
        if e.status_effects.is_disabled() and sk.id == "ice_arrow":
            return sk, e
    # 4. 最近目标保底输出
    if in_range:
        e, sk = in_range[0]
        return sk, e
    return None


def _superconduct_attack(player: Player, alive: list, tm: TileMap):
    """超导破甲流攻击决策：返回 (skill, target) 或 None。

    优先级：
    1. 射程内目标带"冰/雷"附着 → 用另一元素触发超导（追加雷伤 + 破甲 DEF-50%）
    2. 已破甲目标 → 雷击输出（弱雷 ×1.25 + 破甲减防）
    3. 无附着目标 → 寒冰箭挂冰（1.6× + 减速；连招需 6AP，L1/L2 拆两回合）
    4. 最近目标保底输出
    """
    pos = player.grid_pos
    in_range = _in_range_skills(player, alive, tm, ["lightning", "ice_arrow"])

    # 1. 触发超导：附着冰→雷击；附着雷→寒冰箭（谁先谁后均可触发超导）
    for e, sk in in_range:
        aura = e.status_effects.aura
        if aura == Element.ICE and sk.id == "lightning":
            return sk, e
        if aura == Element.LIGHTNING and sk.id == "ice_arrow":
            return sk, e
    # 2. 已破甲 → 雷击收割（弱雷目标收益最大）
    for e, sk in in_range:
        if e.status_effects.has(EffectType.DEF_DOWN) and sk.id == "lightning":
            return sk, e
    # 3. 寒冰箭挂冰（无附着目标）
    for e, sk in in_range:
        if sk.id == "ice_arrow" and e.status_effects.aura is None:
            return sk, e
    # 4. 最近目标保底输出
    if in_range:
        e, sk = in_range[0]
        return sk, e
    return None


def _overload_attack(player: Player, alive: list, tm: TileMap):
    """超载雷爆流攻击决策：返回 (skill, target) 或 None。

    优先级：
    1. 射程内目标带"火/雷"附着 → 用另一元素触发超载（追加雷伤 + 回合末雷爆）
    2. 无附着目标 → 火苗挂火（2 AP，L1 初始自带；火苗射程 2 需近身）
    3. 雷击选束内敌人最多的目标（穿透多目标超载），否则最近保底
    """
    pos = player.grid_pos
    in_range = _in_range_skills(player, alive, tm, ["lightning", "ember"])

    # 1. 触发超载：附着火→雷击；附着雷→火苗（谁先谁后均可触发超载）
    for e, sk in in_range:
        aura = e.status_effects.aura
        if aura == Element.FIRE and sk.id == "lightning":
            return sk, e
        if aura == Element.LIGHTNING and sk.id == "ember":
            return sk, e
    # 2. 火苗挂火（无附着目标）
    for e, sk in in_range:
        if sk.id == "ember" and e.status_effects.aura is None:
            return sk, e
    # 3. 雷击穿透多目标优先，否则最近目标
    best_lightning = None
    best_n = 1
    for e, sk in in_range:
        if sk.id == "lightning":
            beam = set(_line_beam_cells(tm, pos, e.grid_pos, sk.range_cells))
            n = sum(1 for x in alive if x.grid_pos in beam)
            if n > best_n:
                best_lightning, best_n = (sk, e), n
    if best_lightning is not None:
        return best_lightning
    if in_range:
        e, sk = in_range[0]
        return sk, e
    return None


def _archer_attack(player: Player, alive: list, tm: TileMap):
    """长弓放风流攻击决策：纯普攻（射程 3），最近目标保底输出。"""
    in_range = _in_range_skills(player, alive, tm, ["basic_attack"])
    if in_range:
        e, sk = in_range[0]
        return sk, e
    return None


def _companion_turn(companion: Companion, player: Player, alive: list, battle, tm) -> None:
    """伙伴阶段：嘲讽最近敌人（0AP）→ 反击姿态（1AP）→ 朝敌人移动挡前排。
    伙伴独立 2AP，不消耗主角 AP。"""
    alive = [e for e in alive if not e.stats.is_dead()]
    if not alive or companion.stats.is_dead():
        return
    # 1. 嘲讽（0AP，3 格，每回合限 1 次；强制敌人 2 回合内攻击伙伴）
    taunt = companion.get_skill("taunt")
    if taunt is not None and not companion.taunt_used_this_turn:
        for e in sorted(alive, key=lambda x: _cheb(companion.grid_pos, x.grid_pos)):
            if _cheb(companion.grid_pos, e.grid_pos) <= taunt.range_cells:
                _cast(companion, taunt, e, battle, tm)
                break
    # 2. 反击姿态（1AP）：本回合受近战攻击自动反击 50%
    counter = companion.get_skill("counter_stance")
    if (
        counter is not None
        and companion.stats.ap >= 1
        and not companion.counter_stance_active
    ):
        _cast(companion, counter, companion, battle, tm)
    # 3. 朝最近敌人移动（挡前排，吸引火力）
    if companion.stats.ap >= 1:
        focus = min(alive, key=lambda e: (_cheb(companion.grid_pos, e.grid_pos), e.stats.hp))
        blocked = {e.grid_pos for e in alive}
        path = _bfs_path(tm, companion.grid_pos, focus.grid_pos, blocked)
        if path:
            steps = path[: companion.stats.move_range]
            if steps[-1] == focus.grid_pos:
                steps = steps[:-1] if len(steps) > 1 else []
            if steps:
                battle.execute_action(MoveAction(companion, Vector2(*steps[-1]), ap_cost=1))


def _melt_attack(player: Player, alive: list, tm: TileMap):
    """融化蒸发流攻击决策：返回 (skill, target) 或 None。

    优先级：
    1. 射程内目标带"冰/水"附着 → 火球触发融化（受击×1.25）/蒸发（×1.5）
    2. 带"火"附着目标 → 寒冰箭/水弹触发反应
    3. 无附着目标 → 寒冰箭挂冰（1.6× + 减速，为火球溅射融化铺路）
    4. 火球选溅射覆盖最多目标
    5. 最近目标保底输出
    """
    pos = player.grid_pos
    in_range = _in_range_skills(player, alive, tm, ["fireball", "ice_arrow", "water_shot"])

    # 1. 触发反应：冰/水附着 → 火球；火附着 → 寒冰箭/水弹
    for e, sk in in_range:
        aura = e.status_effects.aura
        if aura in (Element.ICE, Element.WATER) and sk.id == "fireball":
            return sk, e
        if aura == Element.FIRE and sk.id in ("ice_arrow", "water_shot"):
            return sk, e
    # 2. 寒冰箭挂冰（无附着目标）
    for e, sk in in_range:
        if sk.id == "ice_arrow" and e.status_effects.aura is None:
            return sk, e
    # 3. 火球溅射覆盖最多目标
    best_fb = None
    best_n = 1
    for e, sk in in_range:
        if sk.id == "fireball":
            cells = {
                (e.grid_x + dx, e.grid_y + dy)
                for dx in range(-config.SPLASH_RADIUS, config.SPLASH_RADIUS + 1)
                for dy in range(-config.SPLASH_RADIUS, config.SPLASH_RADIUS + 1)
            }
            n = sum(1 for x in alive if x.grid_pos in cells)
            if n > best_n:
                best_fb, best_n = (sk, e), n
    if best_fb is not None:
        return best_fb
    # 4. 最近目标保底输出
    if in_range:
        e, sk = in_range[0]
        return sk, e
    return None


def _run_battle(level: int, room_type: str, kit: Kit, seed: int, debug: bool = False) -> dict:
    """模拟一场感电流战斗（真实房间地形），返回统计。"""
    tm, w, h = _room_field(level, room_type, seed)
    player, potions = _make_player(kit, h)
    enemies = _make_enemies(room_type, level, w, h)
    companions = [_make_companion(w, h)] if kit.companion else []
    battle = BattleManager(player, enemies, tm, companions=companions)

    attack_fn = kit.attack or _electro_attack  # 攻击决策策略（未指定默认感电流）
    hp_start = player.stats.hp
    healed = 0
    potions_used = 0
    turns = 0

    while not battle.is_over and turns < 80:
        turns += 1
        # ---- 玩家回合（感电连招 + 打带跑） ----
        guard = 0
        while not battle.is_over:
            guard += 1
            if guard > 50:
                print(f"\nWARN: 玩家回合循环 guard 触发 L{level} {room_type} seed={seed} "
                      f"ap={player.stats.ap} hp={player.stats.hp} pos={player.grid_pos}")
                break
            alive = [e for e in battle.enemies if not e.stats.is_dead()]
            if not alive:
                break
            # 伙伴阶段：当前受控实体是伙伴 → 嘲讽/反击/挡前排，再切回主角
            actor = battle.current_actor
            if actor is not player:
                if getattr(actor, "alive", True):
                    _companion_turn(actor, player, alive, battle, tm)
                if not battle.switch_actor(player):
                    break
                continue
            pos = player.grid_pos
            if player.status_effects.is_disabled():
                break
            # 1. 低血喝药（1 AP）
            if (
                potions
                and player.stats.hp <= player.stats.max_hp // 2
                and player.stats.ap >= 1
            ):
                hp_before = player.stats.hp
                potions.pop().use(player)
                player.stats.spend_ap(1)
                healed += player.stats.hp - hp_before
                potions_used += 1
                continue
            # 2. 护盾（低血 或 当前安全 时）
            safe_now = min(_threat(e, pos, tm) for e in alive) > 0
            if (
                player.get_skill("shield") is not None
                and player.stats.ap >= 2
                and player.status_effects.get(EffectType.SHIELD) is None
                and (player.stats.hp <= player.stats.max_hp // 2 or safe_now)
            ):
                if _cast_shield(player, battle):
                    continue
            # 3. 流派连招攻击
            pick = attack_fn(player, alive, tm)
            if pick is not None:
                sk, target = pick
                if debug:
                    aura = target.status_effects.aura
                    print(f"  T{turns} {sk.name}→{type(target).__name__} "
                          f"aura={aura} dist={_cheb(pos, target.grid_pos)} "
                          f"hp={target.stats.hp} ap={player.stats.ap}")
                _cast(player, sk, target, battle, tm)
                alive = [e for e in battle.enemies if not e.stats.is_dead()]
                if not alive:
                    break
                # 打完立即评估：危险且还有 AP → 先撤一步保命
                pos = player.grid_pos
                if min(_threat(e, pos, tm) for e in alive) <= 0 and player.stats.ap >= 1:
                    blocked = {e.grid_pos for e in alive}
                    cands = _reachable(tm, pos, blocked, player.stats.move_range)
                    if cands:
                        spot = max(
                            cands,
                            key=lambda t: (
                                min(_threat(e, t, tm) for e in alive),
                                -_cheb(t, pos),
                            ),
                        )
                        if spot != pos:
                            battle.execute_action(MoveAction(player, Vector2(*spot), ap_cost=1))
                continue
            # 4. 危险且打不到 → 撤退
            blocked = {e.grid_pos for e in alive}
            if min(_threat(e, pos, tm) for e in alive) <= 0 and player.stats.ap >= 1:
                cands = _reachable(tm, pos, blocked, player.stats.move_range)
                if cands:
                    spot = max(
                        cands,
                        key=lambda t: (
                            min(_threat(e, t, tm) for e in alive),
                            -_cheb(t, pos),
                        ),
                    )
                    if spot != pos:
                        battle.execute_action(MoveAction(player, Vector2(*spot), ap_cost=1))
                        continue
                break  # 无路可退 → 硬抗
            # 5. 打不到（距离远 或 视线被障碍柱挡）→ 朝最近敌人移动。
            #    注意不能用 dist > max_range 作条件：射程内但视线被挡同样打不到，
            #    不移动就会卡死（双方满血对峙 80 回合）。
            focus = min(alive, key=lambda e: (_cheb(pos, e.grid_pos), e.stats.hp))
            if player.stats.ap >= 1:
                path = _bfs_path(tm, pos, focus.grid_pos, blocked)
                if path:
                    steps = path[: player.stats.move_range]
                    if steps[-1] == focus.grid_pos:
                        steps = steps[:-1] if len(steps) > 1 else []
                    if steps:
                        battle.execute_action(MoveAction(player, Vector2(*steps[-1]), ap_cost=1))
                        continue
            break  # 无事可做 → 结束回合
        # ---- 手动结束回合 ----
        if not battle.is_over:
            battle.end_player_turn()
            guard = 0
            while battle.is_enemy_turn and not battle.is_over and guard < 200:
                battle.step_enemy_turn()
                guard += 1
            if debug:
                alive_s = " ".join(
                    f"{type(e).__name__}{e.grid_pos}={e.stats.hp}"
                    for e in battle.enemies if not e.stats.is_dead()
                )
                print(f"  ==T{turns}末== 玩家{player.grid_pos} hp={player.stats.hp} ap={player.stats.ap} | {alive_s}")

    damage_taken = (hp_start - player.stats.hp) + healed
    return {
        "won": battle.phase.name == "BATTLE_WON",
        "damage": damage_taken,
        "turns": turns,
        "potions": potions_used,
    }


# ========== 聚合与报告 ==========

def run_scenario(level: int, room_type: str, kit: Kit, n: int) -> dict:
    """跑 n 场同配置战斗，返回聚合统计。"""
    wins, dmg, turns, pots = 0, [], [], 0
    step = max(1, n // 10)
    for i in range(n):
        r = _run_battle(level, room_type, kit, seed=1000 * level + i)
        wins += r["won"]
        dmg.append(r["damage"])
        turns.append(r["turns"])
        pots += r["potions"]
        if (i + 1) % step == 0:
            print(f"\r  {room_type}: {i+1}/{n}", end="", flush=True)
    print()
    dmg_sorted = sorted(dmg)
    return {
        "win_rate": wins / n,
        "avg_damage": sum(dmg) / n,
        "p90_damage": dmg_sorted[int(n * 0.9)],
        "avg_turns": sum(turns) / n,
        "avg_potions": pots / n,
    }


def run_report(kit_name: str = "electro", n: int = 200) -> str:
    """跑指定流派的 L1~L3 全套房间，输出难度报告文本。"""
    factory = KITS[kit_name]
    lines = [
        f"=== 流派模拟报告：{kit_name}（每场景 {n} 场，真实房间地形，含打带跑） ===",
        "",
    ]
    for level in (1, 2, 3):
        kit = factory(level)
        lines.append(f"— {kit.label} AP={kit.max_ap} 药水×{kit.potions} —")
        floor_damage = 0.0
        for room, count in (("battle", 2), ("elite", 1), ("boss", 1)):
            print(f"  跑 L{level} {room}×{count} ...", flush=True)
            r = run_scenario(level, room, kit, n)
            floor_damage += r["avg_damage"] * count
            win = f"{r['win_rate']*100:.0f}%"
            lines.append(
                f"  {room:<6}×{count}  胜率 {win:>4}  "
                f"均承受 {r['avg_damage']:6.1f} HP (p90 {r['p90_damage']:3})  "
                f"均 {r['avg_turns']:4.1f} 回合  用药 {r['avg_potions']:.2f}"
            )
        budget = 20 + 10 + kit.potions * 15  # 初始HP + 休息回血 + 药水
        lines.append(
            f"  全层预计承受 {floor_damage:.0f} HP vs 资源 {budget} HP "
            f"(初始20+休息10+药水{kit.potions*15})"
            + ("  << 缺口!" if floor_damage > budget else "  OK")
        )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    kit_name = sys.argv[1] if len(sys.argv) > 1 else "electro"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    if kit_name not in KITS:
        print(f"未知流派 {kit_name}，可用: {', '.join(KITS)}")
        sys.exit(1)
    print(run_report(kit_name, n), flush=True)
