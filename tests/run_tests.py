"""
零依赖测试运行器。

用法：python tests/run_tests.py
自动发现 tests/test_*.py 中的 test_* 函数并逐个执行。
兼容 pytest：安装 pytest 后也可直接 `python -m pytest tests/`。
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 无头环境（conftest 已不存在 pytest 场景，这里直接设置）
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


def main() -> int:
    tests_dir = Path(__file__).parent
    passed, failed = [], []
    for path in sorted(tests_dir.glob("test_*.py")):
        module_name = f"tests.{path.stem}"
        module = __import__(module_name, fromlist=["*"])
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            func = getattr(module, name)
            if not callable(func):
                continue
            full = f"{path.stem}::{name}"
            try:
                func()
                passed.append(full)
                print(f"  PASS {full}")
            except Exception:
                failed.append(full)
                print(f"  FAIL {full}")
                traceback.print_exc()
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
