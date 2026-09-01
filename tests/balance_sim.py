"""
数值平衡模拟器（无头蒙特卡洛）。

功能说明：
    用真实的战斗系统（BattleManager + 行为树 AI + 伤害公式 + 真实房间
    地形/障碍柱）做大批量无头战斗模拟，量化每层每类房间的战斗压力，
    用于数值平衡验证。

模拟规则：
    - 战场 = 真实 Floor 生成的对应类型房间（含随机障碍柱，含边界墙）
    - 玩家策略（贪心 + 打带跑，构筑含初始技能火苗术/护盾）：
        1. 血量≤50% 且有药水 → 喝药
        1.5 血量≤50% 且无护盾 → 放护盾（1 AP，吸收 6 伤持续 2 回合）
        2. 攻击范围内有敌人 → 用可负担的最高倍率技能打最近敌人
           （若处于危险距离，保留 1 AP 用于撤退，或攻击可直接击杀的目标）
        3. 有敌人下回合能够到自己 → 撤退到"距离余量"最大的格子
        4. 否则朝最近敌人移动（1 AP 最多 move_range 格）
    - 火球 3×3 溅射按单体计（略低估玩家输出），装备掉落不计（纯基础数值）

运行方式：
    python tests/balance_sim.py [N]     # N=每个场景模拟场次，默认 300
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

from src.combat.action import AttackAction, MoveAction, SkillAction  # noqa: E402
from src.combat.status_effect import EffectType  # noqa: E402
from src.combat.battle_manager import BattleManager  # noqa: E402
from src.entities.player import Player, get_skill_pool  # noqa: E402
from src.entities.enemies.slime import Slime  # noqa: E402
from src.entities.enemies.skeleton import Skeleton  # noqa: E402
from src.entities.enemies.elite import Elite  # noqa: E402
from src.entities.enemies.boss import Boss  # noqa: E402
from src.items.potion import HealthPotion  # noqa: E402
from src.utils.vector import Vector2  # noqa: E402
from src.world.floor import Floor  # noqa: E402
from src.world.room import RoomType  # noqa: E402
from src.world.tilemap import TileMap, TileType  # noqa: E402


# ========== 玩家配置（对应用户实测的成长路线） ==========

@dataclass
class Kit:
    """一层的玩家构筑：技能 id 列表 / AP 上限 / 携带药水数。"""
    label: str
    skills: list[str]
    max_ap: int
    potions: int


# 真实构筑：L1 初始 = 基础攻击+火苗术+护盾，休息房学冲锋斩；
# L2/L3 习得火球术后火苗术被替换（见 player.learn_skill 的 fireball 特判）。
KITS: dict[int, Kit] = {
    1: Kit("初始3技能+冲锋斩", ["basic_attack", "ember", "shield", "charge_slash"], 5, 1),
    2: Kit("L1+火球(替换火苗)", ["basic_attack", "shield", "charge_slash", "fireball"], 5, 2),
    3: Kit("同 L2 + 精力充沛(AP+1)", ["basic_attack", "shield", "charge_slash", "fireball"], 6, 2),
}

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
            tile = floor.tilemap.get_tile(room.x1 + gx, room.y1 + gy)
            tm.set_tile(gx, gy, tile)
    return tm, w, h


def _make_player(kit: Kit, field_h: int) -> tuple[Player, list]:
    """按构筑创建玩家（出生在房间左缘中部）；返回 (玩家, 药水列表)。"""
    p = Player(position=Vector2(1, field_h // 2))
    pool = {s.id: s for s in get_skill_pool()}
    p.skills = [pool[sid] for sid in kit.skills]
    p.stats.max_ap = kit.max_ap
    p.stats.ap = kit.max_ap
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
    """
    敌人对玩家的威胁值（越小越危险，999=安全）。
    远程（骷髅/精英阶段1、2）：移动后能进入射程(4) 且目标可见（障碍柱挡箭）。
    近战：移动 + 攻击距离（Boss 阶段3 AOE 射程 3，其余贴脸 1）。
    """
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


def _run_battle(level: int, room_type: str, kit: Kit, seed: int, debug: bool = False) -> dict:
    """模拟一场战斗（真实房间地形），返回统计。"""
    tm, w, h = _room_field(level, room_type, seed)
    player, potions = _make_player(kit, h)
    enemies = _make_enemies(room_type, level, w, h)
    battle = BattleManager(player, enemies, tm)

    hp_start = player.stats.hp
    healed = 0
    potions_used = 0
    turns = 0
    if debug:
        boss = enemies[0]
        print(f"== seed={seed} room_type={room_type} kit={kit.label} ==")

    while not battle.is_over and turns < 80:
        turns += 1
        # ---- 玩家回合（贪心 + hit&run：打完就撤，安全可连发） ----
        guard = 0
        while not battle.is_over:
            guard += 1
            if guard > 50:  # 防御兜底：理论上每个分支都耗 AP 或 break，不该触发
                print(f"\nWARN: 玩家回合循环 guard 触发 L{level} {room_type} seed={seed} "
                      f"ap={player.stats.ap} hp={player.stats.hp} pos={player.grid_pos}")
                break
            alive = [e for e in battle.enemies if not e.stats.is_dead()]
            if not alive:
                break
            pos = player.grid_pos
            # 0. 被冻结/眩晕 → 本回合无法行动，直接结束回合
            #    （否则 execute_action 因 is_disabled 失败不扣 AP，各分支 continue 造成死循环）
            if player.status_effects.is_disabled():
                break
            # 1. 血量≤50% 且有药水 → 喝药（1 AP）
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
            # 1.5 放护盾（1 AP，自身增益）：仅当"放完仍留 1 AP"且
            # （低血 或 当前安全无人能威胁到），避免抢占撤退/输出的关键 AP。
            shield_sk = player.get_skill("shield")
            safe_now = min(_threat(e, pos, tm) for e in alive) > 0
            if (
                shield_sk is not None
                and player.stats.ap >= shield_sk.ap_cost + 1
                and player.status_effects.get(EffectType.SHIELD) is None
                and (player.stats.hp <= player.stats.max_hp // 2 or safe_now)
            ):
                battle.execute_action(
                    SkillAction(
                        player, player,
                        skill_id="shield",
                        multiplier=0.0,
                        ap_cost=shield_sk.ap_cost,
                        skill_name="护盾",
                    )
                )
                continue
            # 2. 集火最近（同距离血少）的敌人
            focus = min(alive, key=lambda e: (_cheb(pos, e.grid_pos), e.stats.hp))
            dist = _cheb(pos, focus.grid_pos)
            # 3. 射程内 → 攻击（用可负担的最高倍率技能）
            best = None
            for sk in player.skills:
                if dist > sk.range_cells or player.stats.ap < sk.ap_cost:
                    continue
                if best is None or sk.multiplier > best.multiplier:
                    best = sk
            if best is not None:
                battle.execute_action(
                    AttackAction(
                        player, focus,
                        ap_cost=best.ap_cost,
                        multiplier=best.multiplier,
                        skill_name=best.name,
                    )
                )
                if debug:
                    print(f"  T{turns} 攻击({best.name}) @{player.grid_pos} dist={dist} "
                          f"bossHP={focus.stats.hp} ap={player.stats.ap}")
                # 打完立即评估：危险且还有 AP → 先撤一步保命
                alive = [e for e in battle.enemies if not e.stats.is_dead()]
                if not alive:
                    break
                pos = player.grid_pos
                if min(_threat(e, pos, tm) for e in alive) <= 0 and player.stats.ap >= 1:
                    blocked = {e.grid_pos for e in alive}
                    cands = _reachable(tm, pos, blocked, player.stats.move_range)
                    if cands:
                        spot = max(
                            cands,
                            key=lambda t: (
                                min(_threat(e, t, tm) for e in alive),
                                -_cheb(t, focus.grid_pos),
                            ),
                        )
                        if spot != pos:
                            battle.execute_action(MoveAction(player, Vector2(*spot), ap_cost=1))
                continue
            # 4. 射程外且危险 → 撤退（拉开距离/躲视线）
            blocked = {e.grid_pos for e in alive}
            if min(_threat(e, pos, tm) for e in alive) <= 0 and player.stats.ap >= 1:
                cands = _reachable(tm, pos, blocked, player.stats.move_range)
                if cands:
                    spot = max(
                        cands,
                        key=lambda t: (
                            min(_threat(e, t, tm) for e in alive),
                            -_cheb(t, focus.grid_pos),
                        ),
                    )
                    if spot != pos:
                        battle.execute_action(MoveAction(player, Vector2(*spot), ap_cost=1))
                        continue
                break  # 无路可退 → 只能结束回合硬抗
            # 5. 射程外且安全 → 朝集火目标移动（1 AP 最多 move_range 格）
            if player.stats.ap >= 1 and dist > best_range(player):
                path = _bfs_path(tm, pos, focus.grid_pos, blocked)
                if path:
                    steps = path[: player.stats.move_range]
                    if steps[-1] == focus.grid_pos:
                        steps = steps[:-1] if len(steps) > 1 else []
                    if steps:
                        battle.execute_action(MoveAction(player, Vector2(*steps[-1]), ap_cost=1))
                        continue
            break  # 无事可做 → 结束回合
        # ---- 手动结束回合（与真实操作一致） ----
        if not battle.is_over:
            battle.end_player_turn()
            guard = 0
            while battle.is_enemy_turn and not battle.is_over and guard < 200:
                battle.step_enemy_turn()
                guard += 1
            # 敌人回合结束由 _start_player_turn 自动重置 AP/状态

    damage_taken = (hp_start - player.stats.hp) + healed
    return {
        "won": battle.phase.name == "BATTLE_WON",
        "damage": damage_taken,
        "turns": turns,
        "potions": potions_used,
    }


def best_range(player: Player) -> int:
    """玩家当前技能池的最大射程。"""
    return max(sk.range_cells for sk in player.skills)


def run_scenario(level: int, room_type: str, kit: Kit, n: int) -> dict:
    """跑 n 场同配置战斗，返回聚合统计（每 10% 打印进度，避免无输出假死）。"""
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


def run_report(n: int = 300, kits: dict | None = None) -> str:
    """跑全套场景，输出楼层难度报告文本。"""
    kits = kits or KITS
    lines = [f"=== 数值平衡模拟报告（每场景 {n} 场，真实房间地形，含打带跑） ===", ""]
    for level in sorted(kits):
        kit = kits[level]
        lines.append(f"— 第 {level} 层 [{kit.label}] AP={kit.max_ap} 药水×{kit.potions} —")
        floor_damage = 0.0
        for room, count in (("battle", 2), ("elite", 1), ("boss", 1)):
            print(f"  跑 {room}×{count} ...", flush=True)
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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    print(run_report(n), flush=True)
