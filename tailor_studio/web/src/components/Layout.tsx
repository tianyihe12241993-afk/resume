import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FolderKanban, Calendar as CalendarIcon, Search, LogOut,
  MessageSquare, ClipboardList, MessagesSquare, UserCheck, Pencil, Check, X,
} from 'lucide-react'
import clsx from 'clsx'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth, useLogout } from '@/hooks/useAuth'
import { useChatNotifications } from '@/hooks/useChatNotifications'
import { Avatar } from '@/components/charts'
import { useEffect } from 'react'

function BrandMark() {
  return (
    <span
      className="w-9 h-9 rounded-xl grid place-items-center text-white text-sm font-bold shadow-md"
      style={{ background: 'linear-gradient(135deg,#818cf8 0%,#6366f1 45%,#7c3aed 100%)' }}
    >S</span>
  )
}

export default function Layout() {
  const nav = useNavigate()
  const { data: user } = useAuth()
  const logout = useLogout()
  const [q, setQ] = useState('')

  const qc = useQueryClient()
  // Poll for open feedback notes (unconfirmed). Powers the sidebar feedback queue.
  type OpenNote = {
    job_id: number; batch_id: number; profile_id: number; profile_name: string
    company: string | null; title: string | null; note: string
    note_by: string | null; confirmed: boolean; confirmed_by: string | null
    kind: 'comment' | 'confirmed'; actor: string | null; updated_at: string | null
  }
  const { data: unread } = useQuery({
    enabled: !!user,
    queryKey: ['admin/notes/unread'],
    queryFn: () => api.get<{ count: number; samples: OpenNote[] }>('/api/admin/notes/unread'),
    refetchInterval: 15_000,
  })
  const unreadCount = unread?.count ?? 0
  const confirmNote = useMutation({
    mutationFn: (n: OpenNote) => api.post(`/api/admin/batches/${n.batch_id}/jobs/${n.job_id}/note/confirm`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/notes/unread'] }),
  })
  const dismissNote = useMutation({
    mutationFn: (n: OpenNote) => api.post(`/api/admin/batches/${n.batch_id}/jobs/${n.job_id}/note/seen`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/notes/unread'] }),
  })

  // Admin-only: pending member-approval requests, for the sidebar badge.
  const { data: members } = useQuery({
    enabled: !!user?.is_admin,
    queryKey: ['admin/members'],
    queryFn: () => api.get<{ pending: number }>('/api/admin/members'),
    refetchInterval: 15_000,
  })
  const pendingMembers = members?.pending ?? 0

  // App-wide team-chat notifications (badge + desktop notify + title counter).
  const { unread: chatUnread, online } = useChatNotifications(user ?? undefined)
  useEffect(() => {
    document.title = chatUnread > 0 ? `(${chatUnread}) Tailor Studio` : 'Tailor Studio'
  }, [chatUnread])

  // Username editing (every member can set their own).
  const [editName, setEditName] = useState(false)
  const [nameVal, setNameVal] = useState('')
  const saveName = useMutation({
    mutationFn: (name: string) => api.post('/api/me/name', { name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['me'] }); setEditName(false) },
  })
  const onSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (q.trim()) {
      nav('/search?q=' + encodeURIComponent(q.trim()))
      setQ('')
    }
  }
  return (
    <div className="min-h-screen flex bg-slate-50">
      {/* Sidebar */}
      <aside className="hidden md:flex md:flex-col w-60 bg-white border-r border-slate-200 shrink-0 sticky top-0 h-screen overflow-y-auto">
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-slate-200">
          <BrandMark />
          <span className="font-semibold tracking-tight text-gray-900">Tailor Studio</span>
        </div>

        <form onSubmit={onSearch} className="px-3 pt-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search company, title…"
              className="w-full pl-8 pr-2 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200"
            />
          </div>
        </form>

        <nav className="flex-1 px-3 py-3 space-y-0.5">
          <SideLink to="/dashboard" icon={LayoutDashboard} badge={unreadCount}>Dashboard</SideLink>
          <SideLink to="/profiles" icon={FolderKanban}>Profiles</SideLink>
          <SideLink to="/search" icon={Search}>Search</SideLink>
          <SideLink to="/chat" icon={MessagesSquare} badge={chatUnread}>Team chat</SideLink>
          <SideLink to="/calendar" icon={CalendarIcon}>Calendar</SideLink>
          <SideLink to="/answers" icon={ClipboardList}>Answers</SideLink>
          {user?.is_admin && (
            <SideLink to="/members" icon={UserCheck} badge={pendingMembers}>Members</SideLink>
          )}
        </nav>

        {user?.is_admin && (
          <div className="px-3 pb-3">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-gray-400 mb-1.5 px-1 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500" /> Online ({online.length})
            </div>
            {online.length === 0 ? (
              <p className="text-[11px] text-gray-400 px-1">No one online.</p>
            ) : (
              <ul className="space-y-0.5 max-h-48 overflow-y-auto">
                {online.map((n) => (
                  <li key={n} className="flex items-center gap-2 px-1 py-0.5 text-xs text-gray-600">
                    <span className="relative shrink-0">
                      <Avatar name={n} size={20} />
                      <span className="absolute -right-0.5 -bottom-0.5 w-2 h-2 rounded-full bg-green-500 ring-1 ring-white" />
                    </span>
                    <span className="truncate">{n}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {unreadCount > 0 && unread?.samples && (
          <div className="px-3 pb-3">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-rose-600 mb-1 flex items-center gap-1">
              <MessageSquare className="w-3 h-3" />
              {unreadCount} note{unreadCount === 1 ? '' : 's'} for you
            </div>
            <ul className="space-y-0.5 max-h-60 overflow-y-auto pr-0.5">
              {unread.samples.map((s) => (
                <li key={s.job_id} className="group flex items-start gap-1">
                  <Link
                    to={`/admin/batches/${s.batch_id}?job=${s.job_id}`}
                    className="flex-1 min-w-0 hover:bg-rose-50/60 rounded px-1.5 py-0.5"
                    title={`${s.note}${s.note_by ? ' — ' + s.note_by : ''}`}
                  >
                    <span className="block text-[11px] font-medium text-gray-700 truncate">{s.company || s.profile_name || '—'}</span>
                    <span className="block text-[10px] truncate">
                      {s.confirmed
                        ? <span className="text-green-600">✓ {s.actor || 'someone'} confirmed your note</span>
                        : <span className="text-gray-400">{s.note}{s.note_by ? ` · ${s.note_by}` : ''}</span>}
                    </span>
                  </Link>
                  <button
                    onClick={() => (s.confirmed ? dismissNote.mutate(s) : confirmNote.mutate(s))}
                    disabled={confirmNote.isPending || dismissNote.isPending}
                    className="text-gray-300 hover:text-green-600 shrink-0 mt-0.5"
                    title={s.confirmed ? 'Dismiss' : 'Confirm — mark handled'}
                  >
                    <Check className="w-3.5 h-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="border-t border-slate-200 p-3">
          {user && (
            <div className="px-2 py-1.5 mb-1 rounded-md">
              {editName ? (
                <form className="flex items-center gap-1"
                      onSubmit={(e) => { e.preventDefault(); const v = nameVal.trim(); if (v) saveName.mutate(v) }}>
                  <input autoFocus value={nameVal} maxLength={32}
                         onChange={(e) => setNameVal(e.target.value)}
                         onKeyDown={(e) => { if (e.key === 'Escape') setEditName(false) }}
                         placeholder="username"
                         className="input text-xs py-1 flex-1 min-w-0" />
                  <button className="text-green-600 hover:text-green-700 p-1" title="Save"><Check className="w-3.5 h-3.5" /></button>
                  <button type="button" onClick={() => setEditName(false)} className="text-gray-400 hover:text-gray-600 p-1"><X className="w-3.5 h-3.5" /></button>
                </form>
              ) : (
                <div className="flex items-center gap-2 group">
                  <Avatar name={user.name || user.email} size={28} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-800 truncate">{user.name || user.email.split('@')[0]}</p>
                    <p className="text-[10px] text-gray-400 truncate">{user.email}</p>
                  </div>
                  <button onClick={() => { setNameVal(user.name || ''); setEditName(true) }}
                          title="Edit username"
                          className="text-gray-300 hover:text-brand-600 transition opacity-0 group-hover:opacity-100">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              {saveName.isError && (
                <p className="text-[10px] text-red-600 mt-1">{(saveName.error as Error).message}</p>
              )}
            </div>
          )}
          <button
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-gray-500 hover:text-gray-900 hover:bg-slate-50 rounded-md transition disabled:opacity-50"
          >
            <LogOut className="w-3.5 h-3.5" /> Sign out
          </button>
        </div>
      </aside>

      {/* Mobile header */}
      <header className="md:hidden fixed top-0 inset-x-0 bg-white border-b border-slate-200 z-20 h-14 flex items-center px-4">
        <Link to="/" className="flex items-center gap-2">
          <BrandMark />
          <span className="font-semibold tracking-tight text-gray-900">Tailor Studio</span>
        </Link>
      </header>

      <main className="flex-1 min-w-0 pt-14 md:pt-0">
        <div className="w-full px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

function SideLink({
  to, icon: Icon, children, badge,
}: {
  to: string
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
  badge?: number
}) {
  return (
    <NavLink
      to={to}
      end={to === '/dashboard'}
      className={({ isActive }) =>
        clsx(
          'relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition',
          isActive
            ? 'bg-gradient-to-r from-indigo-50 to-violet-50 text-brand-700 shadow-sm'
            : 'text-gray-600 hover:bg-slate-50 hover:text-gray-900',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r bg-gradient-to-b from-indigo-400 to-violet-500" />
          )}
          <Icon className={clsx('w-4 h-4', isActive ? 'text-brand-600' : 'text-gray-400')} />
          <span className="flex-1">{children}</span>
          {!!badge && badge > 0 && (
            <span
              title={`${badge} unread note${badge === 1 ? '' : 's'}`}
              className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold tabular-nums shadow"
            >
              {badge > 99 ? '99+' : badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}
