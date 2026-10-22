"""生成演示文档到 knowledge_base/demo/（六格式样例 + legacy.doc 失败样例）。

用法：在已安装本项目的 Python 环境中运行 `python scripts/seed_demo.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from _samples import build_all  # noqa: E402


def main() -> None:
    demo = ROOT / "knowledge_base" / "demo"
    paths = build_all(demo)
    print(f"已在 {demo} 生成 {len(paths)} 个样例文件：")
    for p in paths:
        print(f"  - {p.name}")


if __name__ == "__main__":
    main()
