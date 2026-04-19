import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, Copy } from 'lucide-react'
import { api, type BidderDetail } from '@/lib/api'
import { formatDateTime } from '@/lib/format'

export default function BidderDetailPage() {
  const { id } = useParams()
  const uid = Number(id)
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['admin/bidder', uid],
    queryFn: () => api.get<BidderDetail>(`/api/admin/bidders/${uid}`),
  })
  const [name, setName] = useState('')
  const [copied, setCopied] = useState(false)

  const rename = useMutation({
    mutationFn: () => api.post(`/api/admin/bidders/${uid}/rename`, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/bidder', uid] }),
  })
  const reset = useMutation({
    mutationFn: () => api.post(`/api/admin/users/${uid}/reset-invite`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/bidder', uid] }),
  })

  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const { bidder, profiles, invite_url } = data

  return (
    <>
      <Link to="/admin/bidders" className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition">
        <ChevronLeft className="w-4 h-4" /> Bidders
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{bidder.name || '(no name set)'}</h1>
          <p className="text-sm text-gray-400 mt-0.5">{bidder.email}</p>
          <p className="text-xs text-gray-400 mt-1">
            Added {formatDateTime(bidder.created_at)} ·{' '}
            {bidder.password_set
              ? <span className="text-green-600 font-medium">password set</span>
              : <span className="text-amber-600 font-medium">pending setup</span>}
          </p>
        </div>
        <button onClick={() => reset.mutate()} disabled={reset.isPending} className="btn-secondary text-sm">
          {reset.isPending ? 'Resetting…' : 'Reset invite'}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        <div className="card p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-3">Name</h2>
          <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); rename.mutate() }}>
            <input className="input flex-1" placeholder="Full name" defaultValue={bidder.name || ''}
                   onChange={(e) => setName(e.target.value)} />
            <button className="btn-primary text-sm shrink-0">Save</button>
          </form>
        </div>

        <div className="card p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-3">Setup link</h2>
          {invite_url ? (
            <>
              <p className="text-xs text-amber-700 mb-2 font-medium">Share this link with the bidder:</p>
              <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
                <input readOnly value={invite_url} className="flex-1 bg-transparent text-xs text-amber-900 font-mono min-w-0" />
                <button
                  onClick={() => { navigator.clipboard.writeText(invite_url); setCopied(true); setTimeout(() => setCopied(false), 1200) }}
                  className="text-[11px] bg-amber-600 text-white rounded px-2 py-0.5 shrink-0 hover:bg-amber-700 transition flex items-center gap-1"
                >
                  <Copy className="w-3 h-3" /> {copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-400">Bidder has a password set. Use "Reset invite" to regenerate.</p>
          )}
        </div>
      </div>

      <div className="card p-5">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Assigned profiles</h2>
        {profiles.length > 0 ? (
          <ul className="divide-y divide-slate-100">
            {profiles.map((p) => (
              <li key={p.id} className="py-3 flex items-center justify-between">
                <Link to={`/admin/profiles/${p.id}`} className="font-medium text-sm hover:underline text-gray-800">
                  {p.name}
                </Link>
                <span className="text-xs text-gray-400">{p.batch_count} batches</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-400">
            No profile access yet. Open a <Link to="/admin/profiles" className="text-brand-600 hover:underline">profile</Link> and grant them access.
          </p>
        )}
      </div>
    </>
  )
}
