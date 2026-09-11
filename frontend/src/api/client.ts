const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export async function checkHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error(`health check failed: ${res.status}`)
  return res.json()
}

export async function sendMessage(threadId: string, message: string): Promise<{ reply: string }> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id: threadId, message }),
  })
  if (!res.ok) throw new Error(`chat request failed: ${res.status}`)
  return res.json()
}
