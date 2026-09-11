import { useEffect, useState } from 'react'
import { checkHealth } from './api/client'
import './App.css'

function App() {
  const [status, setStatus] = useState<'checking' | 'ok' | 'error'>('checking')

  useEffect(() => {
    checkHealth()
      .then(() => setStatus('ok'))
      .catch(() => setStatus('error'))
  }, [])

  return (
    <div className="app">
      <main className="app-main">
        <h1>LangGraph Starter</h1>
        <p>Backend status: {status}</p>
      </main>
    </div>
  )
}

export default App
