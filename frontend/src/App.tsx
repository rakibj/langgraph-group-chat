import { useRef, useState } from 'react'
import { sendMessage } from './api/client'
import './App.css'

type Message = {
  role: 'user' | 'assistant'
  content: string
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const threadId = useRef(crypto.randomUUID())

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setSending(true)

    try {
      const { reply } = await sendMessage(threadId.current, text)
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '(error contacting agent)' },
      ])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="app">
      <main className="app-main">
        <h1>LangGraph Starter</h1>
        <div className="chat-window">
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content}
            </div>
          ))}
          {sending && <div className="bubble assistant pending">thinking...</div>}
        </div>
        <form
          className="chat-input"
          onSubmit={(e) => {
            e.preventDefault()
            handleSend()
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask something..."
          />
          <button type="submit" disabled={sending}>
            Send
          </button>
        </form>
      </main>
    </div>
  )
}

export default App
