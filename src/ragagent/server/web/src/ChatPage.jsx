import React, { useEffect, useRef, useState } from 'react'
import {
  Plus, Search, MessageSquare, Pencil, Trash2, Brain, ChevronDown, Bot,
  FileText, Copy, RefreshCw, Send, Menu, Square,
} from 'lucide-react'
import {
  streamChat, listSessions, createSession, getSession,
  getSessionMessages, renameSession, deleteSession, getHealth,
} from './api.js'
import { mdToHtml } from './md.js'
import Dropdown from './Dropdown.jsx'

function dayBucket(ts) {
  const d = new Date(ts * 1000)
  const now = new Date()
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = (startOf(now) - startOf(d)) / 86400000
  if (diff < 1) return '今天'
  if (diff < 2) return '昨天'
  return '更早'
}

function ToolCallCard({ tool }) {
  return (
    <div className="tool-call rounded-lg bg-background border border-border p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-primary/10 text-primary">
          <Search className="w-3.5 h-3.5" />
        </span>
        <span className="font-medium text-foreground">{tool.name}</span>
        <span className="ml-auto text-xs px-2 py-0.5 rounded-full"
          style={{ backgroundColor: 'color-mix(in srgb, var(--rag-state-success) 12%, transparent)', color: 'var(--rag-state-success)' }}>
          已调用
        </span>
      </div>
      <div className="space-y-1.5 text-xs font-mono text-muted-foreground break-all">
        <p>{tool.summary}</p>
      </div>
    </div>
  )
}

function SourceCard({ c }) {
  return (
    <details className="source-card rounded-md bg-background border border-border pl-3 pr-4 py-3 cursor-pointer"
      style={{ borderLeft: '4px solid var(--rag-primary)' }}>
      <summary className="flex items-center justify-between list-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-4 h-4 text-primary flex-shrink-0" />
          <span className="text-sm font-medium text-foreground truncate">{c.rel_path}</span>
          <span className="text-xs text-muted-foreground flex-shrink-0">{c.location}</span>
        </div>
        <ChevronDown className="source-chevron w-4 h-4 text-muted-foreground flex-shrink-0" />
      </summary>
      <div className="source-chunk pt-3 mt-2 border-t border-border">
        <p className="text-sm text-muted-foreground" style={{ lineHeight: 1.65 }}>{c.snippet}</p>
        {c.image_path && (
          <img
            src={`/api/images?path=${encodeURIComponent(c.image_path)}`}
            alt={`引用图片：${c.rel_path}`}
            loading="lazy"
            className="mt-2 max-h-72 rounded-md border border-border"
          />
        )}
      </div>
    </details>
  )
}

