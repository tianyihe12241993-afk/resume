import { useEffect, useRef, useState, useCallback } from 'react'
import { Send, Reply, X, Bell, Smile, Pin, Pencil, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { api } from '@/lib/api'
import { Avatar } from '@/components/charts'

interface QuotedMsg { id: number; name: string; body: string }
interface PinnedMsg { id: number; name: string; body: string; created_at: string | null }
interface ChatMsg {
  id: number
  user_id: number | null
  name: string
  body: string
  reply_to?: QuotedMsg | null
  pinned?: boolean
  edited_at?: string | null
  created_at: string | null
}
interface HistoryResp {
  me: { id: number; name: string; is_admin?: boolean }
  gif_enabled?: boolean
  messages: ChatMsg[]
  pinned?: PinnedMsg[]
}
interface Member { id: number; name: string }
interface Gif { id: string; preview: string; url: string }

const MENTION_RE = /@(all|everyone|[A-Za-z0-9._-]+)/g
// A message that is exactly an image/GIF URL renders as an image.
const IMG_URL_RE = /^https?:\/\/\S+\.(?:gif|png|jpe?g|webp)(?:\?\S*)?$/i

const EMOJI_GROUPS: Record<string, string> = {
  Smileys: '😀 😃 😄 😁 😆 😅 😂 🤣 🙂 🙃 😉 😊 😇 🥰 😍 😘 😗 😙 😚 😋 😛 😝 😜 🤪 🤨 🧐 🤓 😎 🥳 🤩 😏 😒 😞 😔 😟 😕 🙁 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤬 🤯 😳 🥵 🥶 😱 😨 😰 😥 😓 🤔 🫡 🤗 🤭 🤫 😬 🙄 😴 🤤 😪 😵 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕',
  Gestures: '👍 👎 👌 🤌 🤏 ✌️ 🤞 🫰 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👋 🤚 🖐️ ✋ 🖖 🫶 🙏 👏 🙌 🤝 💪 🫵 ✊ 👊 🤛 🤜',
  Hearts: '❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 🔥 ✨ ⭐ 🌟 💫 💯 ✅ ❌ ❓ ❗ 👀 🎉 🎊 🥂 🏆 🚀',
  Animals: '🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🐦 🦄 🐝 🦋 🐢 🐙 🦀 🐬 🐳 🐺 🦉',
  Food: '🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍒 🍑 🥭 🍍 🥥 🥝 🍅 🥑 🌽 🌶️ 🍔 🍟 🍕 🌭 🥪 🌮 🍜 🍣 🍩 🍪 🎂 🍰 🍫 🍿 ☕ 🍺 🍻 🥤',
  Objects: '💻 🖥️ 📱 ⌨️ 🖱️ 💾 📷 🎧 🎮 📺 ☎️ 📞 ⏰ 💡 🔑 🔒 📌 📎 ✂️ 📝 📚 💰 💵 💳 🎁 📦 ✉️ 📅 ⌛ ⚙️ 🔧 🔨 🧲',
  Symbols: '✔️ ❎ ➕ ➖ ➗ ❤️‍🔥 💢 💥 💦 💨 🕐 🔝 🆗 🆕 🆒 🔥 ⚡ 🌈 ☀️ ⛅ ☁️ 🌧️ ❄️ 🎵 🎶 ♻️ ⚠️ 🚫 ✅ ❌ ❓ ❗ ‼️ 💤',
}

function timeOf(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch { return '' }
}
function typingText(t: { name: string }[]): string {
  if (t.length === 1) return `${t[0].name} is typing`
  if (t.length === 2) return `${t[0].name} and ${t[1].name} are typing`
  return 'Several people are typing'
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
  const [meAdmin, setMeAdmin] = useState(false)
  const [pinned, setPinned] = useState<PinnedMsg[]>([])
  const [editing, setEditing] = useState<{ id: number } | null>(null)
  // Admin multi-select / bulk delete
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  // Typing indicator
  const [typing, setTyping] = useState<{ id: number; name: string }[]>([])
  const typingTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())
  const lastTypingSent = useRef(0)
  const meIdRef = useRef<number | null>(null)
  meIdRef.current = meId
  const [online, setOnline] = useState(0)
  const [onlineNames, setOnlineNames] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [text, setText] = useState('')
  const [replyTo, setReplyTo] = useState<ChatMsg | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [notifPerm, setNotifPerm] = useState<NotificationPermission | 'unsupported'>(
    typeof Notification === 'undefined' ? 'unsupported' : Notification.permission,
  )
  const enableNotifs = async () => {
    if (typeof Notification === 'undefined') return
    try { setNotifPerm(await Notification.requestPermission()) } catch { /* */ }
  }

  // Mention autocomplete state
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null)
  const [mhi, setMhi] = useState(0)   // highlighted candidate index

  // Emoji + GIF pickers
  const [emojiOpen, setEmojiOpen] = useState(false)
  const [gifEnabled, setGifEnabled] = useState(false)
  const [gifOpen, setGifOpen] = useState(false)
  const [gifQuery, setGifQuery] = useState('')
  const [gifResults, setGifResults] = useState<Gif[]>([])
  const [gifLoading, setGifLoading] = useState(false)

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
      setMeId(d.me.id); setMeName(d.me.name); setMeAdmin(!!d.me.is_admin)
      setMessages(d.messages); setPinned(d.pinned ?? [])
      setGifEnabled(!!d.gif_enabled)
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
        else if (m.type === 'edit') {
          setMessages((prev) => prev.map((x) => x.id === m.id ? { ...x, body: m.body, edited_at: m.edited_at } : x))
          setPinned((prev) => prev.map((p) => p.id === m.id ? { ...p, body: m.body } : p))
        }
        else if (m.type === 'delete') {
          setMessages((prev) => prev.filter((x) => x.id !== m.id))
          setPinned((prev) => prev.filter((p) => p.id !== m.id))
        }
        else if (m.type === 'delete_many') {
          const ids = new Set<number>(m.ids ?? [])
          setMessages((prev) => prev.filter((x) => !ids.has(x.id)))
          setPinned((prev) => prev.filter((p) => !ids.has(p.id)))
        }
        else if (m.type === 'clear') {
          setMessages([]); setPinned([])
        }
        else if (m.type === 'typing') {
          if (m.user_id === meIdRef.current) return     // ignore my own typing
          const id = m.user_id, name = m.name
          setTyping((prev) => prev.some((t) => t.id === id) ? prev : [...prev, { id, name }])
          const timers = typingTimers.current
          if (timers.has(id)) clearTimeout(timers.get(id)!)
          timers.set(id, setTimeout(() => {
            setTyping((prev) => prev.filter((t) => t.id !== id))
            timers.delete(id)
          }, 3500))
        }
        else if (m.type === 'pin') {
          setMessages((prev) => prev.map((x) => x.id === m.id ? { ...x, pinned: m.pinned } : x))
          setPinned((prev) => {
            const without = prev.filter((p) => p.id !== m.id)
            return m.pinned && m.msg ? [m.msg, ...without] : without
          })
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
  useEffect(() => () => { typingTimers.current.forEach(clearTimeout); typingTimers.current.clear() }, [])

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
    // Throttle "typing" pings to ~once every 1.8s while there's text.
    const now = Date.now()
    if (v.trim() && !editing && now - lastTypingSent.current > 1800) {
      lastTypingSent.current = now
      wsSend({ action: 'typing' })
    }
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

  const wsSend = (obj: any) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
  }
  const sendBody = (raw: string) => {
    const body = raw.trim()
    if (!body) return
    wsSend({ body, reply_to_id: replyTo?.id ?? null })
    setReplyTo(null)
  }
  const send = () => {
    if (editing) {
      const body = text.trim()
      if (body) wsSend({ action: 'edit', id: editing.id, body })
      setEditing(null); setText(''); setMention(null)
      return
    }
    sendBody(text); setText(''); setMention(null)
  }

  const startEdit = (m: ChatMsg) => {
    setEditing({ id: m.id }); setReplyTo(null); setText(m.body)
    requestAnimationFrame(() => taRef.current?.focus())
  }
  const cancelEdit = () => { setEditing(null); setText('') }
  const remove = (m: ChatMsg) => { if (confirm('Delete this message?')) wsSend({ action: 'delete', id: m.id }) }
  const togglePin = (m: ChatMsg) => wsSend({ action: 'pin', id: m.id, pinned: !m.pinned })

  // Admin selection / bulk delete
  const enterSelect = () => { setSelecting(true); setSelected(new Set()); setEditing(null); setReplyTo(null) }
  const exitSelect = () => { setSelecting(false); setSelected(new Set()) }
  const toggleSelect = (id: number) =>
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allSelected = messages.length > 0 && selected.size === messages.length
  const toggleSelectAll = () =>
    setSelected(allSelected ? new Set() : new Set(messages.map((m) => m.id)))
  const deleteSelected = () => {
    if (!selected.size) return
    if (confirm(`Delete ${selected.size} selected message${selected.size === 1 ? '' : 's'}?`)) {
      wsSend({ action: 'delete_many', ids: [...selected] }); exitSelect()
    }
  }
  const clearAll = () => {
    if (confirm('Delete ALL messages in this chat? This cannot be undone.')) {
      wsSend({ action: 'clear' }); exitSelect()
    }
  }
  const scrollToMsg = (id: number) => {
    const el = document.getElementById(`msg-${id}`)
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.classList.add('ring-2', 'ring-brand-400')
      setTimeout(() => el.classList.remove('ring-2', 'ring-brand-400'), 1500) }
  }

  const insertAtCursor = (s: string) => {
    const ta = taRef.current
    const pos = ta?.selectionStart ?? text.length
    const next = text.slice(0, pos) + s + text.slice(pos)
    setText(next)
    requestAnimationFrame(() => {
      if (ta) { ta.focus(); ta.setSelectionRange(pos + s.length, pos + s.length) }
    })
  }

  // GIF search (debounced) — only when the picker is open.
  useEffect(() => {
    if (!gifOpen) return
    setGifLoading(true)
    const t = setTimeout(() => {
      api.get<{ gifs: Gif[] }>(`/api/chat/gif?q=${encodeURIComponent(gifQuery)}`)
        .then((d) => setGifResults(d.gifs))
        .catch(() => setGifResults([]))
        .finally(() => setGifLoading(false))
    }, 350)
    return () => clearTimeout(t)
  }, [gifOpen, gifQuery])

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

  // Render body with @mentions highlighted as a small readable chip.
  const renderBody = (body: string) => {
    const parts: React.ReactNode[] = []
    let last = 0
    body.replace(MENTION_RE, (match, _g, idx: number) => {
      if (idx > last) parts.push(body.slice(last, idx))
      parts.push(
        <span key={idx} className="bg-brand-100 text-brand-700 font-semibold rounded px-1">{match}</span>,
      )
      last = idx + match.length
      return match
    })
    if (last < body.length) parts.push(body.slice(last))
    return parts
  }

  return (
    <div className="max-w-5xl mx-auto flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Team chat</h1>
          <p className="text-sm text-gray-400">Shared group chat for you and your bidders.</p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {notifPerm === 'default' && (
            <button onClick={enableNotifs}
                    className="inline-flex items-center gap-1 text-xs text-brand-600 hover:text-brand-800 border border-brand-200 rounded-full px-2.5 py-1">
              <Bell className="w-3.5 h-3.5" /> Enable notifications
            </button>
          )}
          {notifPerm === 'granted' && <Bell className="w-4 h-4 text-green-500" aria-label="Notifications on" />}
          {notifPerm === 'denied' && (
            <span className="text-xs text-gray-400" title="Allow notifications for this site in your browser settings">
              notifications blocked
            </span>
          )}
          {meAdmin && !selecting && (
            <button onClick={enterSelect}
                    className="text-xs text-gray-500 hover:text-brand-600 border border-slate-200 rounded-full px-2.5 py-1">
              Select
            </button>
          )}
          <span className={clsx('w-2 h-2 rounded-full', connected ? 'bg-green-500' : 'bg-gray-300')} />
          <span className="text-gray-500" title={onlineNames.join(', ')}>
            {connected ? `${online} online` : 'connecting…'}
          </span>
        </div>
      </div>

      {selecting && (
        <div className="flex items-center gap-3 mb-2 bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm shadow-sm">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                   className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
            Select all
          </label>
          <span className="text-gray-500">{selected.size} selected</span>
          <button onClick={deleteSelected} disabled={!selected.size}
                  className="btn-danger text-xs py-1.5 px-3">Delete selected</button>
          <button onClick={clearAll} className="text-xs text-red-600 hover:text-red-800 font-medium">Delete all</button>
          <button onClick={exitSelect} className="ml-auto text-xs text-gray-500 hover:text-gray-800">Cancel</button>
        </div>
      )}

      <div className="flex-1 flex gap-4 min-h-0">
        <div className="flex-1 flex flex-col min-w-0">
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
              <div id={`msg-${m.id}`}
                   onClick={() => selecting && toggleSelect(m.id)}
                   className={clsx('group flex items-end gap-2 rounded-lg transition px-1 -mx-1',
                     mine ? 'flex-row-reverse' : 'flex-row',
                     selecting && 'cursor-pointer',
                     selecting && selected.has(m.id) && 'bg-brand-100/60 ring-1 ring-brand-300')}>
                {selecting && (
                  <input type="checkbox" checked={selected.has(m.id)}
                         onChange={() => toggleSelect(m.id)} onClick={(e) => e.stopPropagation()}
                         className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500 shrink-0 self-center" />
                )}
                <div className="w-7 shrink-0">{!mine && !grouped && <Avatar name={m.name} size={28} />}</div>
                <div className="max-w-[78%]">
                  {!grouped && (
                    <div className={clsx('text-[11px] mb-0.5', mine ? 'text-right text-gray-400' : 'text-gray-500 font-medium')}>
                      {mine ? '' : m.name}
                    </div>
                  )}
                  <div className={clsx(
                    'rounded-2xl px-3 py-1.5 text-sm whitespace-pre-wrap break-words shadow-sm text-gray-800 border',
                    mine ? 'bg-brand-50 border-brand-200 rounded-br-sm'
                         : pinged ? 'bg-amber-50 border-amber-300 rounded-bl-sm'
                                  : 'bg-white border-slate-200 rounded-bl-sm',
                  )}>
                    {m.reply_to && (
                      <div className="mb-1 pl-2 border-l-2 text-xs rounded-sm py-0.5 border-brand-300 text-gray-500">
                        <span className="font-semibold">{m.reply_to.name}</span>
                        <span className="opacity-80"> · {m.reply_to.body.slice(0, 80)}</span>
                      </div>
                    )}
                    {IMG_URL_RE.test(m.body.trim()) ? (
                      <a href={m.body.trim()} target="_blank" rel="noreferrer" className="block">
                        <img src={m.body.trim()} alt="gif" loading="lazy"
                             className="rounded-lg max-w-[240px] max-h-[260px] block" />
                      </a>
                    ) : (
                      <span>{renderBody(m.body)}</span>
                    )}
                    <span className="ml-2 align-bottom text-[10px] text-gray-400">
                      {m.edited_at && <span className="mr-1">(edited)</span>}{timeOf(m.created_at)}
                    </span>
                  </div>
                </div>
                {!selecting && (
                <div className="opacity-0 group-hover:opacity-100 transition flex items-center gap-0.5 shrink-0 mb-1 text-gray-300">
                  <button onClick={() => { setEditing(null); setReplyTo(m); taRef.current?.focus() }}
                          title="Reply" className="hover:text-brand-600 p-0.5"><Reply className="w-3.5 h-3.5" /></button>
                  {meAdmin && (
                    <button onClick={() => togglePin(m)} title={m.pinned ? 'Unpin' : 'Pin'}
                            className={clsx('p-0.5 hover:text-amber-600', m.pinned && 'text-amber-500')}>
                      <Pin className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {mine && !IMG_URL_RE.test(m.body.trim()) && (
                    <button onClick={() => startEdit(m)} title="Edit" className="hover:text-brand-600 p-0.5">
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {(mine || meAdmin) && (
                    <button onClick={() => remove(m)} title="Delete" className="hover:text-red-600 p-0.5">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Typing indicator */}
      <div className="h-5 px-2 mt-1 flex items-center gap-1.5 text-xs text-gray-400">
        {typing.length > 0 && (
          <>
            <span className="flex gap-0.5 items-end">
              <span className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '300ms' }} />
            </span>
            <span>{typingText(typing)}</span>
          </>
        )}
      </div>

      {/* Composer */}
      <div className="relative">
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

        {/* Emoji picker */}
        {emojiOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setEmojiOpen(false)} />
            <div className="absolute bottom-full mb-2 left-0 w-72 max-h-72 overflow-y-auto bg-white border border-slate-200 rounded-lg shadow-lg z-20 p-2">
              {Object.entries(EMOJI_GROUPS).map(([cat, str]) => (
                <div key={cat} className="mb-2">
                  <div className="text-[10px] uppercase tracking-wide text-gray-400 px-1 mb-1">{cat}</div>
                  <div className="grid grid-cols-8 gap-0.5">
                    {str.split(' ').filter(Boolean).map((e, i) => (
                      <button key={cat + i} type="button" onClick={() => insertAtCursor(e)}
                              className="text-xl leading-none p-1 rounded hover:bg-slate-100">{e}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* GIF picker */}
        {gifOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setGifOpen(false)} />
            <div className="absolute bottom-full mb-2 left-0 w-80 bg-white border border-slate-200 rounded-lg shadow-lg z-20 p-2">
              <input autoFocus value={gifQuery} onChange={(e) => setGifQuery(e.target.value)}
                     placeholder="Search GIFs…" className="input text-sm w-full mb-2" />
              <div className="h-64 overflow-y-auto">
                {gifLoading && <p className="text-xs text-gray-400 text-center py-4">Searching…</p>}
                <div className="columns-2 gap-1">
                  {gifResults.map((g) => (
                    <button key={g.id} type="button" onClick={() => { sendBody(g.url); setGifOpen(false) }}
                            className="mb-1 w-full block hover:opacity-80 transition">
                      <img src={g.preview} alt="gif" loading="lazy" className="rounded w-full" />
                    </button>
                  ))}
                </div>
                {!gifLoading && gifResults.length === 0 && (
                  <p className="text-xs text-gray-400 text-center py-4">No GIFs found.</p>
                )}
              </div>
              <p className="text-[10px] text-gray-300 text-right mt-1">Powered by GIPHY</p>
            </div>
          </>
        )}

        {editing && (
          <div className="flex items-center gap-2 bg-brand-50 border border-brand-200 rounded-t-lg px-3 py-1.5 text-xs">
            <Pencil className="w-3.5 h-3.5 text-brand-500 shrink-0" />
            <span className="text-brand-700">Editing message — press Enter to save</span>
            <button onClick={cancelEdit} className="ml-auto text-gray-400 hover:text-gray-700">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {replyTo && !editing && (
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
          <div className="flex items-center gap-1 pb-0.5">
            <button type="button" title="Emoji"
                    onClick={() => { setEmojiOpen((o) => !o); setGifOpen(false) }}
                    className="h-9 w-9 grid place-items-center text-gray-400 hover:text-brand-600 hover:bg-slate-100 rounded-lg">
              <Smile className="w-5 h-5" />
            </button>
            {gifEnabled && (
              <button type="button" title="GIF"
                      onClick={() => { setGifOpen((o) => !o); setEmojiOpen(false); setGifQuery('') }}
                      className="h-9 px-2 grid place-items-center text-xs font-bold text-gray-400 hover:text-brand-600 hover:bg-slate-100 border border-slate-200 rounded-lg">
                GIF
              </button>
            )}
          </div>
          <textarea
            ref={taRef}
            rows={1}
            value={text}
            onChange={onChange}
            onKeyDown={onKeyDown}
            placeholder={connected ? 'Message your team…  (@ to mention)' : 'Reconnecting…'}
            disabled={!connected}
            className={clsx('input flex-1 resize-none max-h-32', (replyTo || editing) && 'rounded-t-none')}
          />
          <button type="submit" disabled={!connected || !text.trim()} className="btn-primary h-10 px-4 shrink-0">
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>
        </div>

        {/* Pinned panel (right) */}
        {pinned.length > 0 && (
          <aside className="w-64 shrink-0 hidden lg:flex flex-col card p-3 bg-amber-50/40 border-amber-200">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 uppercase tracking-wide mb-2">
              <Pin className="w-3.5 h-3.5" /> Pinned ({pinned.length})
            </div>
            <div className="flex-1 overflow-y-auto space-y-1.5">
              {pinned.map((p) => (
                <div key={p.id}
                     className="group/pin bg-white border border-amber-200 rounded-lg px-2.5 py-1.5 text-xs cursor-pointer hover:border-amber-300"
                     onClick={() => scrollToMsg(p.id)}>
                  <div className="flex items-center gap-1">
                    <span className="font-semibold text-gray-700 truncate">{p.name}</span>
                    {meAdmin && (
                      <button onClick={(e) => { e.stopPropagation(); wsSend({ action: 'pin', id: p.id, pinned: false }) }}
                              title="Unpin"
                              className="ml-auto opacity-0 group-hover/pin:opacity-100 text-amber-500 hover:text-amber-700 shrink-0">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="text-gray-500 line-clamp-2 mt-0.5">
                    {IMG_URL_RE.test(p.body.trim()) ? '🖼️ GIF' : p.body}
                  </div>
                </div>
              ))}
            </div>
          </aside>
        )}
      </div>
    </div>
  )
}
