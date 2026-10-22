import React, { useEffect, useRef, useState } from 'react'
import {
  Search, Plus, Library, Briefcase, BookOpen, FolderOpen, Trash2, FileText,
  Layers, CheckCircle2, HardDrive, Upload, RefreshCw, Eye,
} from 'lucide-react'
import {
  createKb, deleteDoc, deleteKb, getDocChunks, getIngestStatus, ingestKb, kbStats,
  listDocs, rebuildKb, uploadFiles,
} from './api.js'

function fmtSize(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1048576).toFixed(1)} MB`
  return `${(n / 1073741824).toFixed(2)} GB`
}

function StatCard({ icon: Icon, value, label, color }) {
  return (
    <article className="rounded-lg bg-card border border-border p-4" style={{ boxShadow: 'var(--rag-shadow-1)' }}>
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-accent text-accent-foreground">
          <Icon className="w-4 h-4" />
        </span>
        <div>
          <p className="text-2xl font-semibold text-foreground" style={color ? { color } : undefined}>{value}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
      </div>
    </article>
  )
}

function ReportPanel({ report }) {
  if (!report) return null
  const fail = report.items?.filter((i) => i.status === 'failed') || []
  return (
    <div className="rounded-xl border border-border bg-card p-4 text-sm space-y-2"
      style={{ boxShadow: 'var(--rag-shadow-1)' }}>
      <div className="font-semibold text-foreground">
        入库报告 · {report.kb_name}：成功 {report.ok} / 跳过 {report.skipped} / 失败 {report.failed}
        （新增分块 {report.chunks_added}，图片 {report.images_found} 张，已入库 {report.images_indexed ?? 0} 张）
      </div>
      <ul className="space-y-1 text-muted-foreground">
        {(report.items || []).map((i) => (
          <li key={i.rel_path}>
            {i.rel_path} — {i.status}{i.chunks ? `（${i.chunks} 块）` : ''}{i.error ? `：${i.error}` : ''}
          </li>
        ))}
      </ul>
      {(report.warnings || []).length > 0 && (
        <div style={{ color: 'var(--rag-state-warning)' }}>⚠ {report.warnings.join('；')}</div>
      )}
      {fail.length > 0 && (
        <div className="text-muted-foreground">失败项保留可重试：处理后再次入库即可自动收编。</div>
      )}
    </div>
  )
}

const KB_ICONS = [Library, Briefcase, BookOpen, FolderOpen]

function chunkTypeLabel(c) {
  // 图片 caption 块显示「图片」——image_path 优先（兼容未重新入库的旧数据 type=text）
  if (c.image_path || c.type === 'image') return '图片'
  return { text: '文本', table: '表格', code: '代码' }[c.type] || c.type
}

function chunkLocation(c) {
  if (c.heading_path) return c.heading_path
  if (c.page != null) return `第 ${c.page} 页`
  if (c.line_start != null) return `行 ${c.line_start}–${c.line_end}`
  return chunkTypeLabel(c)
}

function ChunkPreviewModal({ path, data, onClose }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}>
      <div className="w-full max-w-3xl rounded-xl border border-border bg-popover flex flex-col"
        style={{ maxHeight: '85vh', boxShadow: 'var(--rag-shadow-3)' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 px-5 pt-4 pb-3 border-b border-border">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-foreground truncate">切分预览 · {path}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              chunk_size {data.chunk_size} · overlap {data.overlap} · 共 {data.count} 块
            </p>
          </div>
          <button onClick={onClose} aria-label="关闭"
            className="w-8 h-8 flex-shrink-0 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">×</button>
        </div>
        <div className="overflow-y-auto px-5 py-4 space-y-3">
          {data.count === 0 && (
            <p className="text-sm text-muted-foreground py-6 text-center">
              暂无分块——该文档尚未入库成功，先修复后重新入库即可预览。
            </p>
          )}
          {data.chunks.map((c) => (
            <div key={c.ordinal} className="rounded-lg bg-background border border-border p-3">
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <span className="text-xs font-semibold px-1.5 py-0.5 rounded bg-primary/15 text-primary">
                  #{c.ordinal}
                </span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                  {chunkTypeLabel(c)}
                </span>
                <span className="text-xs text-muted-foreground truncate">{chunkLocation(c)}</span>
                <span className="ml-auto text-xs text-muted-foreground flex-shrink-0">{c.length} 字</span>
              </div>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap"
                style={{ lineHeight: 1.65, maxHeight: 208, overflowY: 'auto' }}>
                {c.text}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function KBPage({ kbs, kbId, setKbId, refreshKbs }) {
  const [docs, setDocs] = useState([])
  const [stats, setStats] = useState(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [kbQuery, setKbQuery] = useState('')
  const [report, setReport] = useState(null)
  const [working, setWorking] = useState(false)
  const [err, setErr] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [preview, setPreview] = useState(null)  // { path, data }
  const [job, setJob] = useState(null)          // ingest-status 快照；null = 无可见任务
  const fileRef = useRef(null)

  const loadDocs = async (id) => { try { if (id) setDocs(await listDocs(id)); else setDocs([]) } catch { setDocs([]) } }
  const loadStats = async (id) => { try { if (id) setStats(await kbStats(id)); else setStats(null) } catch { setStats(null) } }
  useEffect(() => { loadDocs(kbId); loadStats(kbId) }, [kbId])

  const pollUntilDone = async (id) => {
    for (;;) {
      const s = await getIngestStatus(id)
      setJob(s)
      if (s.status === 'done') { if (s.report) setReport(s.report); return s }
      if (s.status === 'error') {
        setErr(`入库失败：${s.error || '未知错误'}`)
        if (s.report) setReport(s.report)
        return s
      }
      if (s.status === 'idle') return s  // 服务重启复位
      await new Promise((r) => setTimeout(r, 700))
    }
  }

  const run = async (fn, { poll = false } = {}) => {
    setWorking(true); setErr('')
    try {
      await fn()
      if (poll) await pollUntilDone(kbId)  // 报告唯一来源：状态轮询
      await refreshKbs(); await loadDocs(kbId); await loadStats(kbId)
    } catch (e) { setErr(String(e.message || e)) }
    finally { setWorking(false); setJob(null) }
  }

  // 页面刷新/切库时若后台任务仍在跑 → 恢复轮询与进度显示
  useEffect(() => {
    let dead = false
    ;(async () => {
      if (!kbId) return
      try {
        const s = await getIngestStatus(kbId)
        if (dead || s.status !== 'running') return  // done/error 挂载时不自动弹报告
        setWorking(true)
        await pollUntilDone(kbId)
        if (dead) return
        setWorking(false); setJob(null)
        await refreshKbs(); await loadDocs(kbId); await loadStats(kbId)
      } catch { /* 忽略 */ }
    })()
    return () => { dead = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kbId])

  const current = kbs.find((k) => k.id === kbId)
  const filtered = kbs.filter((k) => k.name.toLowerCase().includes(kbQuery.trim().toLowerCase()))

  const create = async () => {
    if (!newName.trim()) return
    await run(async () => {
      const kb = await createKb(newName.trim())
      setKbId(kb.id); setNewName(''); setCreating(false)
      return kb
    })
  }

  const openPreview = async (d) => {
    try {
      setPreview({ path: d.rel_path, data: await getDocChunks(kbId, d.id) })
    } catch (e) {
      alert(`加载切分预览失败：${e.message || e}`)
    }
  }

  const doUpload = (filesOrEvent) => {
    const files = Array.isArray(filesOrEvent)
      ? filesOrEvent
      : Array.from(filesOrEvent.target?.files || [])
    if (files.length) run(() => uploadFiles(kbId, files), { poll: true })
    if (filesOrEvent.target) filesOrEvent.target.value = ''
  }

  return (
    <div className="kb-page">
      <div className="kb-body">
        {/* 侧栏 */}
        <aside className="kb-sidebar bg-muted border-r border-border flex flex-col">
          <div className="p-4 space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input type="text" placeholder="搜索知识库…" value={kbQuery}
                onChange={(e) => setKbQuery(e.target.value)}
                className="w-full h-10 pl-9 pr-3 rounded-lg bg-background border border-input text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
            </div>
            <button type="button" onClick={() => setCreating((v) => !v)}
              className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2.5 text-sm font-medium hover:bg-primary/90 active:scale-[0.98] transition-[transform,background-color]">
              <Plus className="w-4 h-4" />
              <span>新建知识库</span>
            </button>
            {creating && (
              <div className="flex gap-2">
                <input autoFocus value={newName} placeholder="库名称，如：工作笔记"
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newName.trim()) create()
                    if (e.key === 'Escape') setCreating(false)
                  }}
                  className="flex-1 min-w-0 h-9 px-3 rounded-lg bg-background border border-input text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
                <button type="button" disabled={working || !newName.trim()}
                  onClick={create}
                  className="rounded-lg bg-primary text-primary-foreground px-3 text-sm font-medium hover:bg-primary/90 disabled:opacity-50">
                  创建
                </button>
              </div>
            )}
          </div>
          <nav className="flex-1 px-3 pb-4 space-y-1 overflow-y-auto">
            {kbs.length === 0 && (
              <p className="px-3 text-xs text-muted-foreground">还没有知识库，先创建一个。</p>
            )}
            {filtered.map((k, idx) => {
              const Icon = KB_ICONS[idx % KB_ICONS.length]
              const active = k.id === kbId
              const healthy = (k.stats?.failed ?? 0) === 0
              return (
                <div key={k.id} className="group relative">
                  <button type="button" onClick={() => setKbId(k.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                      active
                        ? 'font-medium bg-background text-foreground border border-border shadow-sm'
                        : 'text-foreground hover:bg-background transition-colors border border-transparent'}`}>
                    <Icon className={`w-4 h-4 ${active ? 'text-primary' : 'text-muted-foreground'}`} />
                    <span className="flex-1 text-left truncate">{k.name}</span>
                    <span className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: healthy ? 'var(--rag-state-success)' : 'var(--rag-state-warning)' }} />
                  </button>
                  <button type="button" aria-label="删除知识库" disabled={working}
                    onClick={() => {
                      if (!confirm(`删除知识库「${k.name}」？将同时删除注册、索引与库目录中的全部原始文件，不可恢复。`)) return
                      run(() => deleteKb(k.id)).then(() => { if (kbId === k.id) setKbId(null) })
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 hidden group-hover:inline-flex w-6 h-6 items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-background">
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              )
            })}
          </nav>
        </aside>

        {/* 主区 */}
        <section className="kb-main bg-background">
          <div className="p-6 lg:p-8 space-y-8">
            {!kbId && <p className="text-muted-foreground">左侧选择或创建知识库后，在这里管理文档。</p>}
            {kbId && (
              <>
                {err && (
                  <div className="rounded-lg border px-3 py-2 text-sm"
                    style={{ background: 'color-mix(in srgb, var(--rag-state-error) 10%, transparent)',
                             borderColor: 'color-mix(in srgb, var(--rag-state-error) 35%, transparent)',
                             color: 'var(--rag-state-error)' }}>
                    ⚠ {err}
                  </div>
                )}

                {/* 页头 */}
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                  <div className="space-y-1">
                    <h1 className="text-2xl font-bold tracking-tight text-foreground">{current?.name || '知识库'}</h1>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      本地知识库，用于存放文档与索引。{current?.path ? `（${current.path}）` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button type="button" disabled={working}
                      onClick={() => run(() => ingestKb(kbId), { poll: true })}
                      className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-card text-foreground px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50 transition-colors">
                      <RefreshCw className="w-4 h-4" />
                      <span>扫描库目录入库</span>
                    </button>
                    <button type="button" disabled={working}
                      onClick={() => { if (confirm('清空索引并全量重建？')) run(() => rebuildKb(kbId), { poll: true }) }}
                      className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-card text-foreground px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50 transition-colors">
                      <Layers className="w-4 h-4" />
                      <span>重建索引</span>
                    </button>
                    <button type="button" aria-label="删除知识库" disabled={working}
                      onClick={() => {
                        if (!confirm(`删除知识库「${current?.name}」？将同时删除注册、索引与库目录中的全部原始文件，不可恢复。`)) return
                        run(() => deleteKb(kbId)).then(() => setKbId(null))
                      }}
                      className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-border bg-card hover:bg-muted disabled:opacity-50 transition-colors">
                      <Trash2 className="w-4 h-4" style={{ color: 'var(--rag-state-error)' }} />
                    </button>
                  </div>
                </div>

                {/* 统计卡 */}
                <div className="kb-stats-grid">
                  <StatCard icon={FileText} value={stats?.documents ?? current?.stats?.documents ?? 0} label="文档数" />
                  <StatCard icon={Layers} value={stats?.chunks ?? current?.stats?.chunks ?? 0} label="切片数" />
                  <StatCard icon={CheckCircle2}
                    value={(stats?.failed ?? current?.stats?.failed ?? 0) > 0 ? '有失败' : '已就绪'}
                    label="索引状态"
                    color={(stats?.failed ?? current?.stats?.failed ?? 0) > 0 ? 'var(--rag-state-warning)' : 'var(--rag-state-success)'} />
                  <StatCard icon={HardDrive} value={fmtSize(stats?.size_bytes)} label="占用空间" />
                </div>

                {/* 后台入库进度 */}
                {job && job.status === 'running' && (
                  <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-foreground"
                    style={{ boxShadow: 'var(--rag-shadow-1)' }}>
                    <span className="inline-block w-2 h-2 rounded-full mr-2 align-middle"
                      style={{ backgroundColor: 'var(--rag-state-info, var(--rag-primary))' }} />
                    入库中 {job.done}/{job.total}
                    {job.file ? <span className="text-muted-foreground"> · {job.file}</span> : null}
                  </div>
                )}

                {/* 上传区（点击 + 拖拽） */}
                <div
                  onClick={() => fileRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={(e) => { e.preventDefault(); setDragOver(false); doUpload(Array.from(e.dataTransfer.files || [])) }}
                  className={`rounded-xl border-2 border-dashed p-8 text-center cursor-pointer transition-colors ${
                    dragOver ? 'border-primary bg-primary/5' : 'border-border bg-card hover:bg-muted/50'}`}>
                  <input ref={fileRef} type="file" multiple className="sr-only"
                    onChange={doUpload} accept=".md,.txt,.docx,.pptx,.xlsx,.pdf" />
                  <span className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-accent text-accent-foreground mb-3">
                    <Upload className="w-6 h-6" />
                  </span>
                  <p className="text-base font-medium text-foreground">
                    {working ? '入库中…' : '点击或拖拽文件至此上传'}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    支持 PDF、DOCX、TXT、Markdown 等格式；大文件自动后台入库并显示进度
                  </p>
                </div>

                {/* 文档表 */}
                <div className="rounded-xl border border-border bg-card overflow-hidden" style={{ boxShadow: 'var(--rag-shadow-1)' }}>
                  <div className="overflow-x-auto">
                    <table className="kb-doc-table">
                      <thead>
                        <tr className="border-b border-border bg-muted/50">
                          <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">文件名</th>
                          <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">类型</th>
                          <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">大小</th>
                          <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">状态</th>
                          <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider">更新时间</th>
                          <th className="px-4 py-3 text-xs font-medium text-muted-foreground uppercase tracking-wider text-right">操作</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {docs.map((d) => {
                          const ok = d.status === 'ok'
                          const ext = (d.rel_path.split('.').pop() || '').toUpperCase()
                          return (
                            <tr key={d.id} className="hover:bg-muted/50 transition-colors">
                              <td className="px-4 py-3 text-sm text-foreground">
                                {d.rel_path}
                                {d.error && <p className="text-xs mt-0.5" style={{ color: 'var(--rag-state-error)' }}>{d.error}</p>}
                              </td>
                              <td className="px-4 py-3 text-sm text-muted-foreground">{ext}</td>
                              <td className="px-4 py-3 text-sm text-muted-foreground">{fmtSize(d.size)}</td>
                              <td className="px-4 py-3">
                                <span className="inline-flex items-center gap-1.5 text-sm text-foreground">
                                  <span className="w-2 h-2 rounded-full"
                                    style={{ backgroundColor: ok ? 'var(--rag-state-success)' : 'var(--rag-state-error)' }} />
                                  {ok ? '已索引' : '失败'}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-sm text-muted-foreground">
                                {d.mtime ? new Date(d.mtime * 1000).toLocaleDateString() : '—'}
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex items-center justify-end gap-1">
                                  <button type="button" aria-label="预览切分" disabled={working}
                                    onClick={() => openPreview(d)}
                                    className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-50 transition-colors">
                                    <Eye className="w-4 h-4" />
                                  </button>
                                  <button type="button" aria-label="重新索引" disabled={working}
                                    onClick={() => run(() => ingestKb(kbId, d.rel_path), { poll: true })}
                                    className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-50 transition-colors">
                                    <RefreshCw className="w-4 h-4" />
                                  </button>
                                  <button type="button" aria-label="删除" disabled={working}
                                    onClick={() => { if (confirm(`删除 ${d.rel_path}？磁盘上的原始文件将一并删除，不可恢复。`)) run(() => deleteDoc(kbId, d.id)) }}
                                    className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-50 transition-colors"
                                    style={{ '--tw-hover-color': 'var(--rag-state-error)' }}>
                                    <Trash2 className="w-4 h-4" />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                        {docs.length === 0 && (
                          <tr>
                            <td colSpan={6} className="px-4 py-8 text-sm text-muted-foreground text-center">
                              暂无文档，上传或把文件放进库目录后点「扫描库目录入库」。
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <ReportPanel report={report} />
              </>
            )}
          </div>
        </section>
      </div>
      {preview && (
        <ChunkPreviewModal path={preview.path} data={preview.data}
          onClose={() => setPreview(null)} />
      )}
    </div>
  )
}
