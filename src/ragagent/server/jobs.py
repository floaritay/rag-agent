"""后台入库任务槽：全局单任务（本地单用户工具），内存态。

进程重启即复位为 idle——可接受：文件级 sha256 增量入库天然可恢复，
重新扫描即收敛。work 以 callable 注入，保持本模块为叶子（无 indexer 依赖）。
"""

from __future__ import annotations

import threading
from typing import Callable

_lock = threading.Lock()
_thread: threading.Thread | None = None
_running: dict | None = None   # {"kb_id","kind","done","total","file"} 任务运行中
_last: dict[int, dict] = {}    # kb_id -> {"kind","report","error"} 最近一次终态


def is_busy() -> bool:
    with _lock:
        return _running is not None


def try_start(
    kb_id: int,
    kind: str,
    work: Callable[[Callable[[dict], None]], dict],
) -> bool:
    """空闲则登记 running 并启动 worker 返回 True；忙返回 False。

    work(on_progress) -> report dict；异常记入 error 终态。
    启动时清掉该库旧报告（下一次任务的状态从头开始）。
    """
    global _thread, _running
    with _lock:
        if _running is not None:
            return False
        _last.pop(kb_id, None)
        _running = {"kb_id": kb_id, "kind": kind, "done": 0, "total": 0, "file": ""}

        def _on_progress(p: dict) -> None:
            with _lock:
                if _running is not None:
                    _running.update(p)

        def _body() -> None:
            global _thread, _running
            try:
                report = work(_on_progress)
                with _lock:
                    _last[kb_id] = {"kind": kind, "report": report, "error": None}
            except Exception as e:  # noqa: BLE001 —— 任何入库异常都转为 error 终态
                with _lock:
                    _last[kb_id] = {"kind": kind, "report": None, "error": str(e)}
            finally:
                with _lock:
                    _running = None
                    _thread = None

        _thread = threading.Thread(target=_body, daemon=True, name=f"kb-ingest-{kb_id}")
        _thread.start()
        return True


def status_for(kb_id: int) -> dict:
    """该库的任务状态：running（全局任务属于它）/ 最近终态 / idle。"""
    with _lock:
        if _running is not None and _running["kb_id"] == kb_id:
            return {
                "status": "running",
                "kb_id": kb_id,
                "kind": _running["kind"],
                "done": _running.get("done", 0),
                "total": _running.get("total", 0),
                "file": _running.get("file", ""),
                "report": None,
                "error": None,
            }
        rec = _last.get(kb_id)
        if rec is None:
            return {
                "status": "idle", "kb_id": kb_id, "kind": None,
                "done": 0, "total": 0, "file": "",
                "report": None, "error": None,
            }
        report = rec["report"]
        return {
            "status": "error" if rec["error"] else "done",
            "kb_id": kb_id,
            "kind": rec["kind"],
            "done": (report or {}).get("total", 0),
            "total": (report or {}).get("total", 0),
            "file": "",
            "report": report,
            "error": rec["error"],
        }


def reset() -> None:
    """测试用：join 残留 worker 后清空全部状态。"""
    global _thread, _running
    with _lock:
        t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=30)
    with _lock:
        _thread = None
        _running = None
        _last.clear()
