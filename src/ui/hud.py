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
        # 左上角面板：玩家状态（+ 伙伴血条）
        self.status_panel = Panel(
            pygame.Rect(8, 8, 200, 124),
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
        # 伙伴血条（仅伙伴存在且存活时显示）
        self.companion_hp_bar = Bar(
            pygame.Rect(14, 70, 188, 22),
            current=0, maximum=15,
            color=(80, 200, 120), label="伴",
        )
        # 玩家状态效果（元素系统：冻结/感电/破甲等）
        self.status_text = Text(
            pygame.Rect(14, 96, 188, 24),
            "",
            color=(255, 220, 120),
            center=False,
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

        # 状态面板收起开关（避免面板挡住地图上的敌人）
        self.collapsed = False
        # 展开态：面板右侧小按钮；收起态：左上角小按钮
        self.toggle_rect = pygame.Rect(212, 8, 22, 22)

    def toggle(self) -> None:
        """切换状态面板显示/收起。"""
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.toggle_rect = pygame.Rect(8, 8, 22, 22)
        else:
            self.toggle_rect = pygame.Rect(212, 8, 22, 22)

    def update(self, player, floor, battle=None, mode=None, loot_desc: str = "", companion=None) -> None:
        """根据游戏状态更新 HUD 数据。companion 为伙伴实体（可无），存活时显示其血条。"""
        # 血条
        self.hp_bar.set_value(player.stats.hp, player.stats.max_hp)
        # AP 条
        self.ap_bar.set_value(player.stats.ap, player.stats.max_ap)
        # 伙伴血条（不存在/死亡时不显示）
        if companion is not None and getattr(companion, "alive", False):
            self.companion_hp_bar.visible = True
            self.companion_hp_bar.set_value(companion.stats.hp, companion.stats.max_hp)
        else:
            self.companion_hp_bar.visible = False
        # 玩家状态效果
        effects = player.status_effects.all
        if effects:
            from src.combat.status_effect import EFFECT_DISPLAY_NAME
            labels = [EFFECT_DISPLAY_NAME[e.effect_type] for e in effects]
            self.status_text.set_text("状态: " + " ".join(labels))
        else:
            self.status_text.set_text("")
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
                "1/2/3 技能 · M 移动 · H 药水 · 空格结束回合 · V 收起状态"
            )
        else:
            self.tip_text.set_text("WASD 移动 · ESC 暂停 · I 背包 · V 收起状态")

    def draw(self, screen, font) -> None:
        """绘制 HUD。"""
        if not self.collapsed:
            self.status_panel.draw(screen, font)
            self.hp_bar.draw(screen, font)
            self.ap_bar.draw(screen, font)
            if self.companion_hp_bar.visible:
                self.companion_hp_bar.draw(screen, font)
            self.status_text.draw(screen, font)
        self.info_panel.draw(screen, font)
        self.info_text.draw(screen, font)
        self.tip_text.draw(screen, font)
        # 收起开关按钮（收起时显示 ＋，展开时显示 −）
        r = self.toggle_rect
        pygame.draw.rect(screen, (15, 15, 25), r, border_radius=4)
        pygame.draw.rect(screen, (80, 80, 100), r, 1, border_radius=4)
        glyph = font.render("＋" if self.collapsed else "−", True, (220, 220, 200))
        screen.blit(
            glyph,
            glyph.get_rect(center=r.center),
        )
