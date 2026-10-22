"""Retriever 装饰器：为检索结果回填 chunk_id metadata。

EnsembleRetriever 按 `metadata["chunk_id"]` 去重融合，但历史存量向量的
metadata 里没有 chunk_id（chroma 的 id 本身即 chunk id）。在检索时从
`doc.id` 回填，避免全量重嵌入。
"""

from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class ChunkIdEnrichedRetriever(BaseRetriever):
    """包一层任意 retriever，保证每个 Document 的 metadata 带 chunk_id。"""

    inner: BaseRetriever

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        docs = self.inner.invoke(
            query, config={"callbacks": run_manager.get_child()}
        )
        for d in docs:
            if "chunk_id" not in d.metadata and d.id is not None:
                d.metadata["chunk_id"] = int(d.id)
        return docs
