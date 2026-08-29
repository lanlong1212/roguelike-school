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
    - 加载后自动裁掉透明边距再等比放大至瓦片尺寸（素材画布常含大量
      透明留白，直接缩放会导致角色显示过小、看起来像色块）
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


def _trim_and_fit(raw: list[pygame.Surface], size: int) -> list[pygame.Surface]:
    """
    裁掉透明边距后等比缩放至 size×size 透明画布并居中。

    使用全部帧的联合非透明包围盒裁剪，保证帧间内容对齐不抖动；
    等比缩放避免角色被拉伸变形。
    """
    if not raw:
        return []
    # 联合包围盒：所有帧所有连通区域的并集
    rects: list[pygame.Rect] = []
    for s in raw:
        rects.extend(pygame.mask.from_surface(s).get_bounding_rects())
    if not rects:
        # 全透明素材，回退为直接缩放
        return [pygame.transform.scale(s, (size, size)) for s in raw]
    box = rects[0].unionall(rects)
    # 等比缩放至适配瓦片，居中放置
    bw, bh = box.w, box.h
    scale = min(size / bw, size / bh)
    nw, nh = max(1, round(bw * scale)), max(1, round(bh * scale))
    frames: list[pygame.Surface] = []
    for s in raw:
        canvas = pygame.Surface((size, size), pygame.SRCALPHA)
        cropped = s.subsurface(box).copy()
        canvas.blit(pygame.transform.scale(cropped, (nw, nh)),
                    ((size - nw) // 2, (size - nh) // 2))
        frames.append(canvas)
    return frames


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
        frames = [_convert(s) for s in _trim_and_fit(raw, ts)]
        self._frames[rel] = frames
        return frames


# 全局单例：各实体直接 from src.core.asset_manager import assets
assets = AssetManager()
