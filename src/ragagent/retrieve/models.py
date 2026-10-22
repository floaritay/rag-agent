"""检索结果模型：Hit 统一表示向量/BM25/RRF/重排四路的输出。"""

from __future__ import annotations

from dataclasses import dataclass

import sqlite3


@dataclass
class Hit:
    chunk_id: int
    doc_id: int
    kb_id: int
    rel_path: str
    ordinal: int
    type: str  # text / table / code
    heading_path: str
    page: int | None
    text: str
    summary: str
    score: float = 0.0
    source: str = ""  # vector / bm25 / rrf / rerank（调试用）
    image_path: str | None = None  # 图片块：相对 storage 根的图片路径（回答附原图用）

    @property
    def location(self) -> str:
        """引用位置：页码优先，其次标题路径。"""
        if self.page is not None:
            return f"p.{self.page}"
        return self.heading_path or ""


def hit_from_row(row: sqlite3.Row, score: float, source: str) -> Hit:
    keys = row.keys()
    return Hit(
        chunk_id=int(row["id"]),
        doc_id=int(row["doc_id"]),
        kb_id=int(row["kb_id"]),
        rel_path=row["rel_path"],
        ordinal=int(row["ordinal"]),
        type=row["type"],
        heading_path=row["heading_path"] or "",
        page=row["page"],
        text=row["text"],
        summary=row["summary"] or "",
        score=score,
        source=source,
        image_path=row["image_path"] if "image_path" in keys else None,
    )
