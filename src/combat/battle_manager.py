"""
回合制战斗管理器模块。

功能说明：
    战斗系统的核心调度器。维护战斗参与者、当前回合方、行动队列。
    每次玩家执行行动时，先校验 AP 是否足够，扣除后执行；
    AP 归零或玩家点击结束回合，自动切换到敌人回合。
    Day 4：敌人回合为占位（什么都不做立即切回玩家回合）。
    Day 6：接入行为树，敌人回合调用 AI.tick() 执行行动。

回合状态机（PRD 第 4.3 节）：
    PLAYER_TURN → (AP=0 或 EndTurn) → ENEMY_TURN → (AI 完成) → PLAYER_TURN
"""
from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

from src.combat.action import Action, EndTurnAction
from src.entities.entity import Entity

if TYPE_CHECKING:
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
    ):
        self.player = player
        self.enemies: list[Entity] = enemies
        self.tilemap = tilemap

        # 回合状态
        self.phase: TurnPhase = TurnPhase.PLAYER_TURN
        self.turn_count: int = 1  # 第几回合（双方各动一次算 1 回合）
        self.current_enemy_index: int = 0  # 敌人回合当前轮到的敌人下标

        # 最近一次行动描述（供 HUD 显示反馈）
        self.last_action_desc: str = ""

    # ========== 玩家行动接口 ==========

    def can_execute(self, action: Action) -> bool:
        """检查当前能否执行行动：玩家回合 + AP 足够。"""
        if self.phase != TurnPhase.PLAYER_TURN:
            return False
        return self.player.stats.ap >= action.ap_cost

    def execute_action(self, action: Action) -> bool:
        """
        执行一个玩家行动。AP 不足或非玩家回合返回 False。
        执行后检查胜负与回合结束条件。
        """
        if not self.can_execute(action):
            return False

        # 扣 AP（EndTurnAction cost=0 也会进入这里）
        self.player.stats.spend_ap(action.ap_cost)
        # 执行行动效果
        action.execute(self)

        # 执行后检查胜负
        if self._check_player_won():
            self.phase = TurnPhase.BATTLE_WON
            return True

        # AP 归零或玩家主动结束回合 → 切到敌人回合
        if isinstance(action, EndTurnAction) or self.player.stats.ap <= 0:
            self._start_enemy_turn()

        return True

    def end_player_turn(self) -> None:
        """玩家主动结束回合。"""
        if self.phase == TurnPhase.PLAYER_TURN:
            self.execute_action(EndTurnAction(self.player))

    # ========== 敌人回合（Day 6 接入 AI） ==========

    def _start_enemy_turn(self) -> None:
        """切换到敌人回合。"""
        self.phase = TurnPhase.ENEMY_TURN
        self.current_enemy_index = 0
        # 重置所有敌人 AP（Day 6 AI 用）
        for enemy in self.enemies:
            enemy.stats.reset_ap()

    def step_enemy_turn(self) -> None:
        """
        推进敌人回合一个"tick"。
        Day 4：空实现，直接切回玩家回合。
        Day 6：调用当前敌人的 AI.tick()，AI 返回行动则执行，
              当前敌人 AP 归零后轮到下一个敌人，全部动完切回玩家回合。
        """
        # Day 4 占位：立即结束敌人回合
        self._start_player_turn()

    def _start_player_turn(self) -> None:
        """切换到玩家回合：重置 AP、回合计数 +1。"""
        self.phase = TurnPhase.PLAYER_TURN
        self.turn_count += 1
        self.player.stats.reset_ap()

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
