import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { sendMessage } from './api/client'
import './App.css'

type Message = {
  role: 'user' | 'assistant'
  content: string
  persona?: string
}

const PERSONA_LABELS: Record<string, string> = {
  pragmatist: 'Pragmatist',
  skeptic: 'Skeptic',
  optimist: 'Optimist',
  analyst: 'Analyst',
  contrarian: 'Contrarian',
  people_person: 'People Person',
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const threadId = useRef(crypto.randomUUID())
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setSending(true)

    try {
      const { replies } = await sendMessage(threadId.current, text)
      setMessages((prev) => [
        ...prev,
        ...replies.map((r) => ({
          role: 'assistant' as const,
          content: r.content,
          persona: r.persona,
        })),
      ])
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
      <header className="chat-header">
        <div className="chat-header-avatar">AI</div>
        <div className="chat-header-title">Agent</div>
      </header>

      <div className="chat-window" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">Say something to start the conversation</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>
              {m.role === 'assistant' && m.persona && (
                <div className="bubble-persona">
                  {PERSONA_LABELS[m.persona] ?? m.persona}
                </div>
              )}
              {m.role === 'assistant' ? (
                <ReactMarkdown>{m.content}</ReactMarkdown>
              ) : (
                m.content
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="bubble-row assistant">
            <div className="bubble assistant typing">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}
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
          placeholder="iMessage"
        />
        <button type="submit" disabled={!input.trim() || sending} aria-label="Send">
          ↑
        </button>
      </form>
    </div>
  )
}

export default App
