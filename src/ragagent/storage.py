"""SQLite 元数据层（storage/meta.db）：kb / document / chunk 三表。

路径在调用时从 ragagent.config 读取（便于测试替换）；每个操作独立开连接，
WAL 模式，FastAPI 单进程足够。
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Iterator

import ragagent.config as cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  path TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS document(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kb_id INTEGER NOT NULL REFERENCES kb(id) ON DELETE CASCADE,
  rel_path TEXT NOT NULL,
  mtime REAL NOT NULL,
  sha256 TEXT NOT NULL,
  parser TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  error TEXT,
  image_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(kb_id, rel_path)
);
CREATE TABLE IF NOT EXISTS chunk(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  kb_id INTEGER NOT NULL,
  ordinal INTEGER NOT NULL,
  type TEXT NOT NULL,
  heading_path TEXT NOT NULL DEFAULT '',
  page INTEGER,
  line_start INTEGER,
  line_end INTEGER,
  text TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  image_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_kb ON document(kb_id);
CREATE TABLE IF NOT EXISTS session(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL DEFAULT '新对话',
  kb_id INTEGER REFERENCES kb(id) ON DELETE SET NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS message(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  reasoning TEXT,
  tools TEXT,
  citations TEXT,
  created_at REAL NOT NULL,
  UNIQUE(session_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_message_session ON message(session_id);
CREATE INDEX IF NOT EXISTS idx_session_updated ON session(updated_at);
CREATE TABLE IF NOT EXISTS memory(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'fact',
  content TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
"""


@dataclass
class KBRow:
    id: int
    name: str
    path: str


@dataclass
class SessionRow:
    id: int
    title: str
    kb_id: int | None
    created_at: float
    updated_at: float
    message_count: int = 0


@dataclass
class MessageRow:
    id: int
    ordinal: int
    role: str
    content: str
    reasoning: str | None
    tools: list | None
    citations: list | None
    created_at: float


@dataclass
class MemoryRow:
    id: int
    kind: str
    content: str
    tags: str
    created_at: float
    updated_at: float


def _connect() -> sqlite3.Connection:
    cfg.META_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.META_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.executescript(SCHEMA)
        # 迁移：老 message 表缺 reasoning 列（CREATE TABLE IF NOT EXISTS 不会加列）
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(message)")}
        if "reasoning" not in cols:
            conn.execute("ALTER TABLE message ADD COLUMN reasoning TEXT")
        # 迁移：老 chunk 表缺 image_path 列（图片通道）
        chunk_cols = {r["name"] for r in conn.execute("PRAGMA table_info(chunk)")}
        if "image_path" not in chunk_cols:
            conn.execute("ALTER TABLE chunk ADD COLUMN image_path TEXT")


# ---------- kb ----------

def upsert_kb(name: str, path: str) -> int:
    with closing(_connect()) as conn, conn:
        conn.execute(
            """INSERT INTO kb(name, path, created_at) VALUES(?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET path=excluded.path""",
            (name, path, time.time()),
        )
        row = conn.execute("SELECT id FROM kb WHERE name=?", (name,)).fetchone()
        return int(row["id"])


def _to_kb(row: sqlite3.Row) -> KBRow:
    return KBRow(int(row["id"]), row["name"], row["path"])


def list_kbs() -> list[KBRow]:
    with closing(_connect()) as conn:
        return [_to_kb(r) for r in conn.execute("SELECT * FROM kb ORDER BY id")]


def get_kb(kb_id: int) -> KBRow | None:
    with closing(_connect()) as conn:
        r = conn.execute("SELECT * FROM kb WHERE id=?", (kb_id,)).fetchone()
        return _to_kb(r) if r else None


