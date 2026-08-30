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

import sys
from pathlib import Path

import pygame

from src.core import config


def resource_root() -> Path:
    """资源根目录（项目根）。

    开发运行 = src/core/asset_manager.py 上两级；PyInstaller 打包后 =
    解压目录（sys._MEIPASS），资源经 --add-data 打包进 exe。
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def saves_root() -> Path:
    """存档目录：打包后放 exe 旁（_MEIPASS 临时目录会被清空导致丢档）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


# 项目 assets/images 根目录
_IMAGE_ROOT = resource_root() / "assets" / "images"


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
        self._actor_frames: dict[str, dict[str, list[pygame.Surface]]] = {}
        self._raw_frames: dict[str, list[pygame.Surface]] = {}

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

    def _load_raw_frames(self, rel: str) -> list[pygame.Surface]:
        """
        加载未处理的原始帧列表：
        - rel 是目录 → 加载其中 frame_*.png 按名排序
        - rel 是横向帧表 png → 帧数 = 宽 ÷ 高，subsurface 切帧
        """
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
        return raw

    def get_frames(self, rel: str) -> list[pygame.Surface]:
        """
        加载动画帧列表，独立裁剪缩放至 TILE_SIZE（单动画实体用）。

        注意：多动画实体请用 get_actor_frames，否则各动画独立缩放会
        因包围盒大小不同导致切换动画时角色视觉大小跳变。
        """
        if rel in self._frames:
            return self._frames[rel]
        ts = config.TILE_SIZE
        frames = [_convert(s) for s in _trim_and_fit(self._load_raw_frames(rel), ts)]
        self._frames[rel] = frames
        return frames

    def get_raw_frames(self, rel: str) -> list[pygame.Surface]:
        """
        加载原始帧（不裁剪、不缩放），带缓存。

        用于粒子特效层等自定尺寸素材：特效帧按原始像素尺寸渲染，
        居中叠加在实体格子上，覆盖范围由素材自身大小决定。
        """
        if rel not in self._raw_frames:
            self._raw_frames[rel] = self._load_raw_frames(rel)
        return self._raw_frames[rel]

    def get_actor_frames(self, anims: dict[str, str],
                         base: str = "idle") -> dict[str, list[pygame.Surface]]:
        """
        加载同一实体的多个动画，以基准动画（默认 idle 本体）高度统一缩放。

        各动画独立 trim+fit 时，动作幅度大的帧表（如狂暴攻击含跳起/
        武器挥舞轨迹）联合包围盒更大、缩放系数更小，角色本体被压小，
        切换动画时视觉上"突然缩小"。此方法以基准动画的包围盒高度计算
        统一缩放系数：基准动画满格显示，其他动画同比例缩放、本体大小
        与基准严格一致；大动作（跳起/横扫）超出瓦片的部分由动态加宽
        加高的画布承载，渲染时自然溢出格子。帧内容底边对齐（脚站地面
        位置稳定）。

        参数：
            anims: 动画名 → 帧表相对路径（如 {"idle": "entities/boss/Idle"}）
            base:  缩放基准动画名（该动画缩放后正好撑满瓦片高度）
        返回：动画名 → 缩放后的帧列表（素材缺失的动画不含在结果中）
        """
        key = "|".join(f"{k}:{v}" for k, v in sorted(anims.items())) + f"#{base}"
        if key in self._actor_frames:
            return self._actor_frames[key]

        # 加载各动画原始帧并计算帧表内联合包围盒
        raw: dict[str, list[pygame.Surface]] = {}
        boxes: dict[str, pygame.Rect] = {}
        max_h = 0
        for name, rel in anims.items():
            frames = self._load_raw_frames(rel)
            if not frames:
                continue
            raw[name] = frames
            rects: list[pygame.Rect] = []
            for s in frames:
                rects.extend(pygame.mask.from_surface(s).get_bounding_rects())
            if rects:
                box = rects[0].unionall(rects)
                boxes[name] = box
                max_h = max(max_h, box.h)
            else:
                # 全透明帧表：整帧回退，不参与缩放基准
                boxes[name] = frames[0].get_rect()

        size = config.TILE_SIZE
        result: dict[str, list[pygame.Surface]] = {}
        if max_h <= 0:  # 全部素材无有效内容：回退逐动画独立处理
            for name, frames in raw.items():
                result[name] = [_convert(s) for s in _trim_and_fit(frames, size)]
            self._actor_frames[key] = result
            return result

        # 缩放基准 = 指定动画（默认 idle）的包围盒高度；缺失时回退最大高度
        base_h = boxes[base].h if base in boxes else max_h
        scale = size / base_h
        for name, frames in raw.items():
            box = boxes[name]
            nh = max(1, round(box.h * scale))
            nw = max(1, round(box.w * scale))
            cw = max(size, nw)  # 画布加宽承载横向溢出（武器轨迹/冲击波）
            ch = max(size, nh)  # 画布加高承载纵向溢出（攻击跳起）
            out: list[pygame.Surface] = []
            for s in frames:
                canvas = pygame.Surface((cw, ch), pygame.SRCALPHA)
                cropped = s.subsurface(box).copy()
                # 底边对齐（脚踩格底）+ 水平居中：攻击跳起时角色向上伸展
                canvas.blit(pygame.transform.scale(cropped, (nw, nh)),
                            ((cw - nw) // 2, ch - nh))
                out.append(_convert(canvas))
            result[name] = out
        self._actor_frames[key] = result
        return result


# 全局单例：各实体直接 from src.core.asset_manager import assets
assets = AssetManager()
