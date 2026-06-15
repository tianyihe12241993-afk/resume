import { useEffect, useRef, useState, useCallback } from 'react'
import { Send } from 'lucide-react'
import clsx from 'clsx'
import { api } from '@/lib/api'
import { Avatar } from '@/components/charts'

interface ChatMsg {
  id: number
  user_id: number | null
  name: string
  body: string
  created_at: string | null
}
interface HistoryResp {
  me: { id: number; name: string }
  messages: ChatMsg[]
}

function timeOf(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}
function dayOf(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
  } catch { return '' }
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [meId, setMeId] = useState<number | null>(null)
  const [online, setOnline] = useState(0)
  const [onlineNames, setOnlineNames] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [text, setText] = useState('')

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  // Initial history load.
  useEffect(() => {
    api.get<HistoryResp>('/api/chat/messages').then((d) => {
      setMeId(d.me.id)
      setMessages(d.messages)
      requestAnimationFrame(scrollToBottom)
    }).catch(() => {})
  }, [scrollToBottom])

  // WebSocket lifecycle with auto-reconnect.
  useEffect(() => {
    closedRef.current = false
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/chat`)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closedRef.current) {
          reconnectRef.current = setTimeout(connect, 2000)
        }
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        let m: any
        try { m = JSON.parse(ev.data) } catch { return }
        if (m.type === 'presence') {
          setOnline(m.online ?? 0)
          setOnlineNames(m.users ?? [])
        } else if (m.type === 'message') {
          setMessages((prev) => (prev.some((x) => x.id === m.id) ? prev : [...prev, m]))
        }
      }
    }
    connect()
    return () => {
      closedRef.current = true
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [])

  useEffect(() => { scrollToBottom() }, [messages, scrollToBottom])

  const send = () => {
    const body = text.trim()
    if (!body) return
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ body }))
    setText('')
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Team chat</h1>
          <p className="text-sm text-gray-400">Shared group chat for you and your bidders.</p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className={clsx('w-2 h-2 rounded-full', connected ? 'bg-green-500' : 'bg-gray-300')} />
          <span className="text-gray-500" title={onlineNames.join(', ')}>
            {connected ? `${online} online` : 'connecting…'}
          </span>
        </div>
      </div>

      <div ref={scrollRef}
           className="flex-1 overflow-y-auto card p-4 space-y-2 bg-slate-50/60">
        {messages.length === 0 && (
          <p className="text-center text-sm text-gray-400 py-10">No messages yet. Say hi 👋</p>
        )}
        {messages.map((m, i) => {
          const mine = m.user_id != null && m.user_id === meId
          const prev = messages[i - 1]
          const showDay = !prev || dayOf(prev.created_at) !== dayOf(m.created_at)
          // Group consecutive messages from the same sender.
          const grouped = !showDay && prev && prev.user_id === m.user_id
          return (
            <div key={m.id}>
              {showDay && (
                <div className="text-center my-3">
                  <span className="text-[11px] font-medium text-gray-400 bg-white border border-slate-200 rounded-full px-3 py-0.5">
                    {dayOf(m.created_at)}
                  </span>
                </div>
              )}
              <div className={clsx('flex items-end gap-2', mine ? 'flex-row-reverse' : 'flex-row')}>
                <div className="w-7 shrink-0">
                  {!mine && !grouped && <Avatar name={m.name} size={28} />}
                </div>
                <div className={clsx('max-w-[75%]')}>
                  {!grouped && (
                    <div className={clsx('text-[11px] mb-0.5', mine ? 'text-right text-gray-400' : 'text-gray-500 font-medium')}>
                      {mine ? '' : m.name}
                    </div>
                  )}
                  <div className={clsx(
                    'rounded-2xl px-3 py-1.5 text-sm whitespace-pre-wrap break-words shadow-sm',
                    mine ? 'bg-brand-600 text-white rounded-br-sm'
                         : 'bg-white border border-slate-200 text-gray-800 rounded-bl-sm',
                  )}>
                    {m.body}
                    <span className={clsx('ml-2 align-bottom text-[10px]', mine ? 'text-indigo-200' : 'text-gray-400')}>
                      {timeOf(m.created_at)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <form
        className="mt-3 flex items-end gap-2"
        onSubmit={(e) => { e.preventDefault(); send() }}
      >
        <textarea
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
          }}
          placeholder={connected ? 'Message your team…' : 'Reconnecting…'}
          disabled={!connected}
          className="input flex-1 resize-none max-h-32"
        />
        <button type="submit" disabled={!connected || !text.trim()}
                className="btn-primary h-10 px-4 shrink-0">
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  )
}