export default function ChatPage({ kbs, kbId, setKbId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [sessionQuery, setSessionQuery] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [model, setModel] = useState('')
  const endRef = useRef(null)
  const taRef = useRef(null)
  const scrollRef = useRef(null)   // 消息滚动容器
  const stickRef = useRef(true)    // 是否贴底跟随（用户上翻阅读时暂停自动滚动）
  const abortRef = useRef(null)    // 当前流式请求的 AbortController（停止按钮用）

  const onScroll = () => {
    const el = scrollRef.current
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  // 只在「消息条数或末条内容增长」时滚到底——切换思考展开态等同内容操作不再触发跳底；
  // 且仅当用户贴底时跟随，上翻阅读自由滚动不被打断
  const lastMsg = messages[messages.length - 1]
  const scrollKey = [
    messages.length,
    lastMsg?.content?.length ?? 0,
    lastMsg?.reasoning?.length ?? 0,
    (lastMsg?.tools || []).length,
    (lastMsg?.citations || []).length,
  ].join(':')
  useEffect(() => {
    if (stickRef.current) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [scrollKey])
  useEffect(() => {
    const refresh = () => { getHealth().then((h) => setModel(h.chat_model)).catch(() => {}) }
    refresh()
    window.addEventListener('settings-changed', refresh)  // 设置保存后即时更新模型标签
    return () => window.removeEventListener('settings-changed', refresh)
  }, [])

  async function openSession(id) {
    if (busy) return
    try {
      const [sess, msgs] = await Promise.all([getSession(id), getSessionMessages(id)])
      setSessionId(id)
      setMessages(msgs.map((m) => ({
        role: m.role,
        content: m.content,
        reasoning: m.reasoning || '',
        thinkOpen: false,  // 刷新/切会话后默认收起思考
        citeOpen: false,   // 引用来源默认收起
        tools: m.tools || [],
        citations: m.citations,
        error: null,
      })))
      if (sess.kb_id != null) setKbId(sess.kb_id)
      setSidebarOpen(false)
      stickRef.current = true  // 切换会话后回到贴底
    } catch (e) {
      alert(`加载会话失败：${e.message}`)
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const list = await listSessions()
        setSessions(list)
        if (list.length > 0) await openSession(list[0].id)
      } catch { /* 后端不可用时保持空态 */ }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function newSession() {
    if (busy) return
    try {
      const s = await createSession('新对话', kbId)
      setSessions((list) => [s, ...list])
      setSessionId(s.id)
      setMessages([])
      setInput('')
      setSidebarOpen(false)
    } catch (e) {
      alert(`新建会话失败：${e.message}`)
    }
  }

  async function renameItem(s) {
    if (busy) return
    const title = prompt('重命名会话', s.title)
    if (!title || !title.trim()) return
    try {
      const updated = await renameSession(s.id, title.trim())
      setSessions((list) => list.map((x) => (x.id === s.id ? { ...x, title: updated.title } : x)))
    } catch (err) {
      alert(`重命名失败：${err.message}`)
    }
  }

  async function removeItem(s) {
    if (busy) return
    if (!confirm(`删除会话「${s.title}」？消息将一并删除。`)) return
    try {
      await deleteSession(s.id)
      const rest = sessions.filter((x) => x.id !== s.id)
      setSessions(rest)
      if (sessionId === s.id) {
        if (rest.length > 0) await openSession(rest[0].id)
        else { setSessionId(null); setMessages([]) }
      }
    } catch (err) {
      alert(`删除失败：${err.message}`)
    }
  }

  async function send(textOverride) {
    const text = (textOverride ?? input).trim()
    if (!text || busy) return
    if (!kbId) { alert('请先在右上角选择知识库'); return }
    setInput('')
    if (taRef.current) taRef.current.style.height = 'auto'
    setBusy(true)
    // 懒创建：没有当前会话时先建一个
    let sid = sessionId
    if (sid == null) {
      try {
        const s = await createSession('新对话', kbId)
        sid = s.id
        setSessionId(sid)
        setSessions((list) => [s, ...list])
      } catch (e) {
        setBusy(false)
        alert(`创建会话失败：${e.message}`)
        return
      }
    }
    stickRef.current = true  // 自己提问后恢复贴底跟随
    setMessages((m) => [...m,
      { role: 'user', content: text },
      { role: 'assistant', content: '', reasoning: '', thinkOpen: true, citeOpen: false,
        tools: [], citations: null, error: null },
    ])
    const ctrl = new AbortController()
    abortRef.current = ctrl
    await streamChat({
      kbId, sessionId: sid, message: text, signal: ctrl.signal,
      onEvent: (ev) => setMessages((m) => {
        const copy = m.slice()
        const last = { ...copy[copy.length - 1] }
        if (ev.type === 'reasoning') last.reasoning = (last.reasoning || '') + ev.text
        else if (ev.type === 'token') last.content += ev.text
        else if (ev.type === 'tool') last.tools = [...(last.tools || []), ev]
        else if (ev.type === 'reset') { last.content = ''; last.reasoning = ''; last.tools = [] }
        else if (ev.type === 'citations') last.citations = ev.citations
        else if (ev.type === 'error') last.error = ev.message
        copy[copy.length - 1] = last
        return copy
      }),
    })
    abortRef.current = null
    // 回答结束（含主动停止）：思考过程默认收起（可手动点开）；
    // 服务端断连 finally 会把已生成的部分内容随会话落库
    setMessages((ms) => ms.map((m) => ({ ...m, thinkOpen: false })))
    setBusy(false)
    listSessions().then(setSessions).catch(() => {})
  }

  function regenerate() {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (lastUser) send(lastUser.content)
  }

  function copyAnswer(content) {
    navigator.clipboard?.writeText(content).catch(() => {})
  }

  function stopStream() {
    abortRef.current?.abort()
  }

  // 搜索 + 今天/昨天/更早分组
  const filtered = sessions.filter((s) => s.title.toLowerCase().includes(sessionQuery.trim().toLowerCase()))
  const groups = ['今天', '昨天', '更早']
    .map((label) => [label, filtered.filter((s) => dayBucket(s.updated_at) === label)])
    .filter(([, list]) => list.length > 0)

  const currentTitle = sessions.find((s) => s.id === sessionId)?.title || '新对话'

  return (
    <main className="app-root">
      <div className="chat-shell">
        {/* 侧栏 */}
        <aside className={`chat-sidebar bg-muted ${sidebarOpen ? 'is-open' : ''}`}>
          <div className="p-4 space-y-3">
            <button type="button" onClick={newSession} disabled={busy}
              className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium hover:bg-primary/90 active:scale-[0.98] disabled:opacity-50 transition-[transform,background-color]">
              <Plus className="w-4 h-4" />
              <span>新建对话</span>
            </button>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input type="text" value={sessionQuery} onChange={(e) => setSessionQuery(e.target.value)}
                placeholder="搜索会话..."
                className="w-full rounded-lg bg-background border border-border pl-9 pr-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-4">
            {groups.length === 0 && (
              <p className="px-2 text-xs text-muted-foreground">还没有会话</p>
            )}
            {groups.map(([label, list]) => (
              <section key={label} className="session-group">
                <h3 className="px-2 text-xs font-medium text-muted-foreground mb-1">{label}</h3>
                <ul className="space-y-1">
                  {list.map((s) => (
                    <li key={s.id} className="group relative">
                      <button type="button" onClick={() => openSession(s.id)}
                        aria-current={s.id === sessionId ? 'true' : undefined}
                        className={`w-full flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-left border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                          s.id === sessionId
                            // 深色下 bg-accent 是近白色（--rag-accent 未随暗色改写）→ 改用主色半透明高亮，白字可读
                            ? 'bg-primary/20 border-primary/30 text-foreground font-medium'
                            : 'text-foreground border-transparent hover:bg-background'}`}>
                        <MessageSquare className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                        <span className="truncate flex-1">{s.title}</span>
                      </button>
                      <span className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover:flex gap-0.5">
                        <button type="button" onClick={() => renameItem(s)} aria-label="重命名"
                          className="w-6 h-6 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-background">
                          <Pencil className="w-3 h-3" />
                        </button>
                        <button type="button" onClick={() => removeItem(s)} aria-label="删除"
                          className="w-6 h-6 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-background">
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </aside>

        {/* 消息区 */}
        <section className="chat-main bg-background">
          {/* 顶栏 */}
          <div className="h-14 flex items-center justify-between px-4 sm:px-6 border-b border-border bg-background/95 backdrop-blur flex-shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <button type="button" onClick={() => setSidebarOpen((v) => !v)}
                className="md:hidden inline-flex items-center justify-center w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
                aria-label="会话列表">
                <Menu className="w-4 h-4" />
              </button>
              <h1 className="text-sm font-semibold text-foreground truncate">{currentTitle}</h1>
              <button type="button"
                onClick={() => { const s = sessions.find((x) => x.id === sessionId); if (s) renameItem(s) }}
                className="inline-flex items-center justify-center w-7 h-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="编辑会话标题">
                <Pencil className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <Dropdown
                value={kbId}
                onChange={setKbId}
                placeholder="（未选知识库）"
                minWidth={220}
                options={[
                  { value: null, label: '（未选知识库）' },
                  ...kbs.map((k) => ({ value: k.id, label: `${k.name} · ${k.stats.documents} 篇` })),
                ]} />
              <span className="hidden sm:inline-flex items-center rounded-lg border border-border bg-background text-muted-foreground text-sm px-3 py-1.5"
                title="当前对话模型">
                {model || '…'}
              </span>
              <button type="button"
                onClick={() => { const s = sessions.find((x) => x.id === sessionId); if (s) removeItem(s) }}
                className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="删除当前会话">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* 消息列表 */}
          <div className="message-scroll" ref={scrollRef} onScroll={onScroll}>
            <div className="message-list max-w-4xl mx-auto px-4 sm:px-6 py-8 space-y-8">
              {messages.length === 0 && (
                <p className="text-center text-muted-foreground mt-20">
                  问点你的资料吧，例如：“预算表里 row45 的 Q3 是多少？”
                </p>
              )}
              {messages.map((m, i) => m.role === 'user' ? (
                <article key={i} className="chat-message user flex flex-row justify-end">
                  <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl rounded-tr-sm bg-primary text-primary-foreground px-5 py-3.5"
                    style={{ lineHeight: 1.65 }}>
                    <p className="text-[15px] whitespace-pre-wrap">{m.content}</p>
                  </div>
                </article>
              ) : (
                <article key={i} className="chat-message assistant flex flex-row gap-4">
                  <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-primary text-primary-foreground flex items-center justify-center">
                    <Bot className="w-[18px] h-[18px]" />
                  </div>
                  <div className="flex-1 min-w-0 space-y-3">
                    {/* 思考过程（含工具调用） */}
                    {(m.reasoning || (m.tools || []).length > 0) && (
                      <div className="agent-thinking rounded-xl bg-muted border border-border overflow-hidden">
                        <button type="button"
                          onClick={() => setMessages((ms) => ms.map((x, xi) =>
                            xi === i ? { ...x, thinkOpen: !x.thinkOpen } : x))}
                          className="thinking-toggle w-full flex items-center justify-between px-4 py-2.5 text-left text-sm font-medium text-foreground hover:bg-muted/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          aria-expanded={m.thinkOpen ? 'true' : 'false'}>
                          <span className="flex items-center gap-2">
                            <Brain className="w-4 h-4 text-primary" />
                            思考过程
                            {m.reasoning && (
                              <span className="text-xs font-normal text-muted-foreground">· {m.reasoning.length} 字</span>
                            )}
                          </span>
                          <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${m.thinkOpen ? 'rotate-180' : ''}`} />
                        </button>
                        {m.thinkOpen && (
                          <div className="thinking-content px-4 pb-3 space-y-3 text-sm text-muted-foreground"
                            style={{ lineHeight: 1.65 }}>
                            {m.reasoning.split('\n').filter(Boolean).map((line, j) => (
                              <p key={j} className="whitespace-pre-wrap">{line}</p>
                            ))}
                            {(m.tools || []).map((t, j) => (
                              <ToolCallCard key={j} tool={t} />
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* 答案卡 */}
                    <div className="rounded-2xl rounded-tl-sm bg-card border border-border px-5 py-4"
                      style={{ lineHeight: 1.65 }}>
                      {m.content
                        ? <div className="text-[15px] text-foreground mb-4 md" dangerouslySetInnerHTML={{ __html: mdToHtml(m.content) }} />
                        : busy && i === messages.length - 1
                          ? <p className="text-sm text-muted-foreground mb-4">{m.reasoning ? '推理中…' : '思考中…'}</p>
                          : null}
                      {m.error && (
                        <div className="mb-4 rounded-lg border px-3 py-2 text-sm"
                          style={{ background: 'color-mix(in srgb, var(--rag-state-error) 10%, transparent)',
                                   borderColor: 'color-mix(in srgb, var(--rag-state-error) 35%, transparent)',
                                   color: 'var(--rag-state-error)' }}>
                          ⚠ {m.error}
                        </div>
                      )}
                      {m.citations && m.citations.length > 0 && (
                        <div className="think-box mb-4">
                          <button type="button"
                            onClick={() => setMessages((ms) => ms.map((x, xi) =>
                              xi === i ? { ...x, citeOpen: !x.citeOpen } : x))}
                            className="think-head w-full flex items-center justify-between text-left"
                            aria-expanded={m.citeOpen ? 'true' : 'false'}>
                            <span className="flex items-center gap-2">
                              <FileText className="w-4 h-4 text-primary" />
                              引用来源
                              <span className="text-xs font-normal text-muted-foreground">· {m.citations.length} 条</span>
                            </span>
                            <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${m.citeOpen ? 'rotate-180' : ''}`} />
                          </button>
                          {m.citeOpen && (
                            <div className="space-y-2 mt-2">
                              {m.citations.map((c) => (
                                <SourceCard key={c.chunk_id} c={c} />
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                      {m.content && (
                        <div className="message-actions flex items-center gap-1 pt-1">
                          <button type="button" onClick={() => copyAnswer(m.content)}
                            className="inline-flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            aria-label="复制">
                            <Copy className="w-4 h-4" />
                          </button>
                          <button type="button" onClick={regenerate} disabled={busy}
                            className="inline-flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            aria-label="重新生成">
                            <RefreshCw className="w-4 h-4" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </article>
              ))}
              <div ref={endRef} />
            </div>
          </div>

          {/* 输入区 */}
          <div className="input-area border-t border-border bg-background px-4 sm:px-6 py-4">
            <div className="max-w-4xl mx-auto">
              <div className="relative flex items-end gap-2 rounded-2xl border border-border bg-card p-2 focus-within:ring-2 focus-within:ring-ring">
                <textarea
                  ref={taRef}
                  rows={1}
                  value={input}
                  placeholder={busy ? '回答生成中…' : '输入问题，RAG-Agent 会基于你的知识库回答...'}
                  onChange={(e) => {
                    setInput(e.target.value)
                    e.target.style.height = 'auto'
                    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
                  }}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                  disabled={busy}
                  className="w-full resize-none bg-transparent py-2.5 text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none"
                  style={{ maxHeight: 160, lineHeight: 1.6 }}
                />
                {busy ? (
                  <button type="button" onClick={stopStream}
                    className="inline-flex items-center justify-center w-9 h-9 rounded-xl border border-border bg-card text-foreground hover:bg-muted active:scale-[0.98] flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-[transform,background-color]"
                    aria-label="停止生成">
                    <Square className="w-4 h-4 fill-current" />
                  </button>
                ) : (
                  <button type="button" onClick={() => send()} disabled={!input.trim()}
                    className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 active:scale-[0.98] flex-shrink-0 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-[transform,background-color]"
                    aria-label="发送">
                    <Send className="w-[18px] h-[18px]" />
                  </button>
                )}
              </div>
              <p className="mt-2 text-center text-xs text-muted-foreground">Enter 发送，Shift+Enter 换行</p>
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
