"""会话管理 REST API：/api/sessions*（多会话聊天 + 服务端持久化）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ragagent.storage import (
    create_session,
    delete_session,
    get_kb,
    get_session,
    list_messages,
    list_sessions,
    rename_session,
)

router = APIRouter(prefix="/api")


class SessionCreate(BaseModel):
    title: str = "新对话"
    kb_id: int | None = None


class SessionRename(BaseModel):
    title: str


def _session_dict(s) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "kb_id": s.kb_id,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "message_count": s.message_count,
    }


def _get_session_or_404(session_id: int):
    s = get_session(session_id)
    if s is None:
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return s


@router.get("/sessions")
def list_sessions_endpoint():
    return [_session_dict(s) for s in list_sessions()]


@router.post("/sessions", status_code=201)
def create_session_endpoint(body: SessionCreate | None = None):
    title = (body.title if body else "新对话").strip() or "新对话"
    kb_id = body.kb_id if body else None
    if kb_id is not None and get_kb(kb_id) is None:
        raise HTTPException(404, f"知识库 {kb_id} 不存在")
    sid = create_session(title=title, kb_id=kb_id)
    return _session_dict(get_session(sid))


@router.get("/sessions/{session_id}")
def get_session_endpoint(session_id: int):
    return _session_dict(_get_session_or_404(session_id))


@router.get("/sessions/{session_id}/messages")
def session_messages_endpoint(session_id: int):
    _get_session_or_404(session_id)
    return [
        {
            "id": m.id,
            "ordinal": m.ordinal,
            "role": m.role,
            "content": m.content,
            "reasoning": m.reasoning,  # 思考过程，NULL = 无
            "tools": m.tools,
            "citations": m.citations,
            "created_at": m.created_at,
        }
        for m in list_messages(session_id)
    ]


@router.patch("/sessions/{session_id}")
def rename_session_endpoint(session_id: int, body: SessionRename):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title 不能为空")
    if not rename_session(session_id, title):
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return _session_dict(get_session(session_id))


@router.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: int):
    if not delete_session(session_id):
        raise HTTPException(404, f"会话 {session_id} 不存在")
    return {"deleted": session_id}
