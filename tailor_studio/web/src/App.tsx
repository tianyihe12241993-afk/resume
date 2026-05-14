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
import { useAuth } from '@/hooks/useAuth'

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
