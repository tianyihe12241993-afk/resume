import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Setup from '@/pages/Setup'
import ChangePassword from '@/pages/ChangePassword'
import AdminDashboard from '@/pages/admin/Dashboard'
import AdminProfiles from '@/pages/admin/Profiles'
import AdminProfileDetail from '@/pages/admin/ProfileDetail'
import AdminBidders from '@/pages/admin/Bidders'
import AdminBidderDetail from '@/pages/admin/BidderDetail'
import AdminBatchDetail from '@/pages/admin/BatchDetail'
import AdminCalendar from '@/pages/admin/Calendar'
import MyHome from '@/pages/bidder/Home'
import MyProfile from '@/pages/bidder/Profile'
import MyBatch from '@/pages/bidder/Batch'

function Root() {
  const { data: user, isLoading } = useAuth()
  if (isLoading) return <div className="p-8 text-center text-gray-400 text-sm">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  return <Navigate to={user.role === 'admin' ? '/admin' : '/my'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/setup" element={<Setup />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Root />} />
        <Route path="/change-password" element={<ChangePassword />} />

        <Route path="/admin" element={<AdminDashboard />} />
        <Route path="/admin/profiles" element={<AdminProfiles />} />
        <Route path="/admin/profiles/:id" element={<AdminProfileDetail />} />
        <Route path="/admin/bidders" element={<AdminBidders />} />
        <Route path="/admin/bidders/:id" element={<AdminBidderDetail />} />
        <Route path="/admin/batches/:id" element={<AdminBatchDetail />} />
        <Route path="/admin/calendar" element={<AdminCalendar />} />

        <Route path="/my" element={<MyHome />} />
        <Route path="/my/profiles/:id" element={<MyProfile />} />
        <Route path="/my/batches/:id" element={<MyBatch />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
