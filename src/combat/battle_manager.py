"""
回合制战斗管理器模块。

功能说明：
    战斗系统的核心调度器。维护战斗参与者、当前回合方、行动队列。
    每次玩家执行行动时，先校验 AP 是否足够，扣除后执行；
    AP 耗尽仅提示，由玩家点击结束回合后才切换到敌人回合。
    Day 4：敌人回合为占位（什么都不做立即切回玩家回合）。
    Day 6：接入行为树，敌人回合调用 AI.tick() 执行行动。

回合状态机（PRD 第 4.3 节）：
    PLAYER_TURN → (EndTurn) → ENEMY_TURN → (AI 完成) → PLAYER_TURN
"""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, cast

from src.combat.action import Action, EndTurnAction, SkillAction
from src.combat.status_effect import EffectType
from src.entities.entity import Entity

if TYPE_CHECKING:
    from src.entities.companion import Companion
    from src.entities.player import Player
    from src.world.tilemap import TileMap


class TurnPhase(Enum):
    """回合阶段。"""
    PLAYER_TURN = auto()   # 玩家行动中
    ENEMY_TURN = auto()    # 敌人行动中
    BATTLE_WON = auto()    # 玩家胜
    BATTLE_LOST = auto()   # 玩家败


class BattleManager:
    """战斗调度器。一场战斗一个实例。"""

    def __init__(
        self,
        player: "Player",
        enemies: list[Entity],
        tilemap: "TileMap",
        companions: "list[Companion] | None" = None,
    ):
        self.player = player
        # 友方单位列表（玩家 + 伙伴们）：回合 AP 重置、状态结算、受控切换、
        # UI 头像栏全部按此列表驱动——未来新增同类角色只需传入列表即可。
        # 死亡伙伴保留引用（alive=False）供头像栏灰化显示。
        self.allies: list[Entity] = [player]
        if companions:
            self.allies.extend(companions)
        self.current_actor: Entity = player
        self.enemies: list[Entity] = enemies
        self.tilemap = tilemap

        # 回合状态
        self.phase: TurnPhase = TurnPhase.PLAYER_TURN
        self.turn_count: int = 1  # 第几回合（双方各动一次算 1 回合）
        self.current_enemy_index: int = 0  # 敌人回合当前轮到的敌人下标

        # 最近一次行动描述（供 HUD 显示反馈）
        self.last_action_desc: str = ""
        # 最近一次状态处理日志（回合开始/结束产生，供 HUD 显示）
        self.last_status_logs: list[str] = []
        # Day 5：最近一次伤害结果与目标（供 UI 生成飘字）
        self.last_damage_result = None
        self.last_damage_target = None
        # 反击姿态触发的反击结果与目标（与主伤害分离，UI 可同时显示两个飘字）
        self.last_counter_result = None
        self.last_counter_target = None
        # 守护光环：伙伴存活时主角每回合首次受伤 -2（伙伴被动，见 damage.apply_damage）
        self.player.guardian_halo_active = self.companion is not None and self.companion.alive
        self.player.guardian_halo_used = False


        # ========== 受控实体与友方单位 ==========

    @property
    def friendly_entities(self) -> list[Entity]:
        """存活友方单位列表（玩家 + 存活的伙伴们）。敌人 AI 目标选择、回合结算用。"""
        return [a for a in self.allies if a.alive]

    @property
    def companion(self) -> "Companion | None":
        """首个伙伴（兼容现有引用）。返回列表里第一个非玩家单位；
        若将来需要按角色类型区分，可在此按类型过滤。"""
        for a in self.allies:
            if a is not self.player:
                return cast("Companion", a)
        return None

    def attack_target(self, enemy: Entity) -> Entity:
        """
        敌人 AI 的当前攻击目标（仇恨系统，阶段 4）。
        敌人带"嘲讽"状态且伙伴存活 → 强制以伙伴为目标；否则以玩家为目标。
        伙伴死亡后嘲讽失效，自动回退打玩家。
        """
        if enemy.status_effects.has(EffectType.TAUNT):
            if self.companion is not None and self.companion.alive:
                return self.companion
        return self.player

    def switch_actor(self, actor: Entity) -> bool:
        """
        切换当前受控实体（主角 ↔ 伙伴）。
        仅玩家回合、且目标为存活友方单位时成功，否则返回 False。
        """
        if self.phase != TurnPhase.PLAYER_TURN:
            return False
        if actor not in self.allies:
            return False
        if actor is not self.player and not actor.alive:
            return False
        self.current_actor = actor
        return True


    # ========== 玩家行动接口 ==========
    def can_execute(self, action: Action) -> bool:
        """检查当前能否执行行动：玩家回合 + AP 足够 + 受控实体未被冻结/眩晕。"""
        if self.phase != TurnPhase.PLAYER_TURN:
            return False
        # 冻结/眩晕：本回合不能行动（结束回合除外）——判断当前受控实体
        if self.current_actor.status_effects.is_disabled() and not isinstance(action, EndTurnAction):
            return False
        # 嘲讽每回合限 1 次（0 AP 免费技能，防止无限嘲讽刷仇恨；非伙伴实体无此字段）
        if (
            isinstance(action, SkillAction)
            and action.skill_id == "taunt"
            and getattr(self.current_actor, "taunt_used_this_turn", False)
        ):
            return False
        # 独立 AP 池：按当前受控实体各自 stats 扣费（伙伴每回合固定 2 点）
        return self.current_actor.stats.ap >= action.ap_cost

    def execute_action(self, action: Action) -> bool:
        """
        执行一个玩家行动。AP 不足或非玩家回合返回 False。
        执行后检查胜负与回合结束条件。
        独立 AP 池：扣 AP 按当前受控实体各自 stats 扣除（伙伴 2 点/回合，不消耗主角）。
        """
        if not self.can_execute(action):
            return False

        # 扣 AP（EndTurnAction cost=0 也会进入这里）
        self.current_actor.stats.spend_ap(action.ap_cost)
        # 执行行动效果
        action.execute(self)
        # 行动可能造成友方单位阵亡（AoE 溅射等）：标记死亡并切回主角
        self._handle_ally_death()

        # 执行后检查胜负
        if self._check_player_won():
            self.phase = TurnPhase.BATTLE_WON
            return True

        # 仅玩家主动结束回合才切换到敌人回合；AP 耗尽后留在玩家回合，
        # 由玩家手动点击结束（UI 层据此提示"AP已耗尽"）
        if isinstance(action, EndTurnAction):
            # 玩家回合结束：所有存活友方单位结算回合末状态（冻结/眩晕等时长递减）
            for a in self.friendly_entities:
                a.status_effects.on_turn_end(a)
            self._start_enemy_turn()
        elif self.current_actor.stats.ap <= 0:
            # 当前受控实体 AP 归零：提示手动结束回合（可 Tab 切到其他友方继续行动）
            self.last_action_desc = "AP已耗尽，请手动结束回合"

        return True

    # ========== 敌人行动接口 ==========

    def execute_enemy_action(self, actor: Entity, action: Action) -> bool:
        """
        敌人执行行动。绕过玩家回合检查，用敌人自己的 AP。
        """
        if self.phase != TurnPhase.ENEMY_TURN:
            return False
        if actor.stats.ap < action.ap_cost:
            return False
        actor.stats.spend_ap(action.ap_cost)
        action.execute(self)
        # 敌人行动可能击倒友方单位：标记死亡，后续敌人不再以尸体为目标
        self._handle_ally_death()
        return True

    def _handle_ally_death(self) -> None:
        """友方单位 HP 归零：标记 alive=False（AI 目标选择/受控切换据此排除，
        头像栏保留灰化显示）。若当前受控实体阵亡则切回主角。
        伙伴死亡本局永久消失由 play_state 层处理。"""
        for a in self.allies:
            if a is not self.player and a.alive and a.stats.is_dead():
                a.alive = False
                if self.current_actor is a:
                    self.current_actor = self.player
        # 伙伴全部阵亡 → 守护光环失效（伙伴存活时主角每回合首次受伤才 -2）
        if not any(a is not self.player and a.alive for a in self.allies):
            self.player.guardian_halo_active = False

    def end_player_turn(self) -> None:
        """玩家主动结束回合。"""
        if self.phase == TurnPhase.PLAYER_TURN:
            self.execute_action(EndTurnAction(self.player))

    # ========== 敌人回合（Day 6 接入 AI） ==========

    def _reset_ap_with_slow(self, entity: Entity) -> None:
        """重置 AP；若带减速状态则上限 -1（寒冰箭等附加效果）。"""
        entity.stats.reset_ap()
        if entity.status_effects.has(EffectType.SLOW):
            entity.stats.ap = max(0, entity.stats.ap - 1)

    def _start_enemy_turn(self) -> None:
        """切换到敌人回合：重置 AP、附着计时、处理敌人回合开始状态。"""
        self.phase = TurnPhase.ENEMY_TURN
        self.current_enemy_index = 0
        for enemy in self.enemies:
            if enemy.stats.is_dead():
                continue
            self._reset_ap_with_slow(enemy)
            # 重置"本回合已攻击"标志（AI 移动节点据此避免攻击后走位）
            enemy.attacked_this_turn = False
            # 附着持续计时 + 回合开始状态处理
            enemy.status_effects.tick_aura()
            logs = enemy.status_effects.on_turn_start(enemy)
            if logs:
                self.last_status_logs += logs

    def step_enemy_turn(self) -> None:
        """
        推进敌人回合一个"tick"：让当前敌人执行一次 AI tick。
        敌人 AP 归零或行为树返回 FAILURE 后轮到下一个敌人，
        全部敌人行动完毕则切回玩家回合。
        """
        # 过滤掉已死亡/被冻结眩晕的敌人
        while self.current_enemy_index < len(self.enemies):
            enemy = self.enemies[self.current_enemy_index]
            if enemy.stats.is_dead():
                self.current_enemy_index += 1
                continue
            # AP 不足（< 1）或无行为树或冻结/眩晕 → 轮到下一个
            if (
                enemy.stats.ap < 1
                or enemy.behavior_tree is None
                or enemy.status_effects.is_disabled()
            ):
                self.current_enemy_index += 1
                continue
            # 执行一次 AI tick
            status = enemy.take_ai_turn(self)
            # 检查玩家是否死亡
            if self.is_player_dead():
                self.phase = TurnPhase.BATTLE_LOST
                return
            # status 为 None 或 FAILURE → 轮到下一个敌人
            if status is None or status.name == "FAILURE" or enemy.stats.ap < 1:
                self.current_enemy_index += 1
                continue
            # 本次 tick 成功消耗 AP，下一帧再继续此敌人
            return
        # 所有敌人行动完毕
        self._start_player_turn()

    def _start_player_turn(self) -> None:
        """切换到玩家回合：敌人状态结算、重置 AP、回合计数 +1。"""
        self.phase = TurnPhase.PLAYER_TURN
        self.turn_count += 1
        # 敌人回合结束：敌人状态时长 -1（冻结/感电/破甲等）
        for enemy in self.enemies:
            if not enemy.stats.is_dead():
                enemy.status_effects.on_turn_end(enemy)
        # 玩家回合开始：所有存活友方单位各自结算状态并重置独立 AP 池
        # （玩家 5 点，伙伴 2 点；减速时上限 -1）
        self.last_status_logs = []
        for a in self.friendly_entities:
            a.status_effects.tick_aura()
            logs = a.status_effects.on_turn_start(a)
            if logs:
                self.last_status_logs += logs
            self._reset_ap_with_slow(a)
            # 伙伴回合标记：嘲讽每回合限 1 次、反击姿态仅本回合有效
            if hasattr(a, "taunt_used_this_turn"):
                setattr(a, "taunt_used_this_turn", False)
            if hasattr(a, "counter_stance_active"):
                setattr(a, "counter_stance_active", False)
        # 守护光环：每回合重置"首次受伤"标记，并在伙伴存活时激活
        self.player.guardian_halo_used = False
        self.player.guardian_halo_active = any(
            a is not self.player and a.alive for a in self.allies
        )

    # ========== 胜负判定 ==========

    def _check_player_won(self) -> bool:
        """所有敌人死亡 → 玩家胜。"""
        return all(e.stats.is_dead() for e in self.enemies) if self.enemies else False

    def is_player_dead(self) -> bool:
        """玩家死亡 → 玩家败。"""
        return self.player.stats.is_dead()

    # ========== 状态查询 ==========

    @property
    def is_player_turn(self) -> bool:
        return self.phase == TurnPhase.PLAYER_TURN

    @property
    def is_enemy_turn(self) -> bool:
        return self.phase == TurnPhase.ENEMY_TURN

    @property
    def is_over(self) -> bool:
        return self.phase in (TurnPhase.BATTLE_WON, TurnPhase.BATTLE_LOST)
