"""
把 src/ 下的 Python 模块转成 Obsidian 笔记，import 关系转成 [[双链]]。
生成后可以在 Obsidian 打开 vault 目录，用图谱视图查看依赖关系。
"""
import os
import re
import sys
from pathlib import Path

SRC_DIR = Path("src")
OUT_DIR = Path("docs/obsidian-vault")


def parse_imports(file_path: Path) -> list[str]:
    """
    解析 Python 文件的 import 语句，返回模块名列表（去 src. 前缀）。
    对 `from src.xxx import yyy` 形式做智能展开：
    - 如果 src.xxx.yyy 对应的文件存在，链接到它
    - 否则才链接到 src.xxx（包级别）
    """
    content = file_path.read_text(encoding="utf-8")
    modules = set()
    # from src.xxx import yyy[, zzz]
    for m in re.finditer(r"^from\s+(src[\.\w]+)\s+import\s+(.+)", content, re.MULTILINE):
        base = m.group(1)  # src.core
        imported = m.group(2).strip()
        # 拆分逗号，去掉 as 别名
        names = []
        for part in imported.split(","):
            part = part.strip().split(" as ")[0].strip()
            if part and not part.startswith("("):
                names.append(part)
        for name in names:
            # 尝试 src.xxx.yyy 是否对应实际文件
            candidate = f"{base}.{name}"
            candidate_rel = candidate.replace("src.", "", 1).replace(".", "/")
            candidate_path = SRC_DIR / f"{candidate_rel}.py"
            if candidate_path.exists():
                modules.add(candidate)
            else:
                # yyy 可能是变量/类而非模块，链接到包级别
                modules.add(base)
    # import src.xxx
    for m in re.finditer(r"^import\s+(src[\.\w]+)", content, re.MULTILINE):
        modules.add(m.group(1))
    return sorted(modules)


def module_to_note_name(module: str) -> str:
    """src.core.game → core-game"""
    return module.replace("src.", "").replace(".", "-")


def file_to_module(file_path: Path) -> str:
    """src/core/game.py → src.core.game"""
    rel = file_path.with_suffix("")
    parts = list(rel.parts)
    return ".".join(parts).replace("\\", ".")


def file_to_note_name(file_path: Path) -> str:
    """src/core/game.py → core-game"""
    return module_to_note_name(file_to_module(file_path))


def generate():
    if not SRC_DIR.exists():
        print(f"Error: {SRC_DIR} not found")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    notes_created = 0
    links_created = 0

    # 收集所有 .py 文件
    py_files = sorted(SRC_DIR.rglob("*.py"))

    for py_file in py_files:
        module = file_to_module(py_file)
        note_name = module_to_note_name(module)
        imports = parse_imports(py_file)

        # 按目录分组（用于 Obsidian 文件夹结构）
        rel_dir = py_file.parent.relative_to(SRC_DIR)
        out_subdir = OUT_DIR / rel_dir
        out_subdir.mkdir(parents=True, exist_ok=True)
        note_path = out_subdir / f"{note_name}.md"

        # 生成 frontmatter
        tags = list(rel_dir.parts) if rel_dir.parts else ["root"]
        frontmatter = "---\n"
        frontmatter += f"module: {module}\n"
        frontmatter += f"file: {py_file.as_posix()}\n"
        frontmatter += f"tags:\n"
        for t in tags:
            frontmatter += f"  - {t}\n"
        frontmatter += "---\n\n"

        # 标题
        body = f"# {note_name}\n\n"
        body += f"**源文件**: `{py_file.as_posix()}`\n\n"

        # 依赖关系（双链）
        if imports:
            body += "## 依赖\n\n"
            for imp in imports:
                target_note = module_to_note_name(imp)
                body += f"- [[{target_note}]]\n"
                links_created += 1
        else:
            body += "## 依赖\n\n（无依赖）\n"

        # 反向链接（稍后 Obsidian 会自动生成，这里标注）
        body += "\n## 被依赖\n\n（Obsidian 图谱视图自动生成）\n"

        note_path.write_text(frontmatter + body, encoding="utf-8")
        notes_created += 1
        print(f"  {note_name} → {note_path.relative_to(OUT_DIR)} ({len(imports)} deps)")

    # 生成 README
    readme = OUT_DIR / "README.md"
    readme.write_text(f"""# 代码依赖图谱

本 vault 由脚本自动生成，用于在 Obsidian 中可视化项目模块依赖关系。

- 笔记数: {notes_created}
- 链接数: {links_created}
- 源目录: `src/`

## 使用方法

1. 用 Obsidian 打开本目录作为 vault
2. 按 `Ctrl+G` 打开图谱视图
3. 力导向布局会自动排列模块位置
4. 点击节点可跳转到对应笔记

## 重新生成

```powershell
.venv\\Scripts\\python.exe docs\\generate_obsidian_vault.py
```
""", encoding="utf-8")

    print(f"\n完成: {notes_created} 个笔记, {links_created} 条链接")
    print(f"Vault 位置: {OUT_DIR.resolve()}")
    print(f"用 Obsidian 打开此目录即可查看图谱")


if __name__ == "__main__":
    generate()
