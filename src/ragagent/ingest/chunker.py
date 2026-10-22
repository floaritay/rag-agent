"""结构感知分块：

- 文本块：相同标题路径的相邻段落合并到 chunk_size，超长按段落优先、字符兜底切分（带 overlap）；
- 表格块：整块保留（检索命中后不切分）；超长表格按数据行切分且每块重复表头；
- 代码块：整块保留，超长按字符切分。
"""

from __future__ import annotations

from dataclasses import dataclass

from .parsers import ParsedDoc

TABLE_PIECE_LIMIT = 4000  # 超过此长度的表格按行切分（嵌入模型输入限制）


@dataclass
class Chunk:
    type: str
    text: str
    heading_path: str
    page: int | None
    line_start: int | None
    line_end: int | None
    summary: str
    image_path: str | None = None  # caption 块携带的图片（相对 storage 根）


def chunk_document(parsed: ParsedDoc, size: int = 500, overlap: int = 80) -> list[Chunk]:
    out: list[Chunk] = []

    cur_hp: list[str] | None = None
    cur_meta: tuple[int | None, int | None, int | None] = (None, None, None)
    cur_img: str | None = None  # 图片 caption 块自成一组，不与普通文本合并
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, cur_hp, cur_meta, cur_img
        if buf:
            page, ls, le = cur_meta
            merged = "\n\n".join(buf)
            ctype = "image" if cur_img else "text"  # 图片 caption 块类型标为「图片」
            for piece in _split_text(merged, size, overlap):
                out.append(
                    Chunk(ctype, piece, " > ".join(cur_hp or []), page, ls, le,
                          _summary(piece), image_path=cur_img)
                )
            buf = []
            cur_hp = None
            cur_img = None

    for b in parsed.blocks:
        if b.type == "text":
            same_group = (
                cur_hp is not None and b.heading_path == cur_hp
                and b.image_path == cur_img
            )
            if not same_group:
                flush()
                cur_hp = list(b.heading_path)
                cur_meta = (b.page, b.line_start, b.line_end)
                cur_img = b.image_path
            buf.append(b.text)
        elif b.type == "table":
            flush()
            for piece in _split_table(b.text, TABLE_PIECE_LIMIT):
                out.append(
                    Chunk("table", piece, " > ".join(b.heading_path), b.page,
                          b.line_start, b.line_end, _summary(piece))
                )
        else:  # code
            flush()
            pieces = (
                _split_chars(b.text, size * 2, overlap)
                if len(b.text) > size * 2
                else [b.text]
            )
            for piece in pieces:
                out.append(
                    Chunk("code", piece, " > ".join(b.heading_path), b.page,
                          b.line_start, b.line_end, _summary(piece))
                )
    flush()
    return out


def _summary(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line[:60]


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    cur = ""
    for seg in text.split("\n\n"):
        if len(seg) > size:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_split_chars(seg, size, overlap))
        elif not cur:
            cur = seg
        elif len(cur) + 2 + len(seg) <= size:
            cur += "\n\n" + seg
        else:
            chunks.append(cur)
            cur = seg
    if cur:
        chunks.append(cur)
    return chunks


def _split_chars(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    return [text[i : i + size] for i in range(0, len(text), step)]


def _split_table(md: str, limit: int) -> list[str]:
    """超长表格按数据行切分，每块重复表头与分隔行，保证每块可独立理解。"""
    if len(md) <= limit:
        return [md]
    lines = md.splitlines()
    if len(lines) < 3:
        return [md]
    head, body = lines[:2], lines[2:]
    out: list[str] = []
    cur: list[str] = []
    for line in body:
        if sum(len(l) for l in cur) + len(line) > limit - len("\n".join(head)):
            if cur:
                out.append("\n".join(head + cur))
                cur = []
        cur.append(line)
    if cur:
        out.append("\n".join(head + cur))
    return out
