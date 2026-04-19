import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api, type MyProfile } from '@/lib/api'
import { Empty } from '@/components/ui'
import { formatDateTime } from '@/lib/format'

export default function MyProfilePage() {
  const { id } = useParams()
  const { data } = useQuery({
    queryKey: ['my/profile', id],
    queryFn: () => api.get<MyProfile>(`/api/my/profiles/${id}`),
  })
  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>

  return (
    <>
      <Link to="/my" className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition">
        <ChevronLeft className="w-4 h-4" /> My profiles
      </Link>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">{data.profile.name}</h1>

      {data.batches.length > 0 ? (
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {data.batches.map((b) => (
            <li key={b.id}>
              <Link to={`/my/batches/${b.id}`}
                    className="flex items-center justify-between px-5 py-4 hover:bg-slate-50 transition">
                <span className="font-semibold text-gray-900">{formatDateTime(b.created_at)}</span>
                <div className="flex items-center gap-3 text-sm text-gray-400">
                  <span>{b.done} / {b.total} ready</span>
                  <ChevronRight className="w-4 h-4" />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No batches yet.</Empty>
      )}
    </>
  )
}
