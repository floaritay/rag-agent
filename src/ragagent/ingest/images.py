"""图片落盘与文字化编排：

过滤（去重/<2KB/上限）→ alt 或 OCR 出 caption → 写 storage/images/<kb>/<sha1(rel)>/
→ 构造 caption Block（携带 image_path）插入 parsed.blocks。

- 路径根用调用时求值的 images_root()（不加模块级常量，保测试隔离——storage.py 约定）；
- 目录键 = sha1(rel_path)：re-ingest 同目录覆盖、清理键就是 rel_path；
- 任何单图失败只 warn，绝不抛——图片通道不允许 fail 文档。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Callable

import ragagent.config as cfg
from ragagent.config import get_settings

from . import ocr
from .parsers import Block, ImageItem, ParsedDoc

MAX_IMAGES_PER_DOC = 20   # 兜底默认；实际以 .env 的 IMAGE_MAX_PER_DOC 为准（<=0 不限）
MIN_IMAGE_BYTES = 2048    # <2KB 视为装饰图标，跳过
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 单图发送上限 15MB：超大图跳过索引（请求体/耗时保护）


def images_root() -> Path:
    return cfg.STORAGE_DIR / "images"  # 调用时读模块属性（测试可 monkeypatch）


def _doc_key(rel_path: str) -> str:
    return hashlib.sha1(rel_path.replace("\\", "/").encode("utf-8")).hexdigest()[:16]


def images_doc_dir(kb_id: int, rel_path: str) -> Path:
    return images_root() / str(kb_id) / _doc_key(rel_path)


def image_rel_path(kb_id: int, rel_path: str, ordinal: int, ext: str) -> str:
    """入库 image_path：相对 storage 根的 POSIX 串（chunk.image_path 存此值）。"""
    return f"images/{kb_id}/{_doc_key(rel_path)}/{ordinal}.{ext}"


def remove_doc_images(kb_id: int, rel_path: str) -> None:
    shutil.rmtree(images_doc_dir(kb_id, rel_path), ignore_errors=True)


def remove_kb_images(kb_id: int) -> None:
    shutil.rmtree(images_root() / str(kb_id), ignore_errors=True)


def process_images(
    parsed: ParsedDoc,
    kb_id: int,
    rel_path: str,
    warn: Callable[[str], None],
) -> int:
    """执行过滤→落盘→caption→插块。返回 images_indexed；调用方负责 IMAGE_DESCRIBE 门控。"""
    if not parsed.images:
        return 0

    # 1) 过滤：文档内 sha 去重（保留首次）→ <2KB → >15MB → 张数上限（.env 可配）
    cap = get_settings().image_max_per_doc  # IMAGE_MAX_PER_DOC；<=0 不限
    seen: set[str] = set()
    kept: list[tuple[ImageItem, str]] = []
    for item in parsed.images:
        sha = hashlib.sha256(item.bytes).hexdigest()
        if sha in seen:
            warn(f"重复图片已跳过（#{item.ordinal + 1}）")
            continue
        seen.add(sha)
        if len(item.bytes) < MIN_IMAGE_BYTES:
            warn(f"图片小于 {MIN_IMAGE_BYTES}B 视为装饰图标，已跳过（#{item.ordinal + 1}）")
            continue
        if len(item.bytes) > MAX_IMAGE_BYTES:
            warn(
                f"图片超过 {MAX_IMAGE_BYTES // 1048576}MB 发送上限，已跳过索引"
                f"（#{item.ordinal + 1}）"
            )
            continue
        if cap > 0 and len(kept) >= cap:
            warn(f"超出单文档图片上限 {cap} 张，已截断（#{item.ordinal + 1}）")
            continue
        kept.append((item, sha))
    if not kept:
        return 0

    # 2) 落盘：先清目标目录（防旧版本残留），再逐张写
    doc_dir = images_doc_dir(kb_id, rel_path)
    shutil.rmtree(doc_dir, ignore_errors=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    # 3) caption + 块（事件表按 insert_at 合并，避免多次 list.insert 索引漂移）
    events: list[tuple[int, int, Block]] = []  # (insert_at, 序号, block)
    indexed = 0
    for n, (item, _sha) in enumerate(kept, 1):
        dest = doc_dir / f"{item.ordinal}.{item.ext}"
        try:
            dest.write_bytes(item.bytes)
        except OSError as e:
            warn(f"图片写盘失败已跳过（#{item.ordinal + 1}）：{e}")
            continue
        rel_img = image_rel_path(kb_id, rel_path, item.ordinal, item.ext)
        # caption = 图语义说明（alt / VLM 看图）+ OCR 逐字文字，两者互补：
        # 纯 OCR 对示意图只剩「a b」碎片，语义靠 describe_picture 补
        desc: str | None = None
        ocr_text: str | None = None
        if item.alt and len(item.alt.strip()) >= 8:
            desc = item.alt.strip()  # alt 够长直接当说明，省两次调用
        else:
            try:
                desc = ocr.describe_picture(item.bytes, item.ext)
            except Exception as e:  # noqa: BLE001 —— 说明失败只 warn
                warn(f"图片说明异常（#{item.ordinal + 1}）：{e}")
            try:
                ocr_text = ocr.describe_image(item.bytes, item.ext)
            except Exception as e:  # noqa: BLE001 —— OCR 绝不 fail 文档
                warn(f"OCR 异常（#{item.ordinal + 1}）：{e}")
        if desc and ocr_text:
            caption = f"{desc}（图中文字：{ocr_text}）"
        elif desc:
            caption = desc
        elif ocr_text:
            caption = ocr_text
        else:
            caption = "未能识别出文字"
            warn(f"图片说明与 OCR 均未返回内容（#{item.ordinal + 1}），caption 已用占位文本")
        block = Block(
            "text", f"【图{n}】{caption}",
            item.heading_path, item.page,
            image_path=rel_img,
        )
        events.append((item.insert_at, n, block))
        indexed += 1

    if events:
        events.sort(key=lambda e: (e[0], e[1]))
        merged: list[Block] = []
        ev_i = 0
        for pos, block in enumerate(parsed.blocks):
            while ev_i < len(events) and events[ev_i][0] <= pos:
                merged.append(events[ev_i][2])
                ev_i += 1
            merged.append(block)
        while ev_i < len(events):  # 尾部
            merged.append(events[ev_i][2])
            ev_i += 1
        parsed.blocks = merged
    return indexed
