import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth, useLogout } from '@/hooks/useAuth'
import {
  LogOut, LayoutDashboard, Users, FolderKanban,
  Calendar as CalendarIcon, FileText, KeyRound,
} from 'lucide-react'
import clsx from 'clsx'

function BrandMark() {
  return (
    <span
      className="w-8 h-8 rounded-lg grid place-items-center text-white text-sm font-bold shadow"
      style={{ background: 'linear-gradient(135deg,#6366f1,#4f46e5)' }}
    >R</span>
  )
}

export default function Layout() {
  const { data: user, isLoading } = useAuth()
  const logout = useLogout()
  const loc = useLocation()

  if (isLoading) return <div className="p-8 text-center text-gray-400 text-sm">Loading…</div>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />

  const isAdmin = user.role === 'admin'

  return (
    <div className="min-h-screen flex bg-slate-50">
      {/* Sidebar */}
      <aside className="hidden md:flex md:flex-col w-60 bg-white border-r border-slate-200 shrink-0 sticky top-0 h-screen overflow-y-auto">
        <div className="h-16 flex items-center gap-2.5 px-5 border-b border-slate-200">
          <BrandMark />
          <span className="font-semibold tracking-tight text-gray-900">Resume Builder</span>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {isAdmin ? (
            <>
              <SideLink to="/admin" icon={LayoutDashboard}>Dashboard</SideLink>
              <SideLink to="/admin/profiles" icon={FolderKanban}>Profiles</SideLink>
              <SideLink to="/admin/bidders" icon={Users}>Bidders</SideLink>
              <SideLink to="/admin/calendar" icon={CalendarIcon}>Calendar</SideLink>
            </>
          ) : (
            <SideLink to="/my" icon={FileText}>My resumes</SideLink>
          )}
        </nav>

        <div className="border-t border-slate-200 p-3">
          <Link to="/change-password"
                className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 transition group">
            <span className={clsx(
              'w-8 h-8 rounded-full grid place-items-center text-xs font-semibold',
              isAdmin ? 'bg-brand-600 text-white' : 'bg-brand-100 text-brand-700',
            )}>
              {(user.name || user.email)[0]?.toUpperCase()}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">
                {user.name || user.email.split('@')[0]}
              </p>
              <p className="text-[11px] text-gray-400 capitalize">{user.role}</p>
            </div>
            <KeyRound className="w-3.5 h-3.5 text-gray-300 group-hover:text-gray-600 transition" />
          </Link>
          <button
            onClick={() => logout.mutate()}
            className="w-full flex items-center gap-2 px-3 py-2 mt-1 text-sm text-gray-500 hover:text-gray-900 hover:bg-slate-50 rounded-lg transition"
          >
            <LogOut className="w-4 h-4" /> Sign out
          </button>
        </div>
      </aside>

      {/* Mobile header */}
      <header className="md:hidden fixed top-0 inset-x-0 bg-white border-b border-slate-200 z-20 h-14 flex items-center justify-between px-4">
        <Link to="/" className="flex items-center gap-2">
          <BrandMark />
          <span className="font-semibold tracking-tight text-gray-900">Resume Builder</span>
        </Link>
        <button onClick={() => logout.mutate()} className="text-gray-400 hover:text-gray-700">
          <LogOut className="w-4 h-4" />
        </button>
      </header>

      {/* Main */}
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
      end={to === '/admin' || to === '/my'}
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
