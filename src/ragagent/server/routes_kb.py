"""知识库管理与入库 REST API（M1）。

config.yaml 是知识库注册的源头，meta.db 同步镜像；删除知识库只删注册与索引，
不动库目录中的原始文件。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ragagent.config as cfg
from ragagent.config import KBEntry, load_app_config, save_app_config
from ragagent.ingest import bm25_store, chroma_store, indexer
from ragagent.ingest.images import images_root, remove_doc_images, remove_kb_images
from ragagent.ingest.indexer import kb_root
from ragagent.server import jobs
from ragagent.storage import (
    delete_document as storage_delete_document,
)
from ragagent.storage import (
    delete_kb as storage_delete_kb,
)
from ragagent.storage import (
    get_document_by_id,
    get_kb,
    kb_stats,
    list_chunks_by_doc,
    list_documents,
    list_kbs,
    upsert_kb,
)

router = APIRouter(prefix="/api")

_NAME_RE = re.compile(r"[\w\u4e00-\u9fff-]+")


class KBCreate(BaseModel):
    name: str
    path: str | None = None


class IngestRequest(BaseModel):
    path: str | None = None  # 相对库根目录的子目录或文件；空 = 整库


def _get_kb_or_404(kb_id: int):
    kb = get_kb(kb_id)
    if kb is None:
        raise HTTPException(404, f"知识库 {kb_id} 不存在")
    return kb


@router.get("/kb")
def list_kb_endpoint():
    return [
        {
            "id": kb.id,
            "name": kb.name,
            "path": kb.path,
            "stats": kb_stats(kb.id),
        }
        for kb in list_kbs()
    ]


@router.post("/kb", status_code=201)
def create_kb(body: KBCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name 不能为空")
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(422, "name 仅限中文/字母/数字/下划线/连字符")
    app_cfg = load_app_config()
    if any(kb.name == name for kb in app_cfg.knowledge_bases):
        raise HTTPException(409, f"知识库 {name} 已注册")

    rel_path = body.path or f"knowledge_base/{name}"
    root = Path(rel_path)
    root = root if root.is_absolute() else cfg.PROJECT_ROOT / root
    root.mkdir(parents=True, exist_ok=True)

    app_cfg.knowledge_bases.append(
        KBEntry(name=name, path=rel_path)
    )
    save_app_config(app_cfg)
    kb_id = upsert_kb(name, rel_path)
    return {"id": kb_id, "name": name, "path": rel_path}


@router.delete("/kb/{kb_id}")
def delete_kb_endpoint(kb_id: int):
    """删除知识库：注册 + 索引 + 图片 + **库目录原始文件**（见下安全护栏）。"""
    if jobs.is_busy():
        raise HTTPException(409, "入库任务执行中，请稍后再试")
    kb = _get_kb_or_404(kb_id)
    app_cfg = load_app_config()
    app_cfg.knowledge_bases = [k for k in app_cfg.knowledge_bases if k.name != kb.name]
    save_app_config(app_cfg)
    storage_delete_kb(kb_id)
    chroma_store.delete_collection(kb_id)
    bm25_store.delete(kb_id)
    remove_kb_images(kb_id)

    # 删除磁盘文件：仅当库目录严格位于 knowledge_base/ 之下（防自定义 path 误删别处；
    # 也挡住指向 knowledge_base 根/项目根的病态配置）
    root = kb_root(kb).resolve()
    base = cfg.KNOWLEDGE_BASE_DIR.resolve()
    files_removed = False
    note = "已删除注册、索引与库目录中的全部原始文件"
    if root == base:
        note = "库目录指向 knowledge_base 根，出于安全未删除任何磁盘文件（仅删注册与索引）"
    elif not root.is_relative_to(base):
        note = "库目录不在 knowledge_base/ 之下，出于安全仅删除注册与索引（原始文件保留）"
    else:
        try:
            shutil.rmtree(root)
            files_removed = True
        except OSError as e:
            note = f"注册与索引已删；磁盘文件删除失败：{e}"
    return {"deleted": kb.name, "files_removed": files_removed, "note": note}


@router.post("/kb/{kb_id}/ingest", status_code=202)
def ingest_endpoint(kb_id: int, body: IngestRequest | None = None):
    """启动后台入库（202）；path 校验保持同步——无效参数立即 422/404。"""
    kb = _get_kb_or_404(kb_id)
    target = None
    if body and body.path:
        root = kb_root(kb).resolve()
        given = Path(body.path)
        target = given.resolve() if given.is_absolute() else (root / given).resolve()
        if target != root and root not in target.parents:
            raise HTTPException(422, "path 必须位于库目录内")
        if not target.exists():
            raise HTTPException(404, f"路径不存在：{target}")
    ok = jobs.try_start(
        kb_id, "ingest",
        lambda on_p: indexer.ingest(kb_id, target, on_progress=on_p).as_dict(),
    )
    if not ok:
        raise HTTPException(409, "已有入库任务在执行")
    return {"status": "running", "kind": "ingest", "kb_id": kb_id}


@router.get("/kb/{kb_id}/documents")
def documents_endpoint(kb_id: int):
    kb = _get_kb_or_404(kb_id)
    root = kb_root(kb)
    out = []
    for r in list_documents(kb_id):
        row = dict(r)
        try:
            row["size"] = (root / row["rel_path"]).stat().st_size
        except OSError:  # 文件缺失
            row["size"] = None
        out.append(row)
    return out


@router.get("/kb/{kb_id}/documents/{doc_id}/chunks")
def document_chunks_endpoint(kb_id: int, doc_id: int):
    """切分效果预览：某文档的全部分块 + 当前切分参数（chunk_size/overlap）。"""
    _get_kb_or_404(kb_id)
    d = get_document_by_id(doc_id)
    if d is None or d["kb_id"] != kb_id:
        raise HTTPException(404, "文档不存在")
    conf = load_app_config().chunking
    chunks = [
        {
            "ordinal": c["ordinal"],
            "type": c["type"],
            "heading_path": c["heading_path"],
            "page": c["page"],
            "line_start": c["line_start"],
            "line_end": c["line_end"],
            "text": c["text"],
            "length": len(c["text"]),
            "summary": c["summary"],
            "image_path": c["image_path"],
        }
        for c in list_chunks_by_doc(doc_id)
    ]
    return {
        "chunk_size": conf.chunk_size,
        "overlap": conf.overlap,
        "count": len(chunks),
        "chunks": chunks,
    }


@router.get("/images")
def get_image(path: str):
    """服务已入库图片字节（引用来源展示用）。

    path = chunk.image_path（storage 相对 POSIX 串，如 images/1/ab/0.png）。
    路径守卫：解析后必须位于 storage/images/ 之下且是文件，其余 404——
    .env/meta.db/库目录一律不可达。
    """
    root = images_root().resolve()
    try:
        target = (cfg.STORAGE_DIR / path).resolve()
    except (OSError, ValueError):
        raise HTTPException(404, "图片不存在")
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "图片不存在")
    return FileResponse(target)


@router.delete("/kb/{kb_id}/documents/{doc_id}")
def delete_document_endpoint(kb_id: int, doc_id: int):
    """删除文档：磁盘原始文件 + 全部索引数据（meta/chunks/向量/BM25）。"""
    if jobs.is_busy():
        raise HTTPException(409, "入库任务执行中，请稍后再试")
    kb = _get_kb_or_404(kb_id)
    d = get_document_by_id(doc_id)
    if d is None or d["kb_id"] != kb_id:
        raise HTTPException(404, "文档不存在")

    # 先删磁盘文件（路径守卫防穿越；文件已缺失视为无事），失败则不动索引便于重试
    root = kb_root(kb).resolve()
    target = (root / d["rel_path"]).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(422, "rel_path 越出库目录，拒绝删除")
    try:
        target.unlink()
        file_removed = True
    except FileNotFoundError:
        file_removed = False
    except OSError as e:
        raise HTTPException(409, f"磁盘文件删除失败（索引未动）：{e}")

    storage_delete_document(kb_id, d["rel_path"])
    chroma_store.delete_doc(kb_id, doc_id)
    remove_doc_images(kb_id, d["rel_path"])
    bm25_store.rebuild(kb_id)
    return {"deleted": d["rel_path"], "file_removed": file_removed}


@router.post("/kb/{kb_id}/upload", status_code=202)
async def upload_endpoint(kb_id: int, files: list[UploadFile] = File(...)):
    """上传文件（流式写盘）→ 启动后台入库（202）。报告经 ingest-status 轮询获取。"""
    kb = _get_kb_or_404(kb_id)
    if jobs.is_busy():  # 先于落盘拒绝，避免忙时留下文件
        raise HTTPException(409, "已有入库任务在执行")
    root = kb_root(kb)
    root.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    skipped_names: list[str] = []
    for f in files:
        name = Path(f.filename or "").name  # 去掉路径成分
        if not name or name.startswith("."):
            skipped_names.append(f.filename or "")
            continue
        dest = root / name
        # 点前缀临时文件（_list_files 跳过点开头）→ 流式写 → 原子落位；
        # 客户端中断不会在库目录留下截断文件
        tmp = root / f".{name}.uploading"
        try:
            with open(tmp, "wb") as out:
                while chunk := await f.read(1 << 20):
                    out.write(chunk)
            tmp.replace(dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        saved.append(name)

    def work(on_p: Callable[[dict], None]) -> dict:
        report = indexer.ingest(kb_id, None, on_progress=on_p).as_dict()
        report["uploaded"] = saved
        if skipped_names:
            report["warnings"].append(f"已跳过非法文件名：{skipped_names}")
        return report

    if not jobs.try_start(kb_id, "upload", work):
        # 极窄竞态（保存与启动之间他人抢到任务）：文件已落盘，下次入库自动收编
        raise HTTPException(409, "已有入库任务在执行")
    return {"status": "running", "kind": "upload", "kb_id": kb_id, "uploaded": saved}


@router.post("/kb/{kb_id}/rebuild", status_code=202)
def rebuild_endpoint(kb_id: int):
    """清空索引并全量重建（后台执行；空索引窗口完全在 running 内）。"""
    _get_kb_or_404(kb_id)

    def work(on_p: Callable[[dict], None]) -> dict:
        indexer.reset_kb(kb_id)
        return indexer.ingest(kb_id, None, on_progress=on_p).as_dict()

    if not jobs.try_start(kb_id, "rebuild", work):
        raise HTTPException(409, "已有入库任务在执行")
    return {"status": "running", "kind": "rebuild", "kb_id": kb_id}


@router.get("/kb/{kb_id}/ingest-status")
def ingest_status_endpoint(kb_id: int):
    """入库任务状态：idle / running（done,total,file 实时）/ done|error（report）。"""
    _get_kb_or_404(kb_id)
    return jobs.status_for(kb_id)


@router.get("/kb/{kb_id}/stats")
def stats_endpoint(kb_id: int):
    kb = _get_kb_or_404(kb_id)
    stats = kb_stats(kb_id)
    root = kb_root(kb)
    size = 0
    if root.is_dir():
        for f in root.rglob("*"):
            if f.is_file():
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
    stats["size_bytes"] = size
    return stats
