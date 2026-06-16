import { Navigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, X, Shield, Clock } from 'lucide-react'
import { api } from '@/lib/api'
import { Avatar } from '@/components/charts'
import { useAuth } from '@/hooks/useAuth'
import { formatDateTime } from '@/lib/format'

interface Member {
  id: number
  email: string
  name: string
  approved: boolean
  is_admin: boolean
  created_at: string
}

export default function MembersPage() {
  const { data: me } = useAuth()
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['admin/members'],
    queryFn: () => api.get<{ members: Member[]; pending: number }>('/api/admin/members'),
    refetchInterval: 10_000,
  })

  const approve = useMutation({
    mutationFn: (uid: number) => api.post(`/api/admin/members/${uid}/approve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/members'] }),
  })
  const reject = useMutation({
    mutationFn: (uid: number) => api.post(`/api/admin/members/${uid}/reject`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/members'] }),
  })

  // Admin-only page.
  if (me && me.is_admin === false) return <Navigate to="/dashboard" replace />
  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>

  const pending = data.members.filter((m) => !m.approved)
  const approved = data.members.filter((m) => m.approved)

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Members</h1>
      <p className="text-sm text-gray-400 mb-6">
        Approve bidder sign-up requests. Only approved members can use the platform and the team chat.
      </p>

      {/* Pending requests */}
      <div className="card p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-4 h-4 text-amber-500" />
          <h2 className="text-base font-semibold text-gray-900">
            Pending requests {pending.length > 0 && (
              <span className="ml-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-amber-500 text-white text-xs font-bold">{pending.length}</span>
            )}
          </h2>
        </div>
        {pending.length === 0 ? (
          <p className="text-sm text-gray-400 py-2">No pending requests.</p>
        ) : (
          <ul className="divide-y divide-slate-100 -mx-5">
            {pending.map((m) => (
              <li key={m.id} className="px-5 py-3 flex items-center gap-3">
                <Avatar name={m.name} size={32} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{m.name}</p>
                  <p className="text-xs text-gray-400 truncate">{m.email} · requested {formatDateTime(m.created_at)}</p>
                </div>
                <button onClick={() => approve.mutate(m.id)} disabled={approve.isPending}
                        className="btn-primary text-xs py-1.5 px-3">
                  <Check className="w-3.5 h-3.5" /> Approve
                </button>
                <button onClick={() => { if (confirm(`Reject and delete ${m.email}?`)) reject.mutate(m.id) }}
                        disabled={reject.isPending}
                        className="btn-secondary text-xs py-1.5 px-3 text-red-600 border-red-200 hover:bg-red-50">
                  <X className="w-3.5 h-3.5" /> Reject
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Approved members */}
      <div className="card p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Members ({approved.length})</h2>
        <ul className="divide-y divide-slate-100 -mx-5">
          {approved.map((m) => (
            <li key={m.id} className="px-5 py-3 flex items-center gap-3">
              <Avatar name={m.name} size={32} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate flex items-center gap-1.5">
                  {m.name}
                  {m.is_admin && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-brand-700 bg-brand-50 border border-brand-200 rounded-full px-1.5 py-0.5">
                      <Shield className="w-2.5 h-2.5" /> admin
                    </span>
                  )}
                </p>
                <p className="text-xs text-gray-400 truncate">{m.email} · joined {formatDateTime(m.created_at)}</p>
              </div>
              {!m.is_admin && (
                <button onClick={() => { if (confirm(`Remove ${m.email}? This deletes their account.`)) reject.mutate(m.id) }}
                        disabled={reject.isPending}
                        className="text-gray-300 hover:text-red-600 transition" title="Remove member">
                  <X className="w-4 h-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
