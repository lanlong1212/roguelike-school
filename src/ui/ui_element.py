"""
UI 元素基类模块。

功能说明：
    定义 UI 元素基类与常用组件：Button/Panel/Bar/Text。
    所有 UI 元素继承 UIElement，实现 update/draw 接口。
    供 HUD、菜单、结算界面使用。

设计考量：
    - UIElement 持有 rect（pygame.Rect），支持鼠标点击检测
    - 文字渲染由外部传入 font，避免每个元素自己创建字体
    - 颜色配置来自 config 模块，统一管理
"""
from __future__ import annotations

import pygame


class UIElement:
    """UI 元素基类。"""

    def __init__(self, rect: pygame.Rect):
        self.rect = rect
        self.visible: bool = True
        self.enabled: bool = True

    def update(self, dt: float) -> None:
        """每帧更新。基类为空。"""
        pass

    def draw(self, screen, font) -> None:
        """每帧绘制。基类为空。"""
        pass

    def handle_click(self, pos: tuple[int, int]) -> bool:
        """鼠标点击检测。返回是否点中。"""
        if not self.visible or not self.enabled:
            return False
        return self.rect.collidepoint(pos)


# ========== 按钮 ==========

class Button(UIElement):
    """可点击按钮。"""

    def __init__(
        self,
        rect: pygame.Rect,
        text: str,
        on_click=None,
        color: tuple[int, int, int] = (50, 60, 80),
        text_color: tuple[int, int, int] = (255, 255, 255),
    ):
        super().__init__(rect)
        self.text = text
        self.on_click = on_click
        self.color = color
        self.text_color = text_color
        self.hovered = False

    def update(self, dt: float) -> None:
        mouse_pos = pygame.mouse.get_pos()
        self.hovered = self.rect.collidepoint(mouse_pos)

    def draw(self, screen, font) -> None:
        # hover 时亮一点
        color = tuple(min(255, c + 30) for c in self.color) if self.hovered else self.color
        pygame.draw.rect(screen, color, self.rect, border_radius=6)
        border_color = (255, 255, 255) if self.hovered else (100, 100, 100)
        pygame.draw.rect(screen, border_color, self.rect, 2, border_radius=6)
        text_surf = font.render(self.text, True, self.text_color)
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)

    def handle_click(self, pos: tuple[int, int]) -> bool:
        if super().handle_click(pos):
            if self.on_click:
                self.on_click()
            return True
        return False


# ========== 面板 ==========

class Panel(UIElement):
    """背景面板。"""

    def __init__(
        self,
        rect: pygame.Rect,
        color: tuple[int, int, int] = (20, 20, 30),
        border_color: tuple[int, int, int] = (100, 100, 100),
    ):
        super().__init__(rect)
        self.color = color
        self.border_color = border_color

    def draw(self, screen, font) -> None:
        # 半透明背景
        overlay = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        overlay.fill((*self.color, 200))
        screen.blit(overlay, self.rect.topleft)
        pygame.draw.rect(screen, self.border_color, self.rect, 2, border_radius=4)


# ========== 进度条（血条/AP 条） ==========

class Bar(UIElement):
    """进度条（血条/AP 条）。"""

    def __init__(
        self,
        rect: pygame.Rect,
        current: float = 0,
        maximum: float = 100,
        color: tuple[int, int, int] = (200, 50, 50),
        bg_color: tuple[int, int, int] = (40, 40, 40),
        label: str = "",
    ):
        super().__init__(rect)
        self.current = current
        self.maximum = maximum
        self.color = color
        self.bg_color = bg_color
        self.label = label

    def set_value(self, current: float, maximum: float | None = None) -> None:
        self.current = current
        if maximum is not None:
            self.maximum = maximum

    def draw(self, screen, font) -> None:
        # 背景
        pygame.draw.rect(screen, self.bg_color, self.rect, border_radius=2)
        # 前景
        if self.maximum > 0:
            ratio = max(0, min(1, self.current / self.maximum))
            fg_width = int(self.rect.width * ratio)
            if fg_width > 0:
                fg_rect = pygame.Rect(self.rect.x, self.rect.y, fg_width, self.rect.height)
                pygame.draw.rect(screen, self.color, fg_rect, border_radius=2)
        # 边框
        pygame.draw.rect(screen, (180, 180, 180), self.rect, 1, border_radius=2)
        # 数值文字
        if self.label:
            text = f"{self.label}: {int(self.current)}/{int(self.maximum)}"
        else:
            text = f"{int(self.current)}/{int(self.maximum)}"
        text_surf = font.render(text, True, (255, 255, 255))
        text_rect = text_surf.get_rect(center=self.rect.center)
        screen.blit(text_surf, text_rect)


# ========== 文本标签 ==========

class Text(UIElement):
    """静态文本标签。"""

    def __init__(
        self,
        rect: pygame.Rect,
        text: str,
        color: tuple[int, int, int] = (255, 255, 255),
        center: bool = True,
    ):
        super().__init__(rect)
        self.text = text
        self.color = color
        self.center = center

    def set_text(self, text: str) -> None:
        self.text = text

    def draw(self, screen, font) -> None:
        text_surf = font.render(self.text, True, self.color)
        if self.center:
            text_rect = text_surf.get_rect(center=self.rect.center)
        else:
            text_rect = self.rect.topleft
        screen.blit(text_surf, text_rect)
