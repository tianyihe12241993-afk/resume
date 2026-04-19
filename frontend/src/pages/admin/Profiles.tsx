import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { api, type Profile } from '@/lib/api'
import { Empty } from '@/components/ui'

export default function Profiles() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['admin/profiles'],
    queryFn: () => api.get<{ profiles: Profile[] }>('/api/admin/profiles'),
  })
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: () => api.post<{ profile: Profile }>('/api/admin/profiles', { name }),
    onSuccess: () => { setName(''); qc.invalidateQueries({ queryKey: ['admin/profiles'] }) },
  })

  if (isLoading || !data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const profiles = data.profiles

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Profiles</h1>
        <span className="text-sm text-gray-400">{profiles.length} total</span>
      </div>

      <div className="card p-5 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Create a new profile</h2>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate() }}>
          <input required className="input flex-1" placeholder="e.g. Tianyi – Backend Engineer"
                 value={name} onChange={(e) => setName(e.target.value)} />
          <button disabled={create.isPending} className="btn-primary shrink-0">
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </form>
      </div>

      {profiles.length > 0 ? (
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {profiles.map((p) => (
            <li key={p.id}>
              <Link to={`/admin/profiles/${p.id}`}
                    className="flex items-center justify-between px-5 py-4 hover:bg-slate-50 transition">
                <div>
                  <p className="font-semibold text-gray-900">{p.name}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {p.batch_count} batches ·{' '}
                    {p.base_resume_filename ? (
                      <span className="text-gray-600">{p.base_resume_filename}</span>
                    ) : (
                      <span className="text-amber-600 font-medium">no base resume</span>
                    )}
                  </p>
                </div>
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>No profiles yet. Create one above to get started.</Empty>
      )}
    </>
  )
}
