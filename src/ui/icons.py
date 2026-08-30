"""
UI 图标模块。

功能说明：
    统一加载 assets/images/ui/ 下的图标（物品图标 / 元素技能图标），
    带缓存、缺失素材自动回退。供菜单（menu.py）与游戏状态（play_state.py）
    共用，避免重复实现与循环导入。
    素材统一为 32×32，展示时按需等比缩放（fit_icon）。

使用约定：
    - get_item_icon(item_id)：物品 id → 图标 Surface（无映射/加载失败返回 None）
    - get_element_icon(element)：元素 → 图标 Surface（无映射/加载失败返回 None）
    - fit_icon(icon, size)：等比缩放并居中到 size×size 透明画布（保持像素风）
"""
from __future__ import annotations

import pygame

from src.combat.element import Element
from src.core.asset_manager import resource_root

_UI_DIR = resource_root() / "assets" / "images" / "ui"


def _load_image(path) -> "pygame.Surface | None":
    """安全加载单张图片；无头环境（测试）跳过 convert_alpha。"""
    if not path.exists():
        return None
    if pygame.display.get_surface() is not None:
        return pygame.image.load(str(path)).convert_alpha()
    return pygame.image.load(str(path))


# ========== 元素技能图标 ==========

_ELEMENT_ICON_FILES: dict[Element, str] = {
    Element.FIRE: "fire.png",
    Element.ICE: "ice.png",
    Element.WATER: "water.png",
    Element.LIGHTNING: "thunder.png",
}
_ELEMENT_ICON_DIR = _UI_DIR / "element"
_ELEMENT_ICONS: dict[Element, "pygame.Surface | None"] = {}


def get_element_icon(element: Element) -> "pygame.Surface | None":
    """懒加载元素技能图标，失败（无素材）返回 None。"""
    if element not in _ELEMENT_ICONS:
        fname = _ELEMENT_ICON_FILES.get(element)
        path = _ELEMENT_ICON_DIR / fname if fname else None
        _ELEMENT_ICONS[element] = _load_image(path) if path else None
    return _ELEMENT_ICONS[element]


# ========== 物品图标 ==========
# item_id → 素材文件名（ui/item/ 下）
_ITEM_ICON_FILES: dict[str, str] = {
    "iron_sword": "sword.png",
    "long_bow": "Bow.png",
    "health_potion": "recovery_potion.png",
    "strength_potion": "attack_potion.png",
}
_ITEM_ICON_DIR = _UI_DIR / "item"
_ITEM_ICONS: dict[str, "pygame.Surface | None"] = {}


def get_item_icon(item_id: str) -> "pygame.Surface | None":
    """懒加载物品图标，无对应素材或加载失败返回 None。"""
    if item_id not in _ITEM_ICONS:
        fname = _ITEM_ICON_FILES.get(item_id)
        path = _ITEM_ICON_DIR / fname if fname else None
        _ITEM_ICONS[item_id] = _load_image(path) if path else None
    return _ITEM_ICONS[item_id]


def fit_icon(icon: pygame.Surface, size: int) -> pygame.Surface:
    """等比缩放图标到 size×size 透明画布并居中（最近邻，保持像素风）。"""
    w, h = icon.get_size()
    scale = size / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    canvas = pygame.Surface((size, size), pygame.SRCALPHA)
    canvas.blit(pygame.transform.scale(icon, (nw, nh)),
                ((size - nw) // 2, (size - nh) // 2))
    return canvas
