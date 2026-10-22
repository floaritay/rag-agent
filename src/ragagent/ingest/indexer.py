"""入库编排：sha256 增量 → 解析 → 分块 → 写存储（meta.db / Chroma，嵌入由
langchain-chroma 内部完成 / BM25）。

单文件失败不中断整批，全部汇总进 IngestReport。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import ragagent.config as cfg
from ragagent.storage import get_document, get_kb, replace_chunks, upsert_document

from . import bm25_store, chroma_store, parsers
from . import images as image_store
from .chunker import chunk_document
from .mineru import is_scanned_pdf, mineru_available, parse_with_mineru
from .parsers import UnsupportedFormatError


@dataclass
class FileResult:
    rel_path: str
    status: str  # ok / skipped / failed
    error: str | None = None
    chunks: int = 0


@dataclass
class IngestReport:
    kb_name: str
    total: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    chunks_added: int = 0
    images_found: int = 0
    images_indexed: int = 0
    items: list[FileResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kb_name": self.kb_name,
            "total": self.total,
            "ok": self.ok,
            "skipped": self.skipped,
            "failed": self.failed,
            "chunks_added": self.chunks_added,
            "images_found": self.images_found,
            "images_indexed": self.images_indexed,
            "items": [
                {"rel_path": i.rel_path, "status": i.status, "error": i.error, "chunks": i.chunks}
                for i in self.items
            ],
            "warnings": self.warnings,
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def kb_root(kb) -> Path:
    """库根目录（供管理路由复用；相对路径基于项目根）。"""
    p = Path(kb.path)
    return p if p.is_absolute() else cfg.PROJECT_ROOT / p


def _list_files(scan_root: Path, kb_root: Path) -> list[tuple[Path, str]]:
    """返回 (文件绝对路径, 相对库根的 posix 路径)。"""
    if scan_root.is_file():
        return [(scan_root, scan_root.relative_to(kb_root).as_posix())]
    out = []
    for p in sorted(scan_root.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            out.append((p, p.relative_to(kb_root).as_posix()))
    return out


def ingest(
    kb_id: int,
    target: Path | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> IngestReport:
    kb = get_kb(kb_id)
    if kb is None:
        raise ValueError(f"知识库 {kb_id} 不存在")
    root = kb_root(kb)
    scan_root = target.resolve() if target else root
    files = _list_files(scan_root, root)

    report = IngestReport(kb_name=kb.name)
    chunk_cfg = cfg.load_app_config().chunking

    for i, (abs_path, rel) in enumerate(files):
        if on_progress is not None:  # skipped/failed 也推进进度
            on_progress({"done": i, "total": len(files), "file": rel})
        report.total += 1
        sha = _sha256(abs_path)
        mtime = abs_path.stat().st_mtime
        prev = get_document(kb_id, rel)

        # 增量：未变更直接跳过
        if prev is not None and prev["sha256"] == sha and prev["status"] == "ok":
            report.skipped += 1
            report.items.append(FileResult(rel, "skipped"))
            continue

        # 解析（doc/ppt 在此抛 UnsupportedFormatError）
        try:
            parsed = parsers.parse(abs_path)
        except Exception as e:  # noqa: BLE001
            err = str(e)
            upsert_document(kb_id, rel, mtime, sha, abs_path.suffix.lower(),
                            "failed", err, 0)
            if prev is not None and prev["status"] == "ok":
                chroma_store.delete_doc(kb_id, prev["id"])
            image_store.remove_doc_images(kb_id, rel)
            report.failed += 1
            report.items.append(FileResult(rel, "failed", err))
            continue

        # 扫描件分流：无文本 PDF → MinerU 云解析；失败/无密钥退化并记 warning
        if abs_path.suffix.lower() == ".pdf" and is_scanned_pdf(abs_path):
            if mineru_available():
                try:
                    parsed = parse_with_mineru(abs_path)
                except Exception as me:  # noqa: BLE001 —— 退化为原解析（近似空文本）
                    parsed.warnings.append(f"MinerU 解析失败，退化为原解析：{me}")
            else:
                parsed.warnings.append(
                    "扫描件需配置 MinerU（.env 的 MinerU= 密钥）才能提取文字入库"
                )

        # 图片通道（A）：过滤→落盘→OCR→caption 插块——全程在任何 DB 变更之前；
        # 单图/通道任何异常只记 warning，绝不 fail 文档
        images_indexed = 0
        if cfg.get_settings().image_describe and parsed.images:
            try:
                images_indexed = image_store.process_images(
                    parsed, kb_id, rel,
                    warn=lambda w: report.warnings.append(f"{rel}：{w}"),
                )
            except Exception as ie:  # noqa: BLE001
                report.warnings.append(f"{rel}：图片处理失败（已跳过图片）：{ie}")

        # 解析成功：清掉旧版本（meta 行 + 旧向量）
        if prev is not None:
            chroma_store.delete_doc(kb_id, prev["id"])

        chunks = chunk_document(parsed, chunk_cfg.chunk_size, chunk_cfg.overlap)
        chunk_dicts = [
            {
                "type": c.type,
                "text": c.text,
                "heading_path": c.heading_path,
                "page": c.page,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "summary": c.summary,
                "image_path": c.image_path,
            }
            for c in chunks
        ]

        # 写存储：meta → chroma（add_texts 内部先嵌入再写，嵌入失败零写入；
        # bm25 最后整库重建）。单文件失败不中断整批。
        doc_id: int | None = None
        try:
            doc_id = upsert_document(kb_id, rel, mtime, sha, abs_path.suffix.lower(),
                                     "ok", None, parsed.image_count)
            chunk_ids = replace_chunks(kb_id, doc_id, chunk_dicts)
            chroma_store.add_chunks(
                kb_id,
                chunk_ids,
                [c["text"] for c in chunk_dicts],
                [
                    {
                        "doc_id": doc_id,
                        "ordinal": i,
                        "type": c["type"],
                        "heading_path": c["heading_path"],
                        "page": c["page"],
                        "rel_path": rel,
                    }
                    for i, c in enumerate(chunk_dicts)
                ],
            )
        except Exception as e:  # noqa: BLE001
            err = f"索引写入失败：{e}"
            if doc_id is not None:
                chroma_store.delete_doc(kb_id, doc_id)  # 清掉可能的残留向量
            # 状态 failed：delete→insert 级联删除 chunk 行，终态 = 无块无向量
            upsert_document(kb_id, rel, mtime, sha, abs_path.suffix.lower(),
                            "failed", err, parsed.image_count)
            image_store.remove_doc_images(kb_id, rel)
            report.failed += 1
            report.items.append(FileResult(rel, "failed", err))
            continue

        report.ok += 1
        report.chunks_added += len(chunk_ids)
        report.images_found += parsed.image_count
        report.images_indexed += images_indexed
        report.warnings.extend(f"{rel}：{w}" for w in parsed.warnings)
        report.items.append(FileResult(rel, "ok", chunks=len(chunk_ids)))

    bm25_store.rebuild(kb_id)
    if on_progress is not None:  # 终帧：BM25 全量重建可能耗数秒，给 UI 一个完成 tick
        on_progress({"done": len(files), "total": len(files), "file": ""})
    return report


def reset_kb(kb_id: int) -> None:
    """清空某库的全部索引数据（rebuild 前置步骤；不动原始文件）。

    保留 kb 注册行（不清后重建）——kb_id 稳定，入库期间的状态轮询与
    前端引用不会因重建而 404。
    """
    from ragagent.storage import clear_documents, get_kb

    if get_kb(kb_id) is None:
        return
    clear_documents(kb_id)  # 级联删除 document 行与 chunk 行
    chroma_store.delete_collection(kb_id)
    bm25_store.delete(kb_id)
    image_store.remove_kb_images(kb_id)
