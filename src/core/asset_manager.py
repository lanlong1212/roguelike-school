"""
资源管理器模块。

功能说明：
    全局图片资源加载与缓存。支持两种帧来源：
    - 目录帧序列: player/idle/down → frame_000.png... 按文件名排序
    - 横向帧表:   skeleton/idle.png → 帧数 = 图宽 ÷ 图高（正方形帧）
    所有帧统一缩放至 TILE_SIZE 后缓存。

使用约定：
    - 相对路径基于 assets/images/（如 "player/idle/down"、"skeleton/idle"）
    - convert_alpha 在无显示环境（无头测试）下自动跳过
"""
from __future__ import annotations

from pathlib import Path

import pygame

from src.core import config

# 项目 assets/images 根目录（src/core/asset_manager.py → 上两级 → assets/images）
_IMAGE_ROOT = Path(__file__).resolve().parents[2] / "assets" / "images"


def _convert(surf: pygame.Surface) -> pygame.Surface:
    """有显示环境时 convert_alpha 加速，无头环境原样返回。"""
    if pygame.display.get_surface() is not None:
        return surf.convert_alpha()
    return surf


class AssetManager:
    """图片资源加载器。get_* 均带缓存，同一资源只加载一次。"""

    def __init__(self, image_root: Path = _IMAGE_ROOT):
        self._root = Path(image_root)
        self._images: dict[str, pygame.Surface] = {}
        self._frames: dict[str, list[pygame.Surface]] = {}

    # ========== 单张图 ==========

    def get_image(self, rel: str) -> pygame.Surface:
        """加载单张图片（相对 assets/images/），缓存后返回。"""
        if rel not in self._images:
            surf = pygame.image.load(str(self._root / rel)).convert_alpha() \
                if pygame.display.get_surface() is not None \
                else pygame.image.load(str(self._root / rel))
            self._images[rel] = surf
        return self._images[rel]

    # ========== 帧序列 ==========

    def get_frames(self, rel: str) -> list[pygame.Surface]:
        """
        加载动画帧列表，统一缩放至 TILE_SIZE：
        - rel 是目录 → 加载其中 frame_*.png 按名排序
        - rel 是横向帧表 png → 帧数 = 宽 ÷ 高，subsurface 切帧
        """
        if rel in self._frames:
            return self._frames[rel]

        base = self._root / rel
        # 无扩展名且不存在 → 尝试补 .png（帧表调用可省略扩展名）
        if not base.exists() and base.suffix == "":
            base = base.with_name(base.name + ".png")
        raw: list[pygame.Surface] = []
        if base.is_dir():
            files = sorted(base.glob("frame_*.png"))
            raw = [pygame.image.load(str(f)) for f in files]
        elif base.is_file():
            sheet = pygame.image.load(str(base))
            h = sheet.get_height()
            n = sheet.get_width() // h  # 正方形帧约定
            raw = [sheet.subsurface((i * h, 0, h, h)) for i in range(n)]

        ts = config.TILE_SIZE
        frames = [
            _convert(pygame.transform.scale(s, (ts, ts))) for s in raw
        ]
        self._frames[rel] = frames
        return frames


# 全局单例：各实体直接 from src.core.asset_manager import assets
assets = AssetManager()
