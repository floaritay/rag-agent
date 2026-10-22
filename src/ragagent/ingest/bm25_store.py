"""BM25 索引：每库一份 pickle（storage/bm25/kb_<id>.pkl）。

存的是构建好的 langchain BM25Retriever（过滤式子类）——基于 meta.db 全量
重建（几百份规模秒级）；中文用 jieba 分词。早期格式 `{"ids","bm25"}` pickle
由 load() 识别后透明重建。查询接口（load）供检索层使用。
"""

from __future__ import annotations

import pickle
from pathlib import Path

import jieba
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

import ragagent.config as cfg
from ragagent import storage


class FilteredBM25Retriever(BM25Retriever):
    """只保留 score>0 的命中（原实现语义；vanilla get_top_n 会混入非正分）。"""

    def _get_relevant_documents(self, query, *, run_manager):
        scores = self.vectorizer.get_scores(self.preprocess_func(query))
        pairs = sorted(
            ((i, float(s)) for i, s in enumerate(scores) if s > 0),
            key=lambda p: p[1],
            reverse=True,
        )
        return [self.docs[i] for i, _ in pairs[: self.k]]


def _path(kb_id: int) -> Path:
    return cfg.BM25_DIR / f"kb_{kb_id}.pkl"


def _tokens(text: str) -> list[str]:
    return [w for w in jieba.lcut(text.lower()) if w.strip()]


def rebuild(kb_id: int) -> int:
    """从 meta.db 全量重建某库的 BM25 检索器，返回索引条数。"""
    rows = list(storage.iter_kb_chunks(kb_id))
    cfg.BM25_DIR.mkdir(parents=True, exist_ok=True)
    if not rows:
        _path(kb_id).unlink(missing_ok=True)
        return 0
    docs = [
        Document(
            page_content=r["text"],
            id=str(r["id"]),
            metadata={"chunk_id": int(r["id"])},
        )
        for r in rows
    ]
    retriever = FilteredBM25Retriever.from_documents(docs, preprocess_func=_tokens)
    with open(_path(kb_id), "wb") as f:
        pickle.dump(retriever, f)
    return len(rows)


def load(kb_id: int) -> FilteredBM25Retriever | None:
    p = _path(kb_id)
    if not p.exists():
        return None
    with open(p, "rb") as f:
        data = pickle.load(f)
    if isinstance(data, dict):  # 旧格式 {"ids","bm25"} → 透明重建
        rebuild(kb_id)
        if not p.exists():  # 重建后为空（无块）
            return None
        with open(p, "rb") as f:
            data = pickle.load(f)
    return data


def delete(kb_id: int) -> None:
    _path(kb_id).unlink(missing_ok=True)
