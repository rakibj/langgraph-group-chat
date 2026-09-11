import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { getThreadMessages, listThreads, sendMessage, type ThreadSummary } from './api/client'
import './App.css'

type Message = {
  role: 'user' | 'assistant'
  content: string
  persona?: string
}

type View = 'list' | 'chat'
type Theme = 'system' | 'light' | 'dark'

const PERSONA_LABELS: Record<string, string> = {
  pragmatist: 'Pragmatist',
  skeptic: 'Skeptic',
  optimist: 'Optimist',
  analyst: 'Analyst',
  contrarian: 'Contrarian',
  people_person: 'People Person',
}

const THEME_ICON: Record<Theme, string> = {
  system: '🌗',
  light: '☀️',
  dark: '🌙',
}

function nextTheme(theme: Theme): Theme {
  if (theme === 'system') return 'light'
  if (theme === 'light') return 'dark'
  return 'system'
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) {
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function App() {
  const [view, setView] = useState<View>('list')
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [threadsLoading, setThreadsLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('theme') as Theme | null) ?? 'system'
    } catch {
      return 'system'
    }
  })
  const threadId = useRef<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (theme === 'system') {
      delete document.documentElement.dataset.theme
    } else {
      document.documentElement.dataset.theme = theme
    }
    try {
      localStorage.setItem('theme', theme)
    } catch {
      // ignore storage failures (private browsing, etc.)
    }
  }, [theme])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  async function refreshThreads() {
    setThreadsLoading(true)
    try {
      const { threads } = await listThreads()
      setThreads(threads)
    } catch {
      setThreads([])
    } finally {
      setThreadsLoading(false)
    }
  }

  useEffect(() => {
    if (view === 'list') refreshThreads()
  }, [view])

  function openNewChat() {
    threadId.current = crypto.randomUUID()
    setMessages([])
    setView('chat')
  }

  async function openThread(id: string) {
    threadId.current = id
    setMessages([])
    setView('chat')
    try {
      const { messages: history } = await getThreadMessages(id)
      setMessages(
        history.map((m) => ({
          role: m.role,
          content: m.content,
          persona: m.persona ?? undefined,
        })),
      )
    } catch {
      setMessages([{ role: 'assistant', content: '(failed to load conversation)' }])
    }
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || sending || !threadId.current) return

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

  if (view === 'list') {
    return (
      <div className="app">
        <header className="chat-header">
          <div className="chat-header-title">Chats</div>
          <div className="header-actions">
            <button
              type="button"
              className="icon-button"
              aria-label="Toggle theme"
              title={`Theme: ${theme}`}
              onClick={() => setTheme(nextTheme(theme))}
            >
              {THEME_ICON[theme]}
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label="New chat"
              onClick={openNewChat}
            >
              ✎
            </button>
          </div>
        </header>

        <div className="thread-list">
          {threadsLoading && threads.length === 0 && (
            <div className="chat-empty">Loading…</div>
          )}
          {!threadsLoading && threads.length === 0 && (
            <div className="chat-empty">No conversations yet — start one</div>
          )}
          {threads.map((t) => (
            <button
              key={t.thread_id}
              type="button"
              className="thread-row"
              onClick={() => openThread(t.thread_id)}
            >
              <div className="thread-row-avatar">
                {t.title.slice(0, 1).toUpperCase()}
              </div>
              <div className="thread-row-body">
                <div className="thread-row-title">{t.title || 'New chat'}</div>
              </div>
              <div className="thread-row-time">{formatTimestamp(t.updated_at)}</div>
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="chat-header">
        <button
          type="button"
          className="icon-button back-button"
          aria-label="Back to chats"
          onClick={() => setView('list')}
        >
          ‹
        </button>
        <div className="chat-header-avatar">AI</div>
        <div className="chat-header-title">Group Chat</div>
        <div className="header-actions">
          <button
            type="button"
            className="icon-button"
            aria-label="Toggle theme"
            title={`Theme: ${theme}`}
            onClick={() => setTheme(nextTheme(theme))}
          >
            {THEME_ICON[theme]}
          </button>
        </div>
      </header>

      <div className="chat-window" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-empty">Say something to start the conversation</div>
        )}
        {messages.map((m, i) =>
          m.persona === 'manager' ? (
            <div key={i} className="manager-note">
              {m.content}
            </div>
          ) : (
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
          ),
        )}
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