def delete_kb(kb_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM kb WHERE id=?", (kb_id,))


# ---------- document ----------

def upsert_document(
    kb_id: int,
    rel_path: str,
    mtime: float,
    sha256: str,
    parser: str,
    status: str,
    error: str | None = None,
    image_count: int = 0,
) -> int:
    """同一 rel_path 只保留一行：先删旧行（级联删 chunk）再插入。"""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM document WHERE kb_id=? AND rel_path=?", (kb_id, rel_path))
        cur = conn.execute(
            """INSERT INTO document(kb_id, rel_path, mtime, sha256, parser, status, error, image_count)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (kb_id, rel_path, mtime, sha256, parser, status, error, image_count),
        )
        return int(cur.lastrowid)


def get_document(kb_id: int, rel_path: str) -> sqlite3.Row | None:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM document WHERE kb_id=? AND rel_path=?", (kb_id, rel_path)
        ).fetchone()


def get_document_by_id(doc_id: int) -> sqlite3.Row | None:
    with closing(_connect()) as conn:
        return conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()


def clear_documents(kb_id: int) -> None:
    """清空某库全部文档行（级联删 chunk），保留 kb 注册行——id 稳定不重建。"""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM document WHERE kb_id=?", (kb_id,))


def delete_document(kb_id: int, rel_path: str) -> int | None:
    """删除文档行（级联删 chunk），返回被删文档 id；不存在返回 None。"""
    with closing(_connect()) as conn, conn:
        row = conn.execute(
            "SELECT id FROM document WHERE kb_id=? AND rel_path=?", (kb_id, rel_path)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM document WHERE id=?", (row["id"],))
        return int(row["id"])


def list_documents(kb_id: int) -> list[sqlite3.Row]:
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM document WHERE kb_id=? ORDER BY rel_path", (kb_id,)
        ).fetchall()


def kb_stats(kb_id: int) -> dict:
    with closing(_connect()) as conn:
        docs = conn.execute(
            "SELECT status, COUNT(*) AS n FROM document WHERE kb_id=? GROUP BY status",
            (kb_id,),
        ).fetchall()
        chunks = conn.execute(
            "SELECT COUNT(*) AS n FROM chunk WHERE kb_id=?", (kb_id,)
        ).fetchone()
    by_status = {r["status"]: r["n"] for r in docs}
    return {
        "documents": sum(by_status.values()),
        "ok": by_status.get("ok", 0),
        "failed": by_status.get("failed", 0),
        "chunks": chunks["n"],
    }


# ---------- chunk ----------

def replace_chunks(kb_id: int, doc_id: int, chunks: list[dict]) -> list[int]:
    """按顺序写入一个文档的全部分块，返回与顺序对齐的 chunk id 列表。"""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM chunk WHERE doc_id=?", (doc_id,))
        ids = []
        for ordinal, c in enumerate(chunks):
            cur = conn.execute(
                """INSERT INTO chunk(doc_id, kb_id, ordinal, type, heading_path,
                                     page, line_start, line_end, text, summary, image_path)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id,
                    kb_id,
                    ordinal,
                    c["type"],
                    c.get("heading_path", ""),
                    c.get("page"),
                    c.get("line_start"),
                    c.get("line_end"),
                    c["text"],
                    c.get("summary", ""),
                    c.get("image_path"),
                ),
            )
            ids.append(int(cur.lastrowid))
        return ids


def get_chunks_by_ids(ids: list[int]) -> dict[int, sqlite3.Row]:
    """按 id 集合取分块（JOIN document 附带 rel_path），返回 {id: row}。"""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"""SELECT c.*, d.rel_path FROM chunk c
                JOIN document d ON c.doc_id = d.id
                WHERE c.id IN ({marks})""",
            ids,
        ).fetchall()
    return {r["id"]: r for r in rows}


def list_chunks_by_doc(doc_id: int) -> list[sqlite3.Row]:
    """按 ordinal 顺序返回一个文档的全部分块。"""
    with closing(_connect()) as conn:
        return conn.execute(
            "SELECT * FROM chunk WHERE doc_id=? ORDER BY ordinal", (doc_id,)
        ).fetchall()


def iter_kb_chunks(kb_id: int) -> Iterator[sqlite3.Row]:
    """BM25 全量重建用：仅取 status=ok 文档的分块。"""
    with closing(_connect()) as conn:
        for r in conn.execute(
            """SELECT c.id, c.text FROM chunk c
               JOIN document d ON c.doc_id = d.id
               WHERE c.kb_id=? AND d.status='ok' ORDER BY c.id""",
            (kb_id,),
        ):
            yield r


# ---------- session ----------

_SESSION_SELECT = """SELECT s.*,
  (SELECT COUNT(*) FROM message m WHERE m.session_id = s.id) AS message_count
  FROM session s"""


def _to_session(row: sqlite3.Row) -> SessionRow:
    return SessionRow(
        int(row["id"]), row["title"],
        int(row["kb_id"]) if row["kb_id"] is not None else None,
        float(row["created_at"]), float(row["updated_at"]),
        int(row["message_count"]),
    )


def create_session(title: str = "新对话", kb_id: int | None = None) -> int:
    now = time.time()
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO session(title, kb_id, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (title, kb_id, now, now),
        )
        return int(cur.lastrowid)


def list_sessions() -> list[SessionRow]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"{_SESSION_SELECT} ORDER BY s.updated_at DESC, s.id DESC"
        ).fetchall()
        return [_to_session(r) for r in rows]


def get_session(session_id: int) -> SessionRow | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            f"{_SESSION_SELECT} WHERE s.id=?", (session_id,)
        ).fetchone()
        return _to_session(row) if row else None


def rename_session(session_id: int, title: str) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE session SET title=?, updated_at=? WHERE id=?",
            (title, time.time(), session_id),
        )
        return cur.rowcount > 0


def update_session_kb(session_id: int, kb_id: int | None) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE session SET kb_id=? WHERE id=?", (kb_id, session_id))


