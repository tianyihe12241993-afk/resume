import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { api, type User } from '@/lib/api'
import { Empty } from '@/components/ui'

type BidderRow = User & { profile_count: number }

export default function Bidders() {
  const { data, isLoading } = useQuery({
    queryKey: ['admin/bidders'],
    queryFn: () => api.get<{ bidders: BidderRow[] }>('/api/admin/bidders'),
  })
  if (isLoading || !data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const bidders = data.bidders
  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Bidders</h1>
        <span className="text-sm text-gray-400">{bidders.length} total</span>
      </div>

      {bidders.length > 0 ? (
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {bidders.map((b) => (
            <li key={b.id}>
              <Link to={`/admin/bidders/${b.id}`}
                    className="flex items-center justify-between px-5 py-4 hover:bg-slate-50 transition">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-semibold text-gray-900">{b.name || '(no name set)'}</p>
                    {!b.password_set && <span className="chip chip-needs_manual_jd">pending setup</span>}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">{b.email}</p>
                </div>
                <div className="flex items-center gap-3 text-sm text-gray-400 shrink-0">
                  <span>{b.profile_count} profile{b.profile_count === 1 ? '' : 's'}</span>
                  <ChevronRight className="w-4 h-4" />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No bidders yet. Add one by opening a profile and granting access.</Empty>
      )}
    </>
  )
}
