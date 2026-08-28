"""
菜单与背包界面模块。

功能说明：
    提供两个 UI 面板：
    - PauseMenu: 暂停菜单（恢复/回主菜单）
    - InventoryMenu: 背包界面（显示物品、装备槽、使用物品）

    这些类只负责显示与点击检测，不直接修改游戏状态。
    按钮的 on_click 回调由调用方（PauseState/PlayState）注入。
"""
from __future__ import annotations

import pygame

from src.core import config
from src.items.item import Item, ItemType
from src.ui.ui_element import Button, Panel, Text


class PauseMenu:
    """暂停菜单。"""

    def __init__(self, on_resume=None, on_quit=None):
        sw, sh = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        # 中央面板
        panel_w, panel_h = 300, 200
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        self.panel = Panel(pygame.Rect(panel_x, panel_y, panel_w, panel_h))

        # 标题
        title_rect = pygame.Rect(panel_x, panel_y + 10, panel_w, 40)
        self.title = Text(title_rect, "已暂停", color=(255, 220, 80))

        # 按钮
        btn_w, btn_h = 220, 36
        btn_x = panel_x + (panel_w - btn_w) // 2
        self.btn_resume = Button(
            pygame.Rect(btn_x, panel_y + 70, btn_w, btn_h),
            "继续游戏 (ESC)", on_click=on_resume,
        )
        self.btn_quit = Button(
            pygame.Rect(btn_x, panel_y + 120, btn_w, btn_h),
            "返回主菜单", on_click=on_quit,
            color=(80, 30, 30),
        )
        self.buttons: list[Button] = [self.btn_resume, self.btn_quit]

    def update(self, dt: float) -> None:
        for btn in self.buttons:
            btn.update(dt)

    def draw(self, screen, font) -> None:
        # 半透明遮罩
        overlay = pygame.Surface((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        # 面板
        self.panel.draw(screen, font)
        self.title.draw(screen, font)
        for btn in self.buttons:
            btn.draw(screen, font)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        for btn in self.buttons:
            if btn.handle_click(pos):
                return True
        return False


class InventoryMenu:
    """背包界面。"""

    def __init__(self, inventory, on_use_item=None):
        self.inventory = inventory
        self.on_use_item = on_use_item
        sw, sh = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        # 面板
        panel_w, panel_h = 600, 400
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        self.panel = Panel(pygame.Rect(panel_x, panel_y, panel_w, panel_h))
        # 标题
        self.title = Text(
            pygame.Rect(panel_x, panel_y + 10, panel_w, 32),
            "背包", color=(255, 220, 80),
        )
        # 关闭按钮
        self.btn_close = Button(
            pygame.Rect(panel_x + panel_w - 100, panel_y + 10, 80, 28),
            "关闭 (I)", on_click=None, color=(80, 30, 30),
        )
        # 装备槽区域
        self.equip_rect = pygame.Rect(panel_x + 20, panel_y + 60, 180, 100)
        # 物品栏区域
        self.slots_rect = pygame.Rect(panel_x + 220, panel_y + 60, 360, 320)

    def update(self, dt: float) -> None:
        self.btn_close.update(dt)

    def draw(self, screen, font) -> None:
        # 半透明遮罩
        overlay = pygame.Surface((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        # 面板
        self.panel.draw(screen, font)
        self.title.draw(screen, font)
        self.btn_close.draw(screen, font)
        # 装备槽
        pygame.draw.rect(screen, (30, 30, 40), self.equip_rect, border_radius=4)
        pygame.draw.rect(screen, (120, 100, 60), self.equip_rect, 2, border_radius=4)
        eq_label = font.render("装备", True, (220, 200, 100))
        screen.blit(eq_label, (self.equip_rect.x + 6, self.equip_rect.y + 4))
        # 显示当前武器
        weapon = self.inventory.equipped_weapon
        if weapon:
            w_text = font.render(f"武器: {weapon.name}", True, (255, 255, 255))
            screen.blit(w_text, (self.equip_rect.x + 6, self.equip_rect.y + 28))
            mod = weapon.stat_modifiers
            mod_text = font.render(
                f"ATK+{mod.atk_bonus} DEF+{mod.def_bonus}", True, (180, 180, 180)
            )
            screen.blit(mod_text, (self.equip_rect.x + 6, self.equip_rect.y + 50))
        else:
            w_text = font.render("武器: 无", True, (150, 150, 150))
            screen.blit(w_text, (self.equip_rect.x + 6, self.equip_rect.y + 28))

        # 物品栏（5 列 × 2 行 = 10 槽）
        slot_size = 64
        gap = 8
        for i in range(self.inventory.MAX_SLOTS):
            col = i % 5
            row = i // 5
            sx = self.slots_rect.x + col * (slot_size + gap)
            sy = self.slots_rect.y + row * (slot_size + gap)
            rect = pygame.Rect(sx, sy, slot_size, slot_size)
            pygame.draw.rect(screen, (30, 30, 40), rect, border_radius=4)
            pygame.draw.rect(screen, (80, 80, 100), rect, 1, border_radius=4)
            item = self.inventory.get_item(i)
            if item:
                # 物品名首字
                color = self._rarity_color(item.rarity)
                name_text = font.render(item.name[:2], True, color)
                screen.blit(name_text, (sx + 4, sy + 4))
                # 数量
                if item.count > 1:
                    cnt_text = font.render(f"x{item.count}", True, (255, 255, 255))
                    screen.blit(cnt_text, (sx + slot_size - 20, sy + slot_size - 20))

    def _rarity_color(self, rarity) -> tuple[int, int, int]:
        """稀有度颜色。"""
        from src.items.item import Rarity
        if rarity == Rarity.COMMON: return (220, 220, 220)
        if rarity == Rarity.UNCOMMON: return (100, 220, 100)
        if rarity == Rarity.RARE: return (100, 150, 255)
        return (200, 100, 220)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        # 关闭按钮
        if self.btn_close.handle_click(pos):
            return True
        # 检测物品栏点击
        slot_size = 64
        gap = 8
        for i in range(self.inventory.MAX_SLOTS):
            col = i % 5
            row = i // 5
            sx = self.slots_rect.x + col * (slot_size + gap)
            sy = self.slots_rect.y + row * (slot_size + gap)
            rect = pygame.Rect(sx, sy, slot_size, slot_size)
            if rect.collidepoint(pos):
                item = self.inventory.get_item(i)
                if item is not None and self.on_use_item:
                    self.on_use_item(i)
                return True
        return False
