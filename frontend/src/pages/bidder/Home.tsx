import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { api, type Profile } from '@/lib/api'
import { Empty } from '@/components/ui'

export default function MyHome() {
  const { data, isLoading } = useQuery({
    queryKey: ['my/profiles'],
    queryFn: () => api.get<{ profiles: Profile[] }>('/api/my/profiles'),
  })
  if (isLoading || !data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const profiles = data.profiles
  return (
    <>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">My profiles</h1>
      {profiles.length > 0 ? (
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {profiles.map((p) => (
            <li key={p.id}>
              <Link to={`/my/profiles/${p.id}`}
                    className="flex items-center justify-between px-5 py-4 hover:bg-slate-50 transition">
                <span className="font-semibold text-gray-900">{p.name}</span>
                <div className="flex items-center gap-3 text-sm text-gray-400">
                  <span>{p.batch_count} batches</span>
                  <ChevronRight className="w-4 h-4" />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>You don't have access to any profiles yet. Ask the admin to grant access.</Empty>
      )}
    </>
  )
}
