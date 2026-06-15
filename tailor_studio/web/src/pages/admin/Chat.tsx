import { useEffect, useRef, useState, useCallback } from 'react'
import { Send, Reply, X } from 'lucide-react'
import clsx from 'clsx'
import { api } from '@/lib/api'
import { Avatar } from '@/components/charts'

interface QuotedMsg { id: number; name: string; body: string }
interface ChatMsg {
  id: number
  user_id: number | null
  name: string
  body: string
  reply_to?: QuotedMsg | null
  created_at: string | null
}
interface HistoryResp {
  me: { id: number; name: string }
  messages: ChatMsg[]
}
interface Member { id: number; name: string }

const MENTION_RE = /@(all|everyone|[A-Za-z0-9._-]+)/g

function timeOf(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch { return '' }
}
function dayOf(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) }
  catch { return '' }
}

// Find an in-progress "@token" immediately before the caret.
function activeMention(value: string, caret: number): { start: number; query: string } | null {
  let i = caret - 1
  while (i >= 0 && /[A-Za-z0-9._-]/.test(value[i])) i--
  if (i < 0 || value[i] !== '@') return null
  if (i > 0 && !/\s/.test(value[i - 1])) return null
  return { start: i, query: value.slice(i + 1, caret) }
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [meId, setMeId] = useState<number | null>(null)
  const [meName, setMeName] = useState<string>('')
  const [online, setOnline] = useState(0)
  const [onlineNames, setOnlineNames] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [text, setText] = useState('')
  const [replyTo, setReplyTo] = useState<ChatMsg | null>(null)
  const [members, setMembers] = useState<Member[]>([])

  // Mention autocomplete state
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null)
  const [mhi, setMhi] = useState(0)   // highlighted candidate index

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const taRef = useRef<HTMLTextAreaElement | null>(null)

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  useEffect(() => {
    api.get<HistoryResp>('/api/chat/messages').then((d) => {
      setMeId(d.me.id); setMeName(d.me.name); setMessages(d.messages)
      requestAnimationFrame(scrollToBottom)
    }).catch(() => {})
    api.get<{ members: Member[] }>('/api/chat/members')
      .then((d) => setMembers(d.members)).catch(() => {})
  }, [scrollToBottom])

  useEffect(() => {
    closedRef.current = false
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/chat`)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closedRef.current) reconnectRef.current = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        let m: any
        try { m = JSON.parse(ev.data) } catch { return }
        if (m.type === 'presence') { setOnline(m.online ?? 0); setOnlineNames(m.users ?? []) }
        else if (m.type === 'message') {
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

  // Mention candidates: every member + a synthetic "all".
  const candidates = (() => {
    if (!mention) return []
    const q = mention.query.toLowerCase()
    const all = [{ id: -1, name: 'all' }, ...members]
    return all.filter((c) => c.name.toLowerCase().startsWith(q)).slice(0, 6)
  })()

  const onChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value
    setText(v)
    const m = activeMention(v, e.target.selectionStart ?? v.length)
    setMention(m); setMhi(0)
  }

  const insertMention = (name: string) => {
    if (!mention) return
    const before = text.slice(0, mention.start)
    const after = text.slice(mention.start + 1 + mention.query.length)
    const next = `${before}@${name} ${after}`
    setText(next)
    setMention(null)
    requestAnimationFrame(() => {
      const ta = taRef.current
      if (ta) { const pos = before.length + name.length + 2; ta.focus(); ta.setSelectionRange(pos, pos) }
    })
  }

  const send = () => {
    const body = text.trim()
    if (!body) return
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ body, reply_to_id: replyTo?.id ?? null }))
    setText(''); setReplyTo(null); setMention(null)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention && candidates.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMhi((i) => (i + 1) % candidates.length); return }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setMhi((i) => (i - 1 + candidates.length) % candidates.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insertMention(candidates[mhi].name); return }
      if (e.key === 'Escape') { setMention(null); return }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  // Does this message @-mention me (or everyone)?
  const mentionsMe = (body: string): boolean => {
    const toks = body.match(MENTION_RE) || []
    return toks.some((t) => {
      const n = t.slice(1).toLowerCase()
      return n === 'all' || n === 'everyone' || n === meName.toLowerCase()
    })
  }

  // Render body with @mentions highlighted as a chip that stays readable on
  // both bubble colors (mine = indigo bg → light chip; others = white bg → indigo chip).
  const renderBody = (body: string, mine: boolean) => {
    const chip = mine
      ? 'bg-white/25 text-white font-semibold rounded px-1'
      : 'bg-brand-50 text-brand-700 font-semibold rounded px-1'
    const parts: React.ReactNode[] = []
    let last = 0
    body.replace(MENTION_RE, (match, _g, idx: number) => {
      if (idx > last) parts.push(body.slice(last, idx))
      parts.push(<span key={idx} className={chip}>{match}</span>)
      last = idx + match.length
      return match
    })
    if (last < body.length) parts.push(body.slice(last))
    return parts
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

      <div ref={scrollRef} className="flex-1 overflow-y-auto card p-4 space-y-1.5 bg-slate-50/60">
        {messages.length === 0 && (
          <p className="text-center text-sm text-gray-400 py-10">No messages yet. Say hi 👋</p>
        )}
        {messages.map((m, i) => {
          const mine = m.user_id != null && m.user_id === meId
          const prev = messages[i - 1]
          const showDay = !prev || dayOf(prev.created_at) !== dayOf(m.created_at)
          const grouped = !showDay && prev && prev.user_id === m.user_id && !m.reply_to
          const pinged = !mine && mentionsMe(m.body)
          return (
            <div key={m.id}>
              {showDay && (
                <div className="text-center my-3">
                  <span className="text-[11px] font-medium text-gray-400 bg-white border border-slate-200 rounded-full px-3 py-0.5">
                    {dayOf(m.created_at)}
                  </span>
                </div>
              )}
              <div className={clsx('group flex items-end gap-2', mine ? 'flex-row-reverse' : 'flex-row')}>
                <div className="w-7 shrink-0">{!mine && !grouped && <Avatar name={m.name} size={28} />}</div>
                <div className="max-w-[78%]">
                  {!grouped && (
                    <div className={clsx('text-[11px] mb-0.5', mine ? 'text-right text-gray-400' : 'text-gray-500 font-medium')}>
                      {mine ? '' : m.name}
                    </div>
                  )}
                  <div className={clsx(
                    'rounded-2xl px-3 py-1.5 text-sm whitespace-pre-wrap break-words shadow-sm',
                    mine ? 'bg-brand-600 text-white rounded-br-sm'
                         : pinged ? 'bg-amber-50 border border-amber-300 text-gray-800 rounded-bl-sm'
                                  : 'bg-white border border-slate-200 text-gray-800 rounded-bl-sm',
                  )}>
                    {m.reply_to && (
                      <div className={clsx(
                        'mb-1 pl-2 border-l-2 text-xs rounded-sm py-0.5',
                        mine ? 'border-indigo-300 text-indigo-100' : 'border-brand-300 text-gray-500',
                      )}>
                        <span className="font-semibold">{m.reply_to.name}</span>
                        <span className="opacity-80"> · {m.reply_to.body.slice(0, 80)}</span>
                      </div>
                    )}
                    <span>{renderBody(m.body, mine)}</span>
                    <span className={clsx('ml-2 align-bottom text-[10px]', mine ? 'text-indigo-200' : 'text-gray-400')}>
                      {timeOf(m.created_at)}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => { setReplyTo(m); taRef.current?.focus() }}
                  title="Reply"
                  className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-brand-600 transition shrink-0 mb-1"
                >
                  <Reply className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* Composer */}
      <div className="mt-3 relative">
        {/* Mention autocomplete */}
        {mention && candidates.length > 0 && (
          <div className="absolute bottom-full mb-1 left-0 w-64 bg-white border border-slate-200 rounded-lg shadow-lg overflow-hidden z-10">
            {candidates.map((c, idx) => (
              <button
                key={c.id}
                onMouseDown={(e) => { e.preventDefault(); insertMention(c.name) }}
                onMouseEnter={() => setMhi(idx)}
                className={clsx('w-full text-left px-3 py-1.5 text-sm flex items-center gap-2',
                  idx === mhi ? 'bg-brand-50 text-brand-700' : 'hover:bg-slate-50')}
              >
                {c.id === -1
                  ? <span className="w-6 h-6 rounded-full bg-amber-100 text-amber-700 grid place-items-center text-xs font-bold">@</span>
                  : <Avatar name={c.name} size={24} />}
                <span className="font-medium">@{c.name}</span>
                {c.id === -1 && <span className="text-xs text-gray-400 ml-auto">notify everyone</span>}
              </button>
            ))}
          </div>
        )}

        {replyTo && (
          <div className="flex items-center gap-2 bg-slate-100 border border-slate-200 rounded-t-lg px-3 py-1.5 text-xs">
            <Reply className="w-3.5 h-3.5 text-brand-500 shrink-0" />
            <span className="text-gray-500 truncate">
              Replying to <span className="font-semibold text-gray-700">{replyTo.name}</span>: {replyTo.body.slice(0, 60)}
            </span>
            <button onClick={() => setReplyTo(null)} className="ml-auto text-gray-400 hover:text-gray-700">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); send() }}>
          <textarea
            ref={taRef}
            rows={1}
            value={text}
            onChange={onChange}
            onKeyDown={onKeyDown}
            placeholder={connected ? 'Message your team…  (@ to mention)' : 'Reconnecting…'}
            disabled={!connected}
            className={clsx('input flex-1 resize-none max-h-32', replyTo && 'rounded-t-none')}
          />
          <button type="submit" disabled={!connected || !text.trim()} className="btn-primary h-10 px-4 shrink-0">
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  )
}
