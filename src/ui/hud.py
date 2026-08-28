"""
HUD（抬头显示）模块。

功能说明：
    游戏中固定显示的信息层：
    - 左上：玩家 HP 条 + AP 条
    - 右上：当前楼层 + 回合数（战斗中）
    - 底部：操作提示 + 战利品掉落信息
    - 战斗中：行动描述、技能栏（已有，Day 5）

设计考量：
    HUD 不直接操作游戏状态，只读取数据并显示。
    由 PlayState 调用 draw()，传入需要显示的数据。
"""
from __future__ import annotations

import pygame

from src.core import config
from src.ui.ui_element import Bar, Panel, Text


class HUD:
    """游戏 HUD 管理器。"""

    def __init__(self):
        # 左上角面板：玩家状态
        self.status_panel = Panel(
            pygame.Rect(8, 8, 200, 70),
            color=(15, 15, 25),
            border_color=(80, 80, 100),
        )
        self.hp_bar = Bar(
            pygame.Rect(14, 18, 188, 22),
            current=30, maximum=30,
            color=(200, 60, 60), label="HP",
        )
        self.ap_bar = Bar(
            pygame.Rect(14, 44, 188, 22),
            current=5, maximum=5,
            color=(60, 120, 220), label="AP",
        )

        # 右上角：楼层/回合
        self.info_panel = Panel(
            pygame.Rect(config.SCREEN_WIDTH - 208, 8, 200, 40),
            color=(15, 15, 25),
            border_color=(80, 80, 100),
        )
        self.info_text = Text(
            pygame.Rect(config.SCREEN_WIDTH - 208, 8, 200, 40),
            "楼层 1",
            color=(220, 220, 200),
        )

        # 底部操作提示
        self.tip_text = Text(
            pygame.Rect(8, config.SCREEN_HEIGHT - 30, 600, 24),
            "WASD 移动 · ESC 暂停 · I 背包",
            color=(160, 160, 160),
            center=False,
        )

    def update(self, player, floor, battle=None, mode=None, loot_desc: str = "") -> None:
        """根据游戏状态更新 HUD 数据。"""
        # 血条
        self.hp_bar.set_value(player.stats.hp, player.stats.max_hp)
        # AP 条
        self.ap_bar.set_value(player.stats.ap, player.stats.max_ap)
        # 楼层/回合
        level = getattr(floor, "level", getattr(floor, "current_level", 1))
        if battle is not None:
            info = f"楼层 {level} · 回合 {battle.turn_count}"
            if battle.is_enemy_turn:
                info += " · 敌人回合"
        else:
            info = f"楼层 {level}"
        self.info_text.set_text(info)
        # 底部提示
        if loot_desc:
            self.tip_text.set_text(loot_desc)
        elif mode is not None and mode.name == "BATTLE":
            self.tip_text.set_text(
                "1/2/3 技能 · M 移动 · H 药水 · 空格结束回合"
            )
        else:
            self.tip_text.set_text("WASD 移动 · ESC 暂停 · I 背包")

    def draw(self, screen, font) -> None:
        """绘制 HUD。"""
        self.status_panel.draw(screen, font)
        self.hp_bar.draw(screen, font)
        self.ap_bar.draw(screen, font)
        self.info_panel.draw(screen, font)
        self.info_text.draw(screen, font)
        self.tip_text.draw(screen, font)
