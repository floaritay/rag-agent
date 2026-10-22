"""Agent 长期记忆：工具化读写 + 超阈值触发的周期整理（压缩/合并/淘汰）。

设计要点：
- **不注入** system prompt——模型通过 recall_memory / remember_memory 两个工具
  自主决定读什么、记什么（工具清单在提示词静态段，KV 前缀缓存不受影响）；
- 更新 = remember_memory 带 memory_id 原地改写（内容/类型/标签）；
- 整理：激活条数超过 MAINTAIN_THRESHOLD 时（每次写入后 / 每轮 run_turn 开头
  检查），守护线程调一次对话模型，输出 JSON 整理指令（合并改写 update /
  淘汰 delete / 归纳新增 add）批量落库，目标压到 MAINTAIN_TARGET 附近；
  整理失败静默（下轮超阈值会再触发），绝不影响对话主流程。
"""

from __future__ import annotations

import json
import re
import threading
import time

from ragagent.storage import (
    MEMORY_KINDS,
    add_memory,
    apply_memory_ops,
    count_memories,
    get_memory,
    list_memories,
    update_memory,
)

MAINTAIN_THRESHOLD = 24   # 激活条数超过此值触发整理
MAINTAIN_TARGET = 12      # 整理目标：压缩到此条数附近（合并/淘汰到约一半）
MAX_MEMORY_CHARS = 500    # 单条记忆长度上限
MAX_MAINTAIN_OPS = 60     # 单次整理指令条数上限（防模型失控）

_MAINTAIN_LOCK = threading.Lock()
_MAINTAIN_RUNNING = False  # 全局单飞：整理不并发

# 第 2 层防御：记忆写入（模型唯一的变更类操作）拒绝指令式内容——
# 无论出自检索资料还是模型被注入后的转写。窄匹配优先，宁漏勿滥伤正常表达。
_RISKY_PAT = re.compile(
    r"(忽略|无视)(以上|上述|之前的)?(规则|指令|限制|要求|设定)"
    r"|你现在是|从现在起你是|今后(必须|一律)"
    r"|必须(改|说|执行|回答|遵守|按照)"
    r"|ignore\s+(the\s+)?(above|previous|rules|instructions)"
    r"|system\s+prompt|jailbreak|越狱",
    re.IGNORECASE,
)

_MAINTAIN_PROMPT = """你是长期记忆整理器。下面是从一个个人知识库智能体的记忆库导出的全部条目（JSON 数组）。
请做一次整理与压缩：

1. 语义重复或高度相近的合并为一条更完整的表述（用 update 改写到其中一条上，其余 delete）；
2. 已过时、依赖已删文档、或对未来对话无复用价值的条目 delete；
3. 多条同主题碎片可用一条更高层的归纳替代（update 改写 + delete 其余，或 add 一条 summary）；
4. 保留具体、可复用的用户偏好与事实，不要删除仍有价值的细节；
5. 整理后总条数应不超过 {target} 条。

只输出一个 JSON 对象（不要任何解释、不要代码围栏），格式：
{{"ops": [
  {{"action": "update", "id": <既有id>, "content": "<改写后全文>", "kind": "fact|preference|summary", "tags": "<可选>"}},
  {{"action": "delete", "id": "<既有id>"}},
  {{"action": "add", "content": "<归纳条目>", "kind": "summary", "tags": "<可选>"}}
]}}

记忆条目：
{memories}"""


def _chat_once(prompt: str) -> str:
    """一次无工具的对话调用（整理专用）。测试可 monkeypatch 本函数。"""
    from ragagent.llm import ThinkingChatOpenAI
    from ragagent.config import get_settings

    s = get_settings()
    llm = ThinkingChatOpenAI(
        model=s.chat_model,
        api_key=s.chat_key,
        base_url=s.chat_base,
        temperature=0.0,
        max_retries=1,
        timeout=60,
    )
    from langchain_core.messages import HumanMessage

    resp = llm.invoke([HumanMessage(prompt)])
    content = getattr(resp, "content", "") or ""
    if isinstance(content, list):  # content-block 形式取纯文本
        content = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return content


def _parse_ops(text: str) -> list[dict]:
    """从模型输出提取 ops 列表：容忍代码围栏/前后杂文，容错字段。"""
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return []
    ops = data.get("ops") if isinstance(data, dict) else None
    if not isinstance(ops, list):
        return []
    return [o for o in ops[:MAX_MAINTAIN_OPS] if isinstance(o, dict)]


