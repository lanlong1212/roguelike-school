"""
图鉴式帮助系统（Help/Codex UI）。

功能说明：
    覆盖层式图鉴面板，玩家可随时查看操作指南、元素反应表、房间类型、
    状态效果、伙伴系统五类信息。游戏内 F1 / 暂停菜单 / 主菜单均可打开。
    - 共 5 个标签页，始终可见（不随伙伴是否存在隐藏）
    - 半透明遮罩 + 内容面板，绘制在所有游戏元素之上
    - 不参与状态栈（不 push_state/pop_state），避免 pop 重进状态的坑
    - 不记录已读状态

使用约定：
    - handle_event(event) -> bool：处理事件；返回 True 表示面板保持打开，
      False 表示应关闭面板。调用方据此置空引用。
    - update(dt)：无状态动画（接口一致，空实现）
    - draw(screen, font, small_font)：small_font 缺省回退 font
"""
from __future__ import annotations

import pygame

from src.combat.element import ELEMENT_COLOR, ELEMENT_NAME, Element
from src.core import config
from src.items.relics import RELICS
from src.ui.icons import fit_icon, get_element_icon


# ========== 各标签页内容（硬编码，中文） ==========

# 页 1：操作指南（键位一览）
_PAGE_GUIDE = [
    ("移动", "WASD / 方向键，长按连续走，松开即停"),
    ("攻击", "鼠标点击敌人（战斗模式）"),
    ("切换技能", "数字键 1~6"),
    ("移动模式", "M（切回移动，不消耗 AP 选择）"),
    ("喝药", "H（战斗中不消耗 AP）"),
    ("背包", "B（装备武器 / 使用药水）"),
    ("收起 HUD", "V（左上角状态栏）"),
    ("暂停", "ESC"),
    ("结束回合", "空格（AP 耗尽不会自动结束）"),
    ("切换角色", "Tab（有伙伴时：主角 ↔ 伙伴）"),
    ("图鉴", "F1（随时打开 / 关闭本面板）"),
]

# 页 2：元素反应表（元素图标 + 名称 + 效果）
_PAGE_ELEMENTS = [
    (Element.FIRE, Element.WATER, "蒸发", "伤害 ×1.5"),
    (Element.WATER, Element.ICE, "冻结", "目标跳过下一回合"),
    (Element.LIGHTNING, Element.WATER, "感电", "追加雷伤 + 受击伤害 ×1.5（2 回合）"),
    (Element.LIGHTNING, Element.ICE, "超导", "追加伤害 + 破甲（防御减半，2 回合）"),
    (Element.FIRE, Element.ICE, "融化", "追加伤害 + 受击伤害 ×1.25（1 回合）"),
    (Element.LIGHTNING, Element.FIRE, "超载", "追加伤害 + 回合末雷爆 2 点"),
]

# 页 3：房间类型（名称 + 说明 + 名称颜色）
_PAGE_ROOMS = [
    ("战斗房", "普通敌人，全灭后解锁离开", (200, 200, 210)),
    ("精英房", "三阶段精英（召唤史莱姆 / 狂暴双连击）", config.COLOR_ELITE),
    ("Boss 房", "楼层 Boss，击败后才能走下楼梯", config.COLOR_BOSS),
    ("商店房", "金币购买装备与药水，每层一次", (230, 210, 60)),
    ("休息房", "回血 或 三选一学习技能 / 天赋，每层一次", (120, 220, 120)),
]

# 页 4：状态效果（名称 + 说明）
_PAGE_STATUS = [
    ("眩晕", "跳过本回合行动"),
    ("冻结", "跳过本回合行动（水+冰 反应）"),
    ("护盾", "吸收固定量伤害，持续 2 回合"),
    ("感电", "受击伤害 ×1.5（雷+水 反应）"),
    ("破甲", "防御减半（雷+冰 反应）"),
    ("减速", "下回合 AP 上限 -1（寒冰箭附加）"),
    ("嘲讽", "强制敌人 2 回合只攻击施放者（伙伴技能）"),
]

