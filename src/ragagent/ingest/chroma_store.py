"""Chroma 存储：langchain-chroma 封装，每库一个 collection（kb_<id>，cosine）。

嵌入由挂在 Chroma 上的 OpenAIEmbeddings（硅基流动 bge-m3）在 add_texts /
相似度查询时内部完成；关闭 anonymized_telemetry；metadata 值不能为 None，
None 字段直接省略。不缓存 Chroma 实例——测试通过
`chroma_store._client = None` 重置单例，实例缓存会破坏该契约。
"""

from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma

import ragagent.config as cfg
from ragagent.ingest.embeddings import make_embeddings

_client: chromadb.ClientAPI | None = None

_MAX_INPUT_CHARS = 4000  # 输入护栏
_SLICE = 512             # 分片写入：嵌入+向量内存有界（大文件支持）


def client():
    global _client
    if _client is None:
        cfg.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(cfg.CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def collection(kb_id: int) -> Chroma:
    return Chroma(
        collection_name=f"kb_{kb_id}",
        embedding_function=make_embeddings(),
        client=client(),
        collection_metadata={"hnsw:space": "cosine"},
        # 旧 collection 由 metadata hnsw:space 创建，configuration 里可能没有
        # 空间字段；显式给相关性函数 = 1 - 余弦距离，绕过探测。
        relevance_score_fn=lambda d: 1.0 - d,
    )


def count(kb_id: int) -> int:
    """库内向量条数；collection 不存在返回 0（不创建）。"""
    try:
        return client().get_collection(name=f"kb_{kb_id}").count()
    except Exception:  # noqa: BLE001 —— 不存在视为 0
        return 0


def delete_collection(kb_id: int) -> None:
    try:
        client().delete_collection(name=f"kb_{kb_id}")
    except Exception:  # noqa: BLE001 —— 集合不存在视为已删除
        pass


def delete_doc(kb_id: int, doc_id: int) -> None:
    collection(kb_id).delete(where={"doc_id": doc_id})


def add_chunks(
    kb_id: int,
    chunk_ids: list[int],
    texts: list[str],
    metadatas: list[dict],
) -> None:
    """分片写入（每片 _SLICE 条）：add_texts 内部先嵌入再写。

    任一片失败异常上抛——indexer 按 doc_id 调 delete_doc 全量清理，
    保持"整文档全有或全无"的无残留保证。
    """
    if not chunk_ids:
        return
    clean = [{k: v for k, v in m.items() if v is not None} for m in metadatas]
    guarded = [t[:_MAX_INPUT_CHARS] or " " for t in texts]
    col = collection(kb_id)  # 只取一次，避免每片重建 Chroma + embeddings
    for i in range(0, len(chunk_ids), _SLICE):
        col.add_texts(
            texts=guarded[i : i + _SLICE],
            metadatas=clean[i : i + _SLICE],
            ids=[str(x) for x in chunk_ids[i : i + _SLICE]],
        )
