"""扫描件 PDF 解析通道（MinerU 云，mineru-open-sdk）：

版面分析 + OCR + 公式 + 表格 + 抽图一体。仅用于「扫描/无文本 PDF」；
有文本层的原生 PDF 走 parsers.parse_pdf 快路径。

- 协议：SDK `MinerU(token, base_url).extract(path)` → v4 云（JSON+zip），
  MINERU_BASE_URL 可覆盖私有部署（v4 兼容端点）；密钥来自 .env 的 MinerU= 键。
- v1 局限：markdown 产出无页码 → 图片块挂 heading=["附图"] 以满足引用位置校验
  （_loc_matches 只认 p.N 或标题子串）；content_list 页码映射列为 v1.1 升级项。
"""

from __future__ import annotations

from pathlib import Path

from ragagent.config import Settings, get_settings

from .parsers import ImageItem, ParsedDoc, _blocks_from_lines

SCANNED_AVG_CHARS = 80     # 每页平均文本 < 此值视为扫描件
_SAMPLE_PAGES = 10         # 判定只抽样前 N 页（大文档快扫）
_TIMEOUT = 300


def is_scanned_pdf(path: Path) -> bool:
    """扫描/无文本 PDF 判定：抽样页平均可提取文本 < SCANNED_AVG_CHARS。"""
    try:
        import pymupdf

        with pymupdf.open(str(path)) as pdf:
            if pdf.page_count == 0:
                return False
            pages = list(range(min(_SAMPLE_PAGES, pdf.page_count)))
            total = sum(len(pdf[p].get_text().strip()) for p in pages)
            return (total / len(pages)) < SCANNED_AVG_CHARS
    except Exception:  # noqa: BLE001 —— 判定失败按原生处理
        return False


def mineru_available(s: Settings | None = None) -> bool:
    return (s or get_settings()).mineru_configured


def parse_with_mineru(path: Path, s: Settings | None = None) -> ParsedDoc:
    """云端解析扫描件 → ParsedDoc（markdown 共用 _blocks_from_lines + images）。

    失败抛 RuntimeError，由调用方（indexer）降级为原解析并记 warning。
    """
    s = s or get_settings()
    try:
        from mineru import MinerU
    except ImportError as e:  # noqa: TRY003
        raise RuntimeError(f"mineru-open-sdk 未安装：{e}") from e

    with MinerU(
        token=s.mineru_api_key,
        base_url=s.mineru_base_url or None or "https://mineru.net/api/v4",
    ) as client:
        result = client.extract(str(path), timeout=_TIMEOUT)

    if result.state != "done":
        raise RuntimeError(
            f"MinerU 解析未完成（{result.state}）：{result.error or result.err_code or '未知错误'}"
        )
    md = result.markdown or ""
    if not md.strip() and not result.images:
        raise RuntimeError("MinerU 返回空结果")

    doc = ParsedDoc()
    doc.blocks = _blocks_from_lines(md.splitlines())
    anchor = len(doc.blocks)  # v1：图片统一挂尾（heading=附图，可被引用校验接受）
    for i, im in enumerate(result.images or []):
        name = im.name or f"{i}.png"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
        if ext == "jpg":
            ext = "jpeg"
        doc.images.append(ImageItem(
            bytes=im.data,
            ext=ext,
            page=None,
            heading_path=["附图"],
            ordinal=i,
            alt="",
            insert_at=anchor,
        ))
    return doc
