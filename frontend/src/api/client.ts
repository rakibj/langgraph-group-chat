const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export async function checkHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error(`health check failed: ${res.status}`)
  return res.json()
}

export type PersonaReply = {
  persona: string
  content: string
}

export async function sendMessage(
  threadId: string,
  message: string,
): Promise<{ replies: PersonaReply[] }> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, message }),
  })
  if (!res.ok) throw new Error(`chat request failed: ${res.status}`)
  return res.json()
}

export type ThreadSummary = {
  thread_id: string
  title: string
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
}

export async function getThreadMessages(
  threadId: string,
): Promise<{ messages: ThreadMessage[] }> {
  const res = await fetch(`${API_BASE}/threads/${threadId}/messages`)
  if (!res.ok) throw new Error(`get thread messages failed: ${res.status}`)
  return res.json()
}