def delete_session(session_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute("DELETE FROM session WHERE id=?", (session_id,))
        return cur.rowcount > 0


# ---------- message ----------

def add_message(
    session_id: int,
    role: str,
    content: str,
    tools: list | None = None,
    citations: list | None = None,
    reasoning: str | None = None,
) -> int:
    """单事务：ordinal=MAX+1 → INSERT → 更新会话 updated_at（+首条 user 消息自动生成标题）。"""
    now = time.time()
    with closing(_connect()) as conn, conn:
        ordinal = conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM message WHERE session_id=?",
            (session_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO message(session_id, ordinal, role, content, reasoning,
                                   tools, citations, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, ordinal, role, content, reasoning,
                json.dumps(tools, ensure_ascii=False) if tools is not None else None,
                json.dumps(citations, ensure_ascii=False) if citations is not None else None,
                now,
            ),
        )
        conn.execute(
            "UPDATE session SET updated_at=? WHERE id=?", (now, session_id)
        )
        if role == "user":
            # 默认标题时用首条消息生成标题
            sess = conn.execute(
                "SELECT title FROM session WHERE id=?", (session_id,)
            ).fetchone()
            if sess is not None and sess["title"] == "新对话":
                t = content.strip().replace("\n", " ")
                title = t[:30] + ("…" if len(t) > 30 else "")
                conn.execute(
                    "UPDATE session SET title=? WHERE id=?", (title, session_id)
                )
        return int(cur.lastrowid)


def list_messages(session_id: int) -> list[MessageRow]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM message WHERE session_id=? ORDER BY ordinal",
            (session_id,),
        ).fetchall()
        return [
            MessageRow(
                int(r["id"]), int(r["ordinal"]), r["role"], r["content"],
                r["reasoning"],
                json.loads(r["tools"]) if r["tools"] else None,
                json.loads(r["citations"]) if r["citations"] else None,
                float(r["created_at"]),
            )
            for r in rows
        ]


# ---------- memory（Agent 长期记忆） ----------

MEMORY_KINDS = ("fact", "preference", "summary")


def _to_memory(r: sqlite3.Row) -> MemoryRow:
    return MemoryRow(
        int(r["id"]), r["kind"], r["content"], r["tags"],
        float(r["created_at"]), float(r["updated_at"]),
    )


def add_memory(kind: str, content: str, tags: str = "") -> int:
    now = time.time()
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO memory(kind, content, tags, created_at, updated_at) VALUES(?,?,?,?,?)",
            (kind, content, tags, now, now),
        )
        return int(cur.lastrowid)


def update_memory(
    mem_id: int,
    *,
    content: str | None = None,
    kind: str | None = None,
    tags: str | None = None,
) -> bool:
    sets, args = ["updated_at=?"], [time.time()]
    if content is not None:
        sets.append("content=?")
        args.append(content)
    if kind is not None:
        sets.append("kind=?")
        args.append(kind)
    if tags is not None:
        sets.append("tags=?")
        args.append(tags)
    args.append(mem_id)
    with closing(_connect()) as conn, conn:
        cur = conn.execute(f"UPDATE memory SET {', '.join(sets)} WHERE id=?", args)
        return cur.rowcount > 0


def get_memory(mem_id: int) -> MemoryRow | None:
    with closing(_connect()) as conn:
        r = conn.execute("SELECT * FROM memory WHERE id=?", (mem_id,)).fetchone()
        return _to_memory(r) if r else None


def list_memories(query: str | None = None) -> list[MemoryRow]:
    """全量列出（updated_at 降序）；query 非空时按 content/tags 子串过滤（大小写不敏感）。"""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM memory ORDER BY updated_at DESC").fetchall()
        out = [_to_memory(r) for r in rows]
    q = (query or "").strip().lower()
    if q:
        out = [m for m in out if q in m.content.lower() or q in m.tags.lower()]
    return out


def delete_memory(mem_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute("DELETE FROM memory WHERE id=?", (mem_id,))
        return cur.rowcount > 0


def count_memories() -> int:
    with closing(_connect()) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0])


def apply_memory_ops(
    updates: list[dict],
    deletes: list[int],
    adds: list[dict],
) -> tuple[int, int, int]:
    """批量应用整理指令（单事务）：update/delete/add 各返回实际生效条数。

    非法项（id 不存在 / content 为空）静默跳过——宁少改不误删。
    """
    now = time.time()
    applied = [0, 0, 0]
    with closing(_connect()) as conn, conn:
        for op in updates:
            mid, sets, args = op.get("id"), [], []
            if mid is None:
                continue
            if op.get("content"):
                sets.append("content=?")
                args.append(op["content"])
            if op.get("kind"):
                sets.append("kind=?")
                args.append(op["kind"])
            if op.get("tags") is not None:
                sets.append("tags=?")
                args.append(op["tags"])
            if not sets:
                continue
            cur = conn.execute(
                f"UPDATE memory SET {', '.join(sets)}, updated_at=? WHERE id=?",
                [*args, now, int(mid)],
            )
            applied[0] += cur.rowcount
        for mid in deletes:
            cur = conn.execute("DELETE FROM memory WHERE id=?", (int(mid),))
            applied[1] += cur.rowcount
        for op in adds:
            content = (op.get("content") or "").strip()
            if not content:
                continue
            cur = conn.execute(
                "INSERT INTO memory(kind, content, tags, created_at, updated_at) VALUES(?,?,?,?,?)",
                (op.get("kind") or "fact", content, op.get("tags") or "", now, now),
            )
            applied[2] += cur.rowcount
    return tuple(applied)
