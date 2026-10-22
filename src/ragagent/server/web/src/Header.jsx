import React, { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bot, Settings } from 'lucide-react'
import { getHealth, getModelSettings, probeVision, updateModelSettings } from './api.js'

const CATS = [
  { key: 'chat', label: '对话模型', modelHint: 'deepseek-ai/DeepSeek-V4-Flash' },
  { key: 'embed', label: '嵌入模型', modelHint: 'BAAI/bge-m3' },
  { key: 'rerank', label: '重排模型', modelHint: 'BAAI/bge-reranker-v2-m3' },
  { key: 'ocr', label: '图片 OCR', modelHint: 'deepseek-ai/DeepSeek-OCR' },
]
const emptyForm = () => ({
  chat: { model: '', baseUrl: '', apiKey: '' },
  embed: { model: '', baseUrl: '', apiKey: '' },
  rerank: { model: '', baseUrl: '', apiKey: '' },
  ocr: { model: '', baseUrl: '', apiKey: '' },
})

function CatSection({ cat, cfg, form, onChange }) {
  if (!cfg) return null
  const inputCls = 'w-full rounded-lg bg-background border border-input text-foreground text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring'
  return (
    <div className="space-y-2 pb-3 border-b border-border last:border-b-0">
      <p className="text-xs font-semibold text-primary uppercase tracking-wider">{cat.label}</p>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">模型名称</label>
        <input type="text" value={form.model} placeholder={cat.modelHint}
          onChange={(e) => onChange('model', e.target.value)} className={inputCls} />
      </div>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">API 地址</label>
        <input type="text" value={form.baseUrl}
          placeholder={`${cfg.base_url}（${cfg.own_base_url ? '已单独设置' : '共享，留空沿用'}）`}
          onChange={(e) => onChange('baseUrl', e.target.value)} className={inputCls} />
      </div>
      <div>
        <label className="block text-xs text-muted-foreground mb-1">API 密钥</label>
        <input type="password" value={form.apiKey}
          placeholder={cfg.key_configured
            ? `已配置（${cfg.api_key_masked}），留空不修改`
            : (cfg.own_key ? '已单独设置，留空不修改' : 'sk-…')}
          onChange={(e) => onChange('apiKey', e.target.value)} className={inputCls} />
      </div>
    </div>
  )
}