# 页 5：伙伴系统（条目名 + 说明）
_PAGE_COMPANION = [
    ("来源", "休息房天赋三选一：召唤伙伴"),
    ("属性", "15 HP / 3 ATK / 3 DEF / 移动 3 格"),
    ("独立 AP", "每回合固定 2 点，不消耗主角 AP"),
    ("切换", "Tab 键或点击底部头像栏"),
    ("嘲讽", "0 AP：强制敌人 2 回合只攻击伙伴"),
    ("守护光环", "伙伴存活时主角每回合首次受伤 -2"),
    ("反击姿态", "1 AP：受近战攻击时反击 50% 伤害"),
    ("死亡", "本局永久消失，不可复活"),
]

# 各页顶部的一句话说明（页眉）
_PAGE_HEADER = {
    0: "基础键位与操作一览",
    1: "双元素命中触发反应，反应后双方附着消耗",
    2: "每层 6 个房间：1 Boss + 1 精英 + 1 商店 + 1 休息 + 2 战斗",
    3: "战斗中常见的控制 / 增益 / 减益状态",
    4: "召唤后获得独立 AP 的友方单位，可 Tab 切换操控",
    5: "击败精英 / Boss 或商店购买可获得遗物，共 8 种",
}


class HelpPanel:
    """图鉴覆盖层面板：标签页切换 + 内容渲染 + 键盘/鼠标交互。"""

    # 标签页名称（顺序即显示顺序）
    TABS = ["操作指南", "元素反应", "房间类型", "状态效果", "伙伴系统", "遗物"]

    def __init__(self, player=None):
        self.current_tab: int = 0  # 当前选中标签下标
        # 保留 player 参数以兼容暂停菜单 / 主菜单调用方；
        # 遗物页已改为全量展示（不再按 owned_relics 涂黑），此处不再读取玩家数据
        self.player = player
        # 面板几何（居中）
        sw, sh = config.SCREEN_WIDTH, config.SCREEN_HEIGHT
        panel_w, panel_h = 780, 540
        self.panel_rect = pygame.Rect((sw - panel_w) // 2, (sh - panel_h) // 2, panel_w, panel_h)
        # 关闭按钮（右上角）
        self.close_rect = pygame.Rect(self.panel_rect.right - 96, self.panel_rect.top + 12, 82, 30)
        # 标签页矩形（顶部横排均分）
        tab_w = panel_w // len(self.TABS)
        self.tab_rects = [
            pygame.Rect(self.panel_rect.x + i * tab_w, self.panel_rect.y + 50, tab_w, 36)
            for i in range(len(self.TABS))
        ]
        # 内容区起点（标签下方）
        self._content_x = self.panel_rect.x + 30
        self._content_top = self.panel_rect.y + 102
        # 底部操作提示
        self.hint = "← → 切换标签 · F1 / Esc 关闭"

    # ========== 交互 ==========

    def handle_event(self, event) -> bool:
        """处理事件；返回 True 表示面板保持打开，False 表示应关闭。"""
        if event.type == pygame.KEYDOWN:
            # F1 / Esc → 关闭
            if event.key in (pygame.K_F1, pygame.K_ESCAPE):
                return False
            # 左右方向键 → 切换标签
            if event.key == pygame.K_LEFT:
                self._switch_tab(-1)
            elif event.key == pygame.K_RIGHT:
                self._switch_tab(1)
            return True  # 其他按键保持打开（消费，不传给下层）
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # 点 X → 关闭
            if self.close_rect.collidepoint(event.pos):
                return False
            # 点标签 → 切换
            for i, rect in enumerate(self.tab_rects):
                if rect.collidepoint(event.pos):
                    self.current_tab = i
                    return True
            # 点面板外 → 关闭（覆盖层惯例）
            if not self.panel_rect.collidepoint(event.pos):
                return False
            return True  # 面板内空白：保持打开
        # 其余事件（鼠标移动等）一律消费，避免传给下层
        return True

    def _switch_tab(self, delta: int) -> None:
        """标签循环切换。"""
        self.current_tab = (self.current_tab + delta) % len(self.TABS)

    # ========== 生命周期（接口一致） ==========

    def update(self, dt: float) -> None:
        """静态面板无需动画，保持接口一致。"""
        pass

    # ========== 绘制 ==========

    def draw(self, screen, font, small_font=None) -> None:
        """半透明遮罩 + 面板 + 标题 + 标签页 + 当前页内容 + 底部提示。"""
        small = small_font if small_font is not None else font
        # 遮罩（盖住全部游戏画面）
        overlay = pygame.Surface((config.SCREEN_WIDTH, config.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        screen.blit(overlay, (0, 0))
        # 面板背景
        panel_surf = pygame.Surface(self.panel_rect.size, pygame.SRCALPHA)
        panel_surf.fill((22, 22, 34, 240))
        screen.blit(panel_surf, self.panel_rect.topleft)
        pygame.draw.rect(screen, (150, 150, 180), self.panel_rect, 2, border_radius=6)
        # 标题
        title = font.render("图鉴", True, (255, 220, 100))
        screen.blit(title, (self.panel_rect.x + 16, self.panel_rect.y + 14))
        # 关闭按钮（hover 高亮）
        hover_close = self.close_rect.collidepoint(pygame.mouse.get_pos())
        close_bg = (140, 50, 50) if hover_close else (80, 40, 40)
        pygame.draw.rect(screen, close_bg, self.close_rect, border_radius=4)
        pygame.draw.rect(screen, (210, 130, 130), self.close_rect, 1, border_radius=4)
        close_text = font.render("关闭 (X)", True, (255, 220, 220))
        screen.blit(close_text, close_text.get_rect(center=self.close_rect.center))
        # 标签页
        for i, rect in enumerate(self.tab_rects):
            selected = i == self.current_tab
            bg = (66, 78, 120) if selected else (36, 40, 62)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            border = (255, 220, 100) if selected else (90, 90, 112)
            pygame.draw.rect(screen, border, rect, 2 if selected else 1, border_radius=4)
            color = (255, 235, 170) if selected else (200, 200, 212)
            tab_text = font.render(self.TABS[i], True, color)
            screen.blit(tab_text, tab_text.get_rect(center=rect.center))
        # 页眉说明
        header = small.render(
            _PAGE_HEADER.get(self.current_tab, ""), True, (170, 170, 190)
        )
        screen.blit(header, (self._content_x, self.panel_rect.y + 94))
        # 当前页内容
        self._draw_current_page(screen, font, small)
        # 底部提示
        hint = small.render(self.hint, True, (150, 150, 165))
        screen.blit(hint, (self._content_x, self.panel_rect.bottom - 28))

    def _draw_current_page(self, screen, font, small_font) -> None:
        """按当前标签分派到对应页面渲染。"""
        if self.current_tab == 0:
            self._draw_entry_list(screen, font, _PAGE_GUIDE, row_h=36, name_w=120)
        elif self.current_tab == 1:
            self._draw_element_page(screen, font, small_font)
        elif self.current_tab == 2:
            self._draw_room_page(screen, font)
        elif self.current_tab == 3:
            self._draw_entry_list(screen, font, _PAGE_STATUS, row_h=36, name_w=110)
        elif self.current_tab == 4:
            self._draw_entry_list(screen, font, _PAGE_COMPANION, row_h=36, name_w=130)
        else:
            # 遗物页（5）：全部遗物统一展示
            self._draw_relic_page(screen, font, small_font)

    def _draw_entry_list(self, screen, font, entries, row_h: int, name_w: int) -> None:
        """通用条目列表：左侧名称（金色），右侧说明。"""
        x, y = self._content_x, self._content_top + 8
        for name, desc in entries:
            name_text = font.render(name, True, (255, 220, 120))
            screen.blit(name_text, (x, y))
            desc_text = font.render(desc, True, (215, 215, 225))
            screen.blit(desc_text, (x + name_w, y))
            y += row_h

    def _draw_element_page(self, screen, font, small_font) -> None:
        """元素反应页：两个元素图标 + 名称 + 效果描述。"""
        x, y = self._content_x, self._content_top + 8
        icon_size = 30
        for e1, e2, name, desc in _PAGE_ELEMENTS:
            # 元素图标 1 + 加号 + 元素图标 2 + 反应名 + 效果
            self._blit_element_icon(screen, e1, x, y, icon_size)
            plus = font.render("+", True, (210, 210, 215))
            screen.blit(plus, (x + icon_size + 8, y + 4))
            self._blit_element_icon(screen, e2, x + icon_size + 26, y, icon_size)
            name_text = font.render(f"= {name}", True, (255, 220, 100))
            screen.blit(name_text, (x + icon_size * 2 + 64, y))
            desc_text = small_font.render(desc, True, (215, 215, 225))
            screen.blit(desc_text, (x + icon_size * 2 + 230, y + 6))
            y += 52

    def _draw_room_page(self, screen, font) -> None:
        """房间类型页：名称用对应颜色，右侧说明。"""
        x, y = self._content_x, self._content_top + 8
        for name, desc, color in _PAGE_ROOMS:
            name_text = font.render(name, True, color)
            screen.blit(name_text, (x, y))
            desc_text = font.render(desc, True, (215, 215, 225))
            screen.blit(desc_text, (x + 140, y))
            y += 42

    def _draw_relic_page(self, screen, font, small_font) -> None:
        """遗物页：全部 8 个遗物逐行展示（色块图标 + 金色名称 + 效果描述）。

        改版说明：不再按 owned_relics 区分已获取 / 未获取，
        所有遗物统一正常显示名称与描述（图鉴不再涂黑、不显示 "???" / "尚未获得"）。"""
        x, y = self._content_x, self._content_top + 8
        icon_size = 24
        row_h = 48
        for data in RELICS.values():
            # 色块图标 + 名称 + 描述（全部遗物统一展示）
            pygame.draw.rect(
                screen, data["color"], (x, y, icon_size, icon_size), border_radius=4
            )
            pygame.draw.rect(
                screen, (20, 20, 30), (x, y, icon_size, icon_size), 1, border_radius=4
            )
            ch = data.get("short") or data["name"][:1]
            ch_s = font.render(ch, True, (20, 20, 30))
            screen.blit(ch_s, ch_s.get_rect(center=(x + icon_size // 2, y + icon_size // 2)))
            name_s = font.render(data["name"], True, (255, 220, 120))
            screen.blit(name_s, (x + icon_size + 10, y))
            desc_s = small_font.render(data["description"], True, (215, 215, 225))
            screen.blit(desc_s, (x + icon_size + 10, y + 22))
            y += row_h

    @staticmethod
    def _blit_element_icon(screen, element, x: int, y: int, size: int) -> None:
        """绘制元素小图标：复用技能栏素材；素材缺失时用元素色圆点回退。"""
        icon = get_element_icon(element)
        if icon is not None:
            screen.blit(fit_icon(icon, size), (x, y))
            return
        # 无素材回退：元素色圆 + 单字
        color = ELEMENT_COLOR[element]
        cx, cy = x + size // 2, y + size // 2
        pygame.draw.circle(screen, color, (cx, cy), size // 2)
        pygame.draw.circle(screen, (20, 20, 30), (cx, cy), size // 2, 1)
        label = pygame.font.Font(None, size).render(ELEMENT_NAME[element], True, (20, 20, 30))
        screen.blit(label, label.get_rect(center=(cx, cy)))
