import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FolderKanban, Calendar as CalendarIcon, Search, LogOut,
  MessageSquare, ClipboardList,
} from 'lucide-react'
import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth, useLogout } from '@/hooks/useAuth'
import { Avatar } from '@/components/charts'

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

  // Poll for unread collaboration notes. Drives the badge on Dashboard.
  const { data: unread } = useQuery({
    enabled: !!user,
    queryKey: ['admin/notes/unread'],
    queryFn: () => api.get<{ count: number; samples: Array<{ job_id: number; batch_id: number; company: string|null; title: string|null; note: string }> }>('/api/admin/notes/unread'),
    refetchInterval: 15_000,
  })
  const unreadCount = unread?.count ?? 0
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
          <SideLink to="/calendar" icon={CalendarIcon}>Calendar</SideLink>
          <SideLink to="/answers" icon={ClipboardList}>Answers</SideLink>
        </nav>

        {unreadCount > 0 && unread?.samples && (
          <div className="px-3 pb-3">
            <div className="text-[10px] uppercase tracking-wider font-semibold text-rose-600 mb-1 flex items-center gap-1">
              <MessageSquare className="w-3 h-3" />
              {unreadCount} unread note{unreadCount === 1 ? '' : 's'}
            </div>
            <ul className="space-y-1">
              {unread.samples.slice(0, 3).map((s) => (
                <li key={s.job_id}>
                  <Link
                    to={`/admin/batches/${s.batch_id}`}
                    className="block text-[11px] text-gray-700 hover:text-brand-700 bg-rose-50/60 hover:bg-rose-50 border border-rose-200 rounded px-2 py-1 truncate"
                    title={s.note}
                  >
                    <span className="font-semibold">{s.company || '—'}</span>
                    <span className="text-gray-400"> · {s.title || ''}</span>
                  </Link>
                </li>
              ))}
              {unreadCount > 3 && (
                <li className="text-[10px] text-gray-400 italic pl-1">
                  …and {unreadCount - 3} more
                </li>
              )}
            </ul>
          </div>
        )}

        <div className="border-t border-slate-200 p-3">
          {user && (
            <div className="flex items-center gap-2 px-2 py-1.5 mb-1 rounded-md hover:bg-slate-50">
              <Avatar name={user.email} size={28} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-gray-800 truncate">{user.email}</p>
              </div>
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
