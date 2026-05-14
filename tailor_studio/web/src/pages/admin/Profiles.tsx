import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Pencil, Trash2, Check, X } from 'lucide-react'
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
          <input required className="input flex-1" placeholder="e.g. AI Engineering"
                 value={name} onChange={(e) => setName(e.target.value)} />
          <button disabled={create.isPending} className="btn-primary shrink-0">
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </form>
      </div>

      {profiles.length > 0 ? (
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {profiles.map((p) => <ProfileRow key={p.id} profile={p} />)}
        </ul>
      ) : (
        <Empty>No profiles yet. Create one above to get started.</Empty>
      )}
    </>
  )
}

function ProfileRow({ profile }: { profile: Profile }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(profile.name)

  const rename = useMutation({
    mutationFn: () => api.post(`/api/admin/profiles/${profile.id}/update`, { name: draft.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin/profiles'] })
      qc.invalidateQueries({ queryKey: ['admin/profile', profile.id] })
      setEditing(false)
    },
  })
  const remove = useMutation({
    mutationFn: () => api.post(`/api/admin/profiles/${profile.id}/delete`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin/profiles'] })
      qc.invalidateQueries({ queryKey: ['admin/dashboard'] })
    },
  })

  if (editing) {
    return (
      <li className="flex items-center gap-2 px-5 py-3">
        <input
          autoFocus
          className="input flex-1"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim()) rename.mutate()
            if (e.key === 'Escape') { setDraft(profile.name); setEditing(false) }
          }}
        />
        <button
          onClick={() => draft.trim() && rename.mutate()}
          disabled={rename.isPending || !draft.trim() || draft.trim() === profile.name}
          className="p-2 text-green-700 hover:bg-green-50 rounded-md transition disabled:opacity-30"
          title="Save (Enter)"
        ><Check className="w-4 h-4" /></button>
        <button
          onClick={() => { setDraft(profile.name); setEditing(false) }}
          className="p-2 text-gray-400 hover:bg-slate-50 rounded-md transition"
          title="Cancel (Esc)"
        ><X className="w-4 h-4" /></button>
      </li>
    )
  }

  return (
    <li className="flex items-center px-5 py-4 hover:bg-slate-50/60 transition">
      <Link to={`/admin/profiles/${profile.id}`} className="flex-1 min-w-0">
        <p className="font-semibold text-gray-900 truncate">{profile.name}</p>
        <p className="text-xs text-gray-400 mt-0.5">
          {profile.batch_count} batches ·{' '}
          {profile.base_resume_filename ? (
            <span className="text-gray-600">{profile.base_resume_filename}</span>
          ) : (
            <span className="text-amber-600 font-medium">no base resume</span>
          )}
        </p>
      </Link>
      <div className="flex items-center gap-1 shrink-0 ml-3">
        <button
          onClick={() => { setDraft(profile.name); setEditing(true) }}
          className="p-2 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded-md transition"
          title="Rename"
        ><Pencil className="w-4 h-4" /></button>
        <button
          onClick={() => {
            if (confirm(`Delete "${profile.name}" and all ${profile.batch_count} batch${profile.batch_count === 1 ? '' : 'es'}? This cannot be undone.`)) {
              remove.mutate()
            }
          }}
          disabled={remove.isPending}
          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-md transition"
          title="Delete profile"
        ><Trash2 className="w-4 h-4" /></button>
        <Link
          to={`/admin/profiles/${profile.id}`}
          className="p-2 text-gray-300 hover:text-gray-600 hover:bg-slate-100 rounded-md transition"
          title="Open"
        ><ChevronRight className="w-4 h-4" /></Link>
      </div>
    </li>
  )
}