def run_maintenance() -> tuple[int, int, int]:
    """执行一次整理：不足阈值则不动；返回 (update, delete, add) 实际生效数。

    任何异常返回 (0,0,0)——后台任务不冒泡。
    """
    try:
        memories = list_memories()
        if len(memories) <= MAINTAIN_THRESHOLD:
            return (0, 0, 0)
        dump = [
            {"id": m.id, "kind": m.kind, "tags": m.tags, "content": m.content}
            for m in sorted(memories, key=lambda x: x.id)
        ]
        raw = _chat_once(_MAINTAIN_PROMPT.format(
            target=MAINTAIN_TARGET,
            memories=json.dumps(dump, ensure_ascii=False, indent=1),
        ))
        ops = _parse_ops(raw)
        if not ops:
            return (0, 0, 0)
        updates = [o for o in ops if o.get("action") == "update"]
        deletes = [int(o["id"]) for o in ops
                   if o.get("action") == "delete" and str(o.get("id", "")).isdigit()]
        adds = [o for o in ops if o.get("action") == "add"]
        # 截断超长内容，防模型输出失控
        for o in updates + adds:
            if isinstance(o.get("content"), str) and len(o["content"]) > MAX_MEMORY_CHARS:
                o["content"] = o["content"][:MAX_MEMORY_CHARS]
        return apply_memory_ops(updates, deletes, adds)
    except Exception:  # noqa: BLE001 —— 后台整理失败静默，下次超阈值再触发
        return (0, 0, 0)


def maybe_trigger_maintenance() -> None:
    """超阈值时起守护线程整理（全局单飞，不阻塞调用方）。"""
    global _MAINTAIN_RUNNING
    if count_memories() <= MAINTAIN_THRESHOLD:
        return
    if not _MAINTAIN_LOCK.acquire(blocking=False):
        return  # 已有整理在跑
    if _MAINTAIN_RUNNING:
        _MAINTAIN_LOCK.release()
        return
    _MAINTAIN_RUNNING = True

    def _worker():
        global _MAINTAIN_RUNNING
        try:
            run_maintenance()
        finally:
            _MAINTAIN_RUNNING = False
            _MAINTAIN_LOCK.release()

    threading.Thread(target=_worker, daemon=True, name="memory-maintain").start()


# ---------- 工具实现（tools.py 调用，返回 (结果JSON, 事件摘要)） ----------

def tool_recall_memory(query: str | None) -> tuple[str, str]:
    rows = list_memories(query)
    out = [
        {
            "id": m.id,
            "kind": m.kind,
            "tags": m.tags,
            "content": m.content,
            "更新于": time.strftime("%Y-%m-%d", time.localtime(m.updated_at)),
        }
        for m in rows
    ]
    summary = f"记忆 {len(out)} 条" + (f"（匹配 {query!r}）" if query else "")
    return (
        json.dumps({"memories": out,
                    "提示": "更新某条记忆时用 remember_memory 并带其 id"},
                   ensure_ascii=False),
        summary,
    )


def tool_remember_memory(
    content: str | None,
    kind: str | None,
    tags: str | None,
    memory_id: int | None,
) -> tuple[str, str]:
    text = (content or "").strip()
    if not text:
        return json.dumps({"error": "content 不能为空"}, ensure_ascii=False), "内容为空"
    if _RISKY_PAT.search(text):  # 指令式内容不落库（注入防御硬门禁）
        return (
            json.dumps({"error": "内容包含指令式文本（试图改变规则/行为），"
                                  "已拒绝写入；记忆只收事实与偏好"},
                       ensure_ascii=False),
            "拒绝写入（指令式内容）",
        )
    if len(text) > MAX_MEMORY_CHARS:
        text = text[:MAX_MEMORY_CHARS]
    k = (kind or "fact").strip()
    if k not in MEMORY_KINDS:
        k = "fact"
    tg = (tags or "").strip()

    if memory_id is not None:
        if get_memory(int(memory_id)) is None:
            return (json.dumps({"error": f"记忆 {memory_id} 不存在，无法更新"},
                               ensure_ascii=False), "记忆不存在")
        update_memory(int(memory_id), content=text, kind=k, tags=tg)
        maybe_trigger_maintenance()
        return (json.dumps({"updated": int(memory_id), "kind": k, "content": text},
                           ensure_ascii=False), f"更新记忆 #{memory_id}")

    mid = add_memory(k, text, tg)
    maybe_trigger_maintenance()
    return (json.dumps({"saved": mid, "kind": k, "content": text},
                       ensure_ascii=False), f"记住 #{mid}")
