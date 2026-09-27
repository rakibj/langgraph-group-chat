import { useEffect, useRef, useState, type CSSProperties } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  getThreadMessages,
  listThreads,
  sendMessage,
  type MessageKind,
  type Strategy,
  type ThreadSummary,
} from './api/client'
import './App.css'

type Message = {
  role: 'user' | 'assistant'
  content: string
  persona?: string
  kind?: MessageKind
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
  manager: 'Manager',
  group: 'The Group',
}

const PERSONA_COLORS: Record<string, string> = {
  pragmatist: 'var(--persona-pragmatist)',
  skeptic: 'var(--persona-skeptic)',
  optimist: 'var(--persona-optimist)',
  analyst: 'var(--persona-analyst)',
  contrarian: 'var(--persona-contrarian)',
  people_person: 'var(--persona-people_person)',
  manager: 'var(--persona-manager)',
  group: 'var(--persona-manager)',
}

const STRATEGY_LABELS: Record<Strategy, string> = {
  confidence: 'Manager thinks out loud',
  background: 'Friends only',
  debate: 'Brief the manager, then let them fight',
}

const STRATEGY_HINTS: Record<Strategy, string> = {
  confidence: "You'll see who's being routed to and why, plus an explicit verdict when the group is confident.",
  background: 'No routing chatter — just the friends talking, with a final group take once they land somewhere.',
  debate: 'The manager asks you what matters, then the six argue it out with each other, vote, and the manager calls it.',
}

const STRATEGY_BADGE: Record<Strategy, string> = {
  confidence: '🧠',
  background: '👥',
  debate: '🔥',
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
  const [strategy, setStrategy] = useState<Strategy | null>(null)
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
    setStrategy(null)
    setView('chat')
  }

  async function openThread(t: ThreadSummary) {
    threadId.current = t.thread_id
    setMessages([])
    setStrategy(t.strategy)
    setView('chat')
    try {
      const { messages: history } = await getThreadMessages(t.thread_id)
      setMessages(
        history.map((m) => ({
          role: m.role,
          content: m.content,
          persona: m.persona ?? undefined,
          kind: m.kind,
        })),
      )
    } catch {
      setMessages([{ role: 'assistant', content: '(failed to load conversation)' }])
    }
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || sending || !threadId.current || !strategy) return

    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setInput('')
    setSending(true)

    try {
      await sendMessage(threadId.current, text, strategy, (reply) => {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: reply.content,
            persona: reply.persona,
            kind: reply.kind,
          },
        ])
      })
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
              onClick={() => openThread(t)}
            >
              <div className="thread-row-avatar">
                {t.title.slice(0, 1).toUpperCase()}
              </div>
              <div className="thread-row-body">
                <div className="thread-row-title">
                  <span className="thread-row-badge" title={STRATEGY_LABELS[t.strategy]}>
                    {STRATEGY_BADGE[t.strategy]}
                  </span>
                  {t.title || 'New chat'}
                </div>
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
        <div className="chat-header-title">
          Group Chat
          {strategy && (
            <span className="chat-header-strategy" title={STRATEGY_LABELS[strategy]}>
              {STRATEGY_BADGE[strategy]}
            </span>
          )}
        </div>
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
        {!strategy && (
          <div className="strategy-chooser">
            <div className="strategy-chooser-title">How should this group run?</div>
            {(['confidence', 'background', 'debate'] as Strategy[]).map((s) => (
              <button
                key={s}
                type="button"
                className="strategy-option"
                onClick={() => setStrategy(s)}
              >
                <div className="strategy-option-label">
                  {STRATEGY_BADGE[s]} {STRATEGY_LABELS[s]}
                </div>
                <div className="strategy-option-hint">{STRATEGY_HINTS[s]}</div>
              </button>
            ))}
          </div>
        )}
        {strategy && messages.length === 0 && (
          <div className="chat-empty">
            {strategy === 'debate'
              ? "Tell the manager what you're trying to decide"
              : 'Say something to start the conversation'}
          </div>
        )}
        {messages.map((m, i) => {
          if (m.persona === 'manager' && (m.kind === 'routing' || m.kind === 'vote_call')) {
            return (
              <div key={i} className="manager-note">
                {m.content}
              </div>
            )
          }

          const color = m.persona ? PERSONA_COLORS[m.persona] : undefined
          const isHighlighted =
            (m.persona === 'manager' && (m.kind === 'to_user' || m.kind === 'kickoff')) ||
            m.kind === 'verdict'
          const bubble = (
            <div key={i} className={`bubble-row ${m.role}`}>
              <div
                className={`bubble ${m.role}${isHighlighted ? ' manager-highlight' : ''}${
                  m.kind === 'verdict' ? ' verdict-bubble' : ''
                }${m.kind === 'vote' ? ' vote-bubble' : ''}`}
                style={color ? ({ '--accent': color } as CSSProperties) : undefined}
              >
                {m.role === 'assistant' && m.persona && (
                  <div className="bubble-persona" style={{ color }}>
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
          )
          if (m.kind !== 'kickoff') return bubble
          return [
            bubble,
            <div key={`${i}-divider`} className="chat-divider">
              🔥 group chat started
            </div>,
          ]
        })}
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
          placeholder={strategy ? 'iMessage' : 'Pick a strategy above to start'}
          disabled={!strategy}
        />
        <button type="submit" disabled={!strategy || !input.trim() || sending} aria-label="Send">
          ↑
        </button>
      </form>
    </div>
  )
}

export default App
