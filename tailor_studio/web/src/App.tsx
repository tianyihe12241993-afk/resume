import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Signup from '@/pages/Signup'
import Dashboard from '@/pages/admin/Dashboard'
import Profiles from '@/pages/admin/Profiles'
import ProfileDetail from '@/pages/admin/ProfileDetail'
import BatchDetail from '@/pages/admin/BatchDetail'
import Calendar from '@/pages/admin/Calendar'
import Search from '@/pages/admin/Search'
import Answers from '@/pages/admin/Answers'
import Chat from '@/pages/admin/Chat'
import Members from '@/pages/admin/Members'
import { useAuth, useLogout } from '@/hooks/useAuth'

function PendingApproval({ email }: { email: string }) {
  const logout = useLogout()
  return (
    <div className="min-h-screen grid place-items-center bg-slate-50 p-6">
      <div className="card p-8 max-w-md text-center">
        <div className="text-3xl mb-3">⏳</div>
        <h1 className="text-lg font-bold text-gray-900 mb-1">Waiting for approval</h1>
        <p className="text-sm text-gray-500">
          Your request to join (<span className="font-medium">{email}</span>) was sent to the
          admin. You'll get access as soon as they approve you.
        </p>
        <button onClick={() => logout.mutate()}
                className="btn-secondary text-sm mt-5">Sign out</button>
      </div>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading } = useAuth()
  const loc = useLocation()
  if (isLoading) {
    return <div className="min-h-screen grid place-items-center text-sm text-gray-400">Loading…</div>
  }
  if (!user) {
    const next = encodeURIComponent(loc.pathname + loc.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  if (user.approved === false) {
    return <PendingApproval email={user.email} />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/profiles" element={<Profiles />} />
        <Route path="/profiles/:id" element={<ProfileDetail />} />
        <Route path="/batches/:id" element={<BatchDetail />} />
        <Route path="/calendar" element={<Calendar />} />
        <Route path="/search" element={<Search />} />
        <Route path="/answers" element={<Answers />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/members" element={<Members />} />
        {/* Legacy admin paths still target /admin/* — register the same components there. */}
        <Route path="/admin" element={<Navigate to="/dashboard" replace />} />
        <Route path="/admin/profiles" element={<Profiles />} />
        <Route path="/admin/profiles/:id" element={<ProfileDetail />} />
        <Route path="/admin/batches/:id" element={<BatchDetail />} />
        <Route path="/admin/calendar" element={<Calendar />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
