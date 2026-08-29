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


class ShopMenu:
    """神秘商人商店界面。

    显示玩家金币余额与商品列表（名称/描述/价格），点击商品购买。
    stock 为 [(Item, price), ...] 列表，sold 记录已售罄的商品下标。
    on_buy(index) 由调用方注入，负责扣金币、加背包并标记已售。
    """

    def __init__(self, player, stock: list, on_buy=None, on_close=None):
        self.player = player
        self.stock = stock  # list[tuple[Item, int]]（物品, 价格）
        self.sold: set[int] = set()  # 已售罄商品下标
        self.on_buy = on_buy
        self.on_close = on_close
        sw, sh = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        # 面板
        panel_w, panel_h = 480, 460
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        self.panel = Panel(pygame.Rect(panel_x, panel_y, panel_w, panel_h))
        self.title = Text(
            pygame.Rect(panel_x, panel_y + 10, panel_w, 32),
            "神秘商店", color=(230, 210, 60),
        )
        self.btn_close = Button(
            pygame.Rect(panel_x + panel_w - 100, panel_y + 10, 80, 28),
            "离开", on_click=None, color=(80, 30, 30),
        )
        # 商品行（名称/描述/价格按钮）
        self.item_rects: list[pygame.Rect] = []
        row_w = panel_w - 40
        for i in range(len(self.stock)):
            row_y = panel_y + 70 + i * 82
            self.item_rects.append(pygame.Rect(panel_x + 20, row_y, row_w, 70))

    def is_sold(self, index: int) -> bool:
        return index in self.sold

    def mark_sold(self, index: int) -> None:
        self.sold.add(index)

    def update(self, dt: float) -> None:
        self.btn_close.update(dt)

    def draw(self, screen, font) -> None:
        # 半透明遮罩
        overlay = pygame.Surface((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))
        # 面板
        self.panel.draw(screen, font)
        self.title.draw(screen, font)
        self.btn_close.draw(screen, font)
        # 金币余额
        gold_text = font.render(f"金币: {self.player.gold}", True, (255, 220, 80))
        screen.blit(gold_text, (self.panel.rect.x + 20, self.panel.rect.y + 44))

        # 商品列表
        for i, (item, price) in enumerate(self.stock):
            rect = self.item_rects[i]
            sold = i in self.sold
            bg = (35, 35, 45) if not sold else (25, 25, 30)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            border = (110, 100, 60) if not sold else (60, 60, 60)
            pygame.draw.rect(screen, border, rect, 1, border_radius=4)
            # 名称（稀有度颜色）
            name_color = self._rarity_color(item.rarity) if not sold else (90, 90, 90)
            name_text = font.render(item.name, True, name_color)
            screen.blit(name_text, (rect.x + 10, rect.y + 8))
            # 描述
            desc_text = font.render(item.description, True, (170, 170, 170))
            screen.blit(desc_text, (rect.x + 10, rect.y + 32))
            # 价格/售罄
            if sold:
                price_text = font.render("已售罄", True, (90, 90, 90))
            else:
                price_text = font.render(f"{price} 金币", True, (255, 220, 80))
            screen.blit(price_text, (rect.x + rect.width - 90, rect.y + 24))

    def _rarity_color(self, rarity) -> tuple[int, int, int]:
        from src.items.item import Rarity
        if rarity == Rarity.COMMON: return (220, 220, 220)
        if rarity == Rarity.UNCOMMON: return (100, 220, 100)
        if rarity == Rarity.RARE: return (100, 150, 255)
        return (200, 100, 220)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        # 关闭按钮
        if self.btn_close.handle_click(pos):
            if self.on_close:
                self.on_close()
            return True
        # 商品购买
        for i, rect in enumerate(self.item_rects):
            if rect.collidepoint(pos):
                if i not in self.sold and self.on_buy:
                    self.on_buy(i)
                return True
        return False


