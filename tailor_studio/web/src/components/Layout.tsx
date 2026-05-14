import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, FolderKanban, Calendar as CalendarIcon, Search, LogOut,
} from 'lucide-react'
import clsx from 'clsx'
import { useAuth, useLogout } from '@/hooks/useAuth'

function BrandMark() {
  return (
    <span
      className="w-8 h-8 rounded-lg grid place-items-center text-white text-sm font-bold shadow"
      style={{ background: 'linear-gradient(135deg,#6366f1,#4f46e5)' }}
    >S</span>
  )
}

export default function Layout() {
  const nav = useNavigate()
  const { data: user } = useAuth()
  const logout = useLogout()
  const [q, setQ] = useState('')
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
          <SideLink to="/dashboard" icon={LayoutDashboard}>Dashboard</SideLink>
          <SideLink to="/profiles" icon={FolderKanban}>Profiles</SideLink>
          <SideLink to="/search" icon={Search}>Search</SideLink>
          <SideLink to="/calendar" icon={CalendarIcon}>Calendar</SideLink>
        </nav>

        <div className="border-t border-slate-200 p-3">
          {user && (
            <div className="flex items-center gap-2 px-2 py-1.5 mb-1 rounded-md hover:bg-slate-50">
              <span className="w-7 h-7 rounded-full bg-brand-100 text-brand-700 text-xs font-semibold grid place-items-center shrink-0">
                {(user.email[0] || '?').toUpperCase()}
              </span>
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
  to, icon: Icon, children,
}: { to: string; icon: React.ComponentType<{ className?: string }>; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === '/dashboard'}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition',
          isActive
            ? 'bg-brand-50 text-brand-700'
            : 'text-gray-600 hover:bg-slate-50 hover:text-gray-900',
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon className={clsx('w-4 h-4', isActive ? 'text-brand-600' : 'text-gray-400')} />
          {children}
        </>
      )}
    </NavLink>
  )
}
