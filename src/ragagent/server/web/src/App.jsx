import React, { useEffect, useState } from 'react'
import ChatPage from './ChatPage.jsx'
import KBPage from './KBPage.jsx'
import LandingPage from './LandingPage.jsx'
import Header from './Header.jsx'
import { listKbs } from './api.js'
import { useHashRoute } from './router.js'

export default function App() {
  const route = useHashRoute()
  const [kbs, setKbs] = useState([])
  const [kbId, setKbId] = useState(null)

  const refreshKbs = async () => {
    try {
      const list = await listKbs()
      setKbs(list)
      setKbId((cur) => (cur && list.some((k) => k.id === cur) ? cur : (list[0]?.id ?? null)))
    } catch { /* 服务未就绪时静默 */ }
  }
  useEffect(() => { refreshKbs() }, [])

  if (route === '/') {
    return (
      <>
        <Header route={route} landing />
        <LandingPage />
      </>
    )
  }

  return (
    <>
      <Header route={route} />
      {route === '/chat'
        ? <ChatPage kbs={kbs} kbId={kbId} setKbId={setKbId} />
        : <KBPage kbs={kbs} kbId={kbId} setKbId={setKbId} refreshKbs={refreshKbs} />}
    </>
  )
}
