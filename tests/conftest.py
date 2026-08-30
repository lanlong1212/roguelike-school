"""
pytest 全局配置。

必须在任何 pygame 导入之前设置无头环境变量：
- SDL_VIDEODRIVER=dummy：无显示环境（CI/无人值守）下创建 Surface 正常
- SDL_AUDIODRIVER=dummy：无音频设备时 mixer 不报错
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# 项目根加入 sys.path，保证 `from src...` 可导入
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
