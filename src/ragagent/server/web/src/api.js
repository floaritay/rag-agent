// 后端 API 封装：REST + SSE 流式读取

async function json(resp) {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try { detail = (await resp.json()).detail || detail } catch { /* ignore */ }
    throw new Error(detail)
  }
  return resp.json()
}

export const listKbs = () => fetch('/api/kb').then(json)
export const getHealth = () => fetch('/api/health').then(json)
export const getModelSettings = () => fetch('/api/settings/models').then(json)
export const updateModelSettings = (payload) => fetch('/api/settings/models', {
  method: 'PUT', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
}).then(json)
export const probeVision = () => fetch('/api/settings/models/vision-probe', {
  method: 'POST',
}).then(json)
export const createKb = (name) => fetch('/api/kb', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name }),
}).then(json)
export const deleteKb = (id) => fetch(`/api/kb/${id}`, { method: 'DELETE' }).then(json)
export const listDocs = (id) => fetch(`/api/kb/${id}/documents`).then(json)
export const getDocChunks = (kbId, docId) =>
  fetch(`/api/kb/${kbId}/documents/${docId}/chunks`).then(json)
export const deleteDoc = (kbId, docId) => fetch(`/api/kb/${kbId}/documents/${docId}`, { method: 'DELETE' }).then(json)
export const ingestKb = (kbId, path = '') => fetch(`/api/kb/${kbId}/ingest`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(path ? { path } : {}),
}).then(json)
export const rebuildKb = (kbId) => fetch(`/api/kb/${kbId}/rebuild`, { method: 'POST' }).then(json)
export const kbStats = (kbId) => fetch(`/api/kb/${kbId}/stats`).then(json)
export const getIngestStatus = (kbId) => fetch(`/api/kb/${kbId}/ingest-status`).then(json)
export const uploadFiles = (kbId, files) => {
  const fd = new FormData()
  for (const f of files) fd.append('files', f)
  return fetch(`/api/kb/${kbId}/upload`, { method: 'POST', body: fd }).then(json)
}

// 会话管理
export const listSessions = () => fetch('/api/sessions').then(json)
export const createSession = (title, kbId) => fetch('/api/sessions', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ title: title || '新对话', kb_id: kbId ?? null }),
}).then(json)
export const getSession = (id) => fetch(`/api/sessions/${id}`).then(json)
export const getSessionMessages = (id) => fetch(`/api/sessions/${id}/messages`).then(json)
export const renameSession = (id, title) => fetch(`/api/sessions/${id}`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ title }),
}).then(json)
export const deleteSession = (id) => fetch(`/api/sessions/${id}`, { method: 'DELETE' }).then(json)

// SSE：解析 data: {...}\n\n 事件流，逐事件回调；signal 支持中途停止（AbortController）
export async function streamChat({ kbId, sessionId, message, onEvent, signal }) {
  let resp
  try {
    resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kb_id: kbId, message, session_id: sessionId }),
      signal,
    })
  } catch (e) {
    if (e.name === 'AbortError') return  // 用户主动停止：静默结束
    onEvent({ type: 'error', message: `网络错误：${e.message}` })
    return
  }
  if (!resp.ok || !resp.body) {
    onEvent({ type: 'error', message: `HTTP ${resp.status}` })
    return
  }
  const reader = resp.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    let done, value
    try {
      ({ done, value } = await reader.read())
    } catch (e) {
      if (e.name === 'AbortError') break  // 停止：保留已收到的部分内容
      throw e
    }
    if (done) break
    buf += dec.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 2)
      if (!block.startsWith('data:')) continue
      try { onEvent(JSON.parse(block.slice(5))) } catch { /* 忽略坏帧 */ }
    }
  }
}