function SettingsDialog({ onClose }) {
  const [health, setHealth] = useState(null)
  const [cfg, setCfg] = useState(null)   // GET /api/settings/models
  const [form, setForm] = useState(emptyForm())
  const [tab, setTab] = useState('chat')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')     // 成功/提示信息
  const [err, setErr] = useState('')
  // 图片通道附属（ocr tab）
  const [mineruKey, setMineruKey] = useState('')
  const [mineruBase, setMineruBase] = useState('')
  const [describe, setDescribe] = useState(true)
  // 视觉能力探测
  const [probe, setProbe] = useState(null)   // true/false/字符串错误

  const resetFrom = (s) => {
    setForm({
      chat: { model: s.chat.model, baseUrl: '', apiKey: '' },
      embed: { model: s.embed.model, baseUrl: '', apiKey: '' },
      rerank: { model: s.rerank.model, baseUrl: '', apiKey: '' },
      ocr: { model: s.ocr.model, baseUrl: '', apiKey: '' },
    })
    setMineruKey(''); setMineruBase('')
    setDescribe(s.image_describe)
  }

  const loadAll = async () => {
    try {
      const [h, s] = await Promise.all([getHealth(), getModelSettings()])
      setHealth(h); setCfg(s)
      resetFrom(s)  // 模型名预填当前值；地址/密钥保持留空（输入 = 写覆盖）
    } catch (e) { setErr(String(e.message || e)) }
  }
  useEffect(() => { loadAll() }, [])

  const change = (cat, field, value) =>
    setForm((f) => ({ ...f, [cat]: { ...f[cat], [field]: value } }))

  const save = async () => {
    if (!cfg) return
    setErr(''); setMsg('')
    // 构造 payload：模型必填（预填值原样提交）；地址/密钥仅输入才提交
    const payload = {}
    for (const cat of CATS) {
      const f = form[cat.key]
      const cur = cfg[cat.key]
      const entry = {}
      const model = f.model.trim()
      if (!model) { setErr(`${cat.label}：模型名称不能为空`); return }
      if (model !== cur.model) entry.model = model
      if (f.baseUrl.trim()) entry.base_url = f.baseUrl.trim()
      if (f.apiKey.trim()) entry.api_key = f.apiKey.trim()
      if (Object.keys(entry).length > 0) payload[cat.key] = entry
    }
    // 图片通道附属配置（仅提交有变化/有输入的）
    if (mineruKey.trim()) payload.mineru = { ...(payload.mineru || {}), api_key: mineruKey.trim() }
    if (mineruBase.trim()) payload.mineru = { ...(payload.mineru || {}), base_url: mineruBase.trim() }
    if (cfg && describe !== cfg.image_describe) payload.image_describe = describe
    if (Object.keys(payload).length === 0) { setMsg('无更改'); return }
    setSaving(true)
    try {
      const s = await updateModelSettings(payload)
      setCfg(s)
      resetFrom(s)  // 已持久化的输入清空；模型名按回显刷新
      setMsg('✓ 已保存，即刻生效')
      const h = await getHealth().catch(() => null)
      if (h) setHealth(h)
      window.dispatchEvent(new Event('settings-changed'))
      setTimeout(() => setMsg(''), 3000)
    } catch (e) { setErr(String(e.message || e)) }
    finally { setSaving(false) }
  }

  const runProbe = async () => {
    setErr(''); setProbe('检测中…')
    try {
      const r = await probeVision()
      setProbe(r.supported ? '✅ 支持图片输入' : '❌ 纯文本模型（回答将自动降级为仅文字）')
      window.dispatchEvent(new Event('settings-changed'))
    } catch (e) { setProbe(`探测失败：${e.message || e}`) }
  }

  const infoRows = health && [
    ['版本', health.version],
    ['共享 Key', health.key_configured ? '已配置' : '未配置'],
    ['知识库', (health.knowledge_bases || []).join('、') || '无'],
  ]

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl border border-border bg-popover overflow-y-auto"
        style={{ maxHeight: '85vh', boxShadow: 'var(--rag-shadow-3)' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-border sticky top-0 bg-popover">
          <h3 className="text-base font-semibold text-foreground">设置</h3>
          <button onClick={onClose} aria-label="关闭"
            className="w-8 h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">×</button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* 三类模型切换栏（置顶）：圆点 = 该类已有单独覆盖 */}
          <div className="flex gap-1 rounded-lg bg-muted p-1" role="tablist">
            {CATS.map((cat) => {
              const active = tab === cat.key
              const c = cfg?.[cat.key]
              const overridden = c && (c.own_key || c.own_base_url)
              return (
                <button key={cat.key} type="button" role="tab"
                  aria-selected={active} onClick={() => setTab(cat.key)}
                  className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 text-sm rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    active
                      ? 'bg-primary text-primary-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground'}`}>
                  {cat.label}
                  {overridden && (
                    <span className="w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: active ? 'var(--rag-primary-foreground)' : 'var(--rag-primary)' }} />
                  )}
                </button>
              )
            })}
          </div>

          <CatSection
            cat={CATS.find((c) => c.key === tab)}
            cfg={cfg?.[tab]}
            form={form[tab]}
            onChange={(field, value) => change(tab, field, value)} />

          {/* 对话模型页：多模态能力探测 */}
          {tab === 'chat' && (
            <div className="flex items-center gap-3 pb-3 border-b border-border">
              <button type="button" onClick={runProbe}
                className="inline-flex items-center justify-center rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors">
                检测视觉能力
              </button>
              {probe && <span className="text-xs text-muted-foreground">{probe}</span>}
            </div>
          )}

          {/* 图片 OCR 页：MinerU 扫描件通道 + 图片解析开关 */}
          {tab === 'ocr' && (
            <div className="space-y-2 pb-3 border-b border-border">
              <p className="text-xs font-semibold text-primary uppercase tracking-wider">扫描件解析（MinerU）</p>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">MinerU 密钥</label>
                <input type="password" value={mineruKey} onChange={(e) => setMineruKey(e.target.value)}
                  placeholder={cfg?.mineru?.key_configured
                    ? `已配置（${cfg.mineru.api_key_masked}），留空不修改`
                    : 'sk-…（缺省则扫描件 PDF 不做文字提取）'}
                  className="w-full rounded-lg bg-background border border-input text-foreground text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">MinerU 地址</label>
                <input type="text" value={mineruBase} onChange={(e) => setMineruBase(e.target.value)}
                  placeholder={`${cfg?.mineru?.base_url || 'https://mineru.net/api/v4'}（留空沿用）`}
                  className="w-full rounded-lg bg-background border border-input text-foreground text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
              <label className="flex items-center gap-2 text-sm text-foreground pt-1 cursor-pointer">
                <input type="checkbox" checked={describe}
                  onChange={(e) => setDescribe(e.target.checked)}
                  className="accent-[var(--rag-primary)]" />
                图片解析入库（抽图 → OCR 文字化 → 可检索；关闭则图片仅计数）
              </label>
            </div>
          )}

          <p className="text-xs text-muted-foreground leading-relaxed">
            地址与密钥<b>留空则回退</b>共享的 SILICONFLOW_BASE_URL / SILICONFLOW_API_KEY；
            地址需 OpenAI 兼容，重排需兼容 /rerank 协议。要清除已有的单独覆盖请直接编辑 .env。
            图片 OCR 用于把文档图片文字化；回答时命中图片会自动附给多模态对话模型，
            纯文本对话模型会自动降级为仅文字。
          </p>

          <div className="flex items-center gap-3 pt-1">
            <button type="button" onClick={save} disabled={saving || !cfg}
              className="inline-flex items-center justify-center rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 active:scale-[0.98] disabled:opacity-50 transition-[transform,background-color]">
              {saving ? '保存中…' : '保存'}
            </button>
            {msg && <span className="text-sm" style={{ color: 'var(--rag-state-success)' }}>{msg}</span>}
            {err && <span className="text-sm" style={{ color: 'var(--rag-state-error)' }}>{err}</span>}
          </div>

          {infoRows && (
            <div className="border-t border-border pt-4 space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">系统信息</p>
              <dl className="space-y-2 text-sm">
                {infoRows.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="text-right break-all">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {!health && !err && <p className="text-sm text-muted-foreground">加载中…</p>}
        </div>
      </div>
    </div>,
    document.body,
  )
}

const NAV = [
  { path: '/', label: '首页' },
  { path: '/chat', label: '对话' },
  { path: '/kb', label: '知识库' },
]

export default function Header({ route, landing = false }) {
  const [showSettings, setShowSettings] = useState(false)

  if (landing) {
    return (
      <header className="fixed top-0 left-0 right-0 z-50 bg-background/95 backdrop-blur border-b border-border">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <a href="#/" className="flex items-center gap-2 text-foreground font-semibold text-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg">
            <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground">
              <Bot className="w-5 h-5" />
            </span>
            <span>RAG-Agent</span>
          </a>
          <nav className="hidden md:flex items-center gap-8">
            <a href="#section-capabilities" className="text-sm text-foreground hover:text-primary transition-colors rounded">能力</a>
            <a href="#section-workflow" className="text-sm text-foreground hover:text-primary transition-colors rounded">工作流</a>
            <a href="#section-usecases" className="text-sm text-foreground hover:text-primary transition-colors rounded">场景</a>
            <a href="#/chat" className="text-sm text-foreground hover:text-primary transition-colors rounded">对话</a>
            <a href="#/kb" className="text-sm text-foreground hover:text-primary transition-colors rounded">知识库</a>
          </nav>
          <a href="#/chat" className="inline-flex items-center rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 active:scale-[0.98] transition-[transform,background-color]">
            开始使用
          </a>
        </div>
      </header>
    )
  }

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-background/95 backdrop-blur border-b border-border">
      <div className="max-w-full mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <a href="#/" className="flex items-center gap-2 text-foreground font-semibold text-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground">
            <Bot className="w-5 h-5" />
          </span>
          <span>RAG-Agent</span>
        </a>
        <nav className="hidden md:flex items-center gap-1">
          {NAV.map((n) => (
            <a key={n.path} href={`#${n.path}`}
              aria-current={route === n.path ? 'page' : undefined}
              className={`px-3 py-2 text-sm rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                route === n.path
                  ? 'text-primary font-medium'
                  : 'text-foreground hover:text-primary transition-colors'}`}>
              {n.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setShowSettings(true)}
            className="inline-flex items-center justify-center w-9 h-9 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors"
            aria-label="设置">
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </div>
      {showSettings && <SettingsDialog onClose={() => setShowSettings(false)} />}
    </header>
  )
}