class RestMenu:
    """休息房间界面：休息（回血）或强化（学习技能）。

    提供两个操作：
    - 休息：回复玩家 50% 最大 HP（由调用方 on_rest 实现）
    - 强化：从技能池选择一个未学技能学习（on_learn(skill) 实现）
    点击"强化"后切换到技能列表视图，选择技能后关闭。
    """

    def __init__(
        self,
        player,
        unlearned_skills: list,
        on_rest=None,
        on_learn=None,
        on_close=None,
    ):
        self.player = player
        self.unlearned_skills = unlearned_skills  # list[Skill] 尚未学习的技能
        self.on_rest = on_rest
        self.on_learn = on_learn
        self.on_close = on_close
        self.showing_skills = False  # True=技能选择视图
        sw, sh = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        # 面板
        panel_w, panel_h = 520, 420
        panel_x = (sw - panel_w) // 2
        panel_y = (sh - panel_h) // 2
        self.panel = Panel(pygame.Rect(panel_x, panel_y, panel_w, panel_h))
        self.title = Text(
            pygame.Rect(panel_x, panel_y + 10, panel_w, 32),
            "休息房间", color=(120, 220, 120),
        )
        self.btn_close = Button(
            pygame.Rect(panel_x + panel_w - 100, panel_y + 10, 80, 28),
            "离开", on_click=None, color=(80, 30, 30),
        )
        # 主视图按钮
        self.btn_rest = Button(
            pygame.Rect(panel_x + 90, panel_y + 120, panel_w - 180, 64),
            "休息", on_click=None, color=(40, 110, 60),
        )
        self.btn_train = Button(
            pygame.Rect(panel_x + 90, panel_y + 210, panel_w - 180, 64),
            "强化", on_click=None, color=(80, 70, 120),
        )
        self.buttons: list[Button] = [self.btn_rest, self.btn_train]
        # 技能列表行
        self.skill_rects: list[pygame.Rect] = []
        for i in range(len(unlearned_skills)):
            row_y = panel_y + 90 + i * 76
            self.skill_rects.append(pygame.Rect(panel_x + 40, row_y, panel_w - 80, 64))

    # ========== 视图切换 ==========

    def enter_skill_view(self) -> None:
        """点击"强化"后切换到技能列表视图。"""
        self.showing_skills = True

    def update(self, dt: float) -> None:
        self.btn_close.update(dt)
        if not self.showing_skills:
            for btn in self.buttons:
                btn.update(dt)

    def draw(self, screen, font) -> None:
        # 半透明遮罩
        overlay = pygame.Surface((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))
        self.panel.draw(screen, font)
        self.title.draw(screen, font)
        self.btn_close.draw(screen, font)

        if not self.showing_skills:
            # 主视图：休息 / 强化
            hp_text = font.render(
                f"HP: {self.player.stats.hp}/{self.player.stats.max_hp}",
                True, (255, 255, 255),
            )
            screen.blit(hp_text, (self.panel.rect.x + 40, self.panel.rect.y + 60))
            self.btn_rest.draw(screen, font)
            rest_desc = font.render("回复 50% 生命值", True, (180, 180, 180))
            screen.blit(rest_desc, (self.panel.rect.x + 60, self.btn_rest.rect.y + 66))
            self.btn_train.draw(screen, font)
            train_desc = font.render("从技能池中学习一个新技能", True, (180, 180, 180))
            screen.blit(train_desc, (self.panel.rect.x + 60, self.btn_train.rect.y + 66))
        else:
            # 技能列表视图
            header = font.render("选择一个技能学习：", True, (220, 220, 220))
            screen.blit(header, (self.panel.rect.x + 40, self.panel.rect.y + 56))
            if not self.unlearned_skills:
                empty = font.render("已学会全部技能", True, (150, 150, 150))
                screen.blit(empty, (self.panel.rect.x + 40, self.panel.rect.y + 100))
                return
            for i, skill in enumerate(self.unlearned_skills):
                rect = self.skill_rects[i]
                pygame.draw.rect(screen, (40, 40, 55), rect, border_radius=4)
                pygame.draw.rect(screen, (110, 160, 110), rect, 1, border_radius=4)
                # 技能名（元素色）
                from src.combat.element import ELEMENT_COLOR, Element
                name_color = (
                    ELEMENT_COLOR[skill.element]
                    if skill.element is not Element.NONE else (230, 230, 230)
                )
                name_text = font.render(skill.name, True, name_color)
                screen.blit(name_text, (rect.x + 10, rect.y + 6))
                # 描述
                desc_text = font.render(skill.desc, True, (170, 170, 170))
                screen.blit(desc_text, (rect.x + 10, rect.y + 32))

    def handle_click(self, pos: tuple[int, int]) -> bool:
        # 关闭按钮
        if self.btn_close.handle_click(pos):
            if self.on_close:
                self.on_close()
            return True
        if not self.showing_skills:
            if self.btn_rest.handle_click(pos):
                if self.on_rest:
                    self.on_rest()
                return True
            if self.btn_train.handle_click(pos):
                if self.unlearned_skills:
                    self.enter_skill_view()
                return True
            return False
        # 技能列表视图：点击技能学习
        for i, rect in enumerate(self.skill_rects):
            if i >= len(self.unlearned_skills):
                break
            if rect.collidepoint(pos):
                if self.on_learn:
                    self.on_learn(self.unlearned_skills[i])
                return True
        return False
