// 极简 hash 路由：#/ 落地页 · #/chat 对话 · #/kb 知识库（静态托管零配置）
import { useEffect, useState } from 'react'

export function currentRoute() {
  const h = window.location.hash.replace(/^#/, '')
  if (h.startsWith('/chat')) return '/chat'
  if (h.startsWith('/kb')) return '/kb'
  if (h === '') return '/chat'  // 进入时默认对话页（#/ 仍可访问首页）
  return '/'
}

export function navigate(path) {
  window.location.hash = path === '/' ? '/' : path
}

export function useHashRoute() {
  const [route, setRoute] = useState(currentRoute)
  useEffect(() => {
    const onChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
