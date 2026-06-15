import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import type { User } from '@/lib/api'

// App-wide chat notifier. Keeps a lightweight WebSocket open on every page (so
// you're notified of team-chat messages even when not viewing the chat), tracks
// an unread count for the sidebar badge, fires desktop notifications, and pings
// on @mentions. The Chat page has its own connection for the live UI; this one
// only drives notifications.

const MENTION = /@(all|everyone|[A-Za-z0-9._-]+)/g

let _audio: AudioContext | null = null
function ping() {
  try {
    const Ctx = window.AudioContext || (window as any).webkitAudioContext
    _audio = _audio || new Ctx()
    const o = _audio.createOscillator()
    const g = _audio.createGain()
    o.connect(g); g.connect(_audio.destination)
    o.type = 'sine'; o.frequency.value = 660
    g.gain.setValueAtTime(0.0001, _audio.currentTime)
    g.gain.exponentialRampToValueAtTime(0.16, _audio.currentTime + 0.01)
    g.gain.exponentialRampToValueAtTime(0.0001, _audio.currentTime + 0.25)
    o.start(); o.stop(_audio.currentTime + 0.26)
  } catch { /* ignore */ }
}

function notify(m: any, pinged: boolean) {
  try {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
      const n = new Notification(
        pinged ? `📣 ${m.name} mentioned you` : `${m.name}`,
        { body: String(m.body || '').slice(0, 140), tag: 'tailor-chat' } as NotificationOptions,
      )
      n.onclick = () => { try { window.focus() } catch { /* */ }; n.close() }
    }
  } catch { /* ignore */ }
  if (pinged) ping()
}

export function useChatNotifications(user: User | undefined): number {
  const [unread, setUnread] = useState(0)
  const loc = useLocation()
  const onChat = loc.pathname === '/chat' || loc.pathname.endsWith('/chat')

  const onChatRef = useRef(onChat)
  onChatRef.current = onChat
  const meRef = useRef({ id: user?.id, name: (user?.email || '').split('@')[0].toLowerCase() })
  meRef.current = { id: user?.id, name: (user?.email || '').split('@')[0].toLowerCase() }

  // Clear the badge whenever you open the chat.
  useEffect(() => { if (onChat) setUnread(0) }, [onChat])

  useEffect(() => {
    if (!user) return
    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let closed = false
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/ws/chat`)
      ws.onmessage = (ev) => {
        let m: any
        try { m = JSON.parse(ev.data) } catch { return }
        if (m.type !== 'message') return
        const me = meRef.current
        if (m.user_id != null && m.user_id === me.id) return        // ignore own
        if (onChatRef.current && !document.hidden) return            // already reading
        const toks = (String(m.body || '').match(MENTION) || []).map((t: string) => t.slice(1).toLowerCase())
        const pinged = toks.includes('all') || toks.includes('everyone') || (!!me.name && toks.includes(me.name))
        setUnread((u) => u + 1)
        notify(m, pinged)
      }
      ws.onclose = () => { if (!closed) timer = setTimeout(connect, 3000) }
      ws.onerror = () => ws && ws.close()
    }
    connect()
    return () => { closed = true; if (timer) clearTimeout(timer); ws?.close() }
  }, [user?.id])

  return unread
}
