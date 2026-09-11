const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export async function checkHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error(`health check failed: ${res.status}`)
  return res.json()
}

export type Strategy = 'confidence' | 'background'

export type PersonaReply = {
  persona: string
  content: string
  kind: 'routing' | 'to_user' | 'to_verdict' | 'verdict' | null
}

export async function sendMessage(
  threadId: string,
  message: string,
  strategy: Strategy,
  onReply: (reply: PersonaReply) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, message, strategy }),
  })
  if (!res.ok || !res.body) throw new Error(`chat request failed: ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const event of events) {
      const line = event.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      onReply(JSON.parse(line.slice('data: '.length)))
    }
  }
}

export type ThreadSummary = {
  thread_id: string
  title: string
  strategy: Strategy
  updated_at: string
}

export async function listThreads(): Promise<{ threads: ThreadSummary[] }> {
  const res = await fetch(`${API_BASE}/threads`)
  if (!res.ok) throw new Error(`list threads failed: ${res.status}`)
  return res.json()
}

export type ThreadMessage = {
  role: 'user' | 'assistant'
  persona: string | null
  content: string
  kind: 'routing' | 'to_user' | 'to_verdict' | 'verdict' | null
}

export async function getThreadMessages(
  threadId: string,
): Promise<{ messages: ThreadMessage[] }> {
  const res = await fetch(`${API_BASE}/threads/${threadId}/messages`)
  if (!res.ok) throw new Error(`get thread messages failed: ${res.status}`)
  return res.json()
}
