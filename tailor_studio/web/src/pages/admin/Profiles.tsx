import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Pencil, Trash2, Check, X, FileCheck, FileWarning, Lock } from 'lucide-react'
import clsx from 'clsx'
import { api, type Profile } from '@/lib/api'
import { Empty } from '@/components/ui'
import { Avatar } from '@/components/charts'
import { useAuth } from '@/hooks/useAuth'

export default function Profiles() {
  const qc = useQueryClient()
  const { data: me } = useAuth()
  const isAdmin = !!me?.is_admin
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
      <div className="flex items-end justify-between mb-4">
        <div>
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-0.5">Workspace</p>
          <h1 className="text-2xl font-bold text-gray-900">
            Profiles <span className="text-gray-400 font-normal text-base">({profiles.length})</span>
          </h1>
        </div>
        {isAdmin && (
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate() }}>
            <input required className="input" placeholder="New profile name…"
                   value={name} onChange={(e) => setName(e.target.value)} />
            <button disabled={create.isPending} className="btn-primary shrink-0 whitespace-nowrap">
              {create.isPending ? 'Creating…' : '+ Create'}
            </button>
          </form>
        )}
      </div>

      {profiles.length > 0 ? (
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {profiles.map((p) => <ProfileRow key={p.id} profile={p} isAdmin={isAdmin} />)}
        </ul>
      ) : (
        <Empty>{isAdmin ? 'No profiles yet. Create one above to get started.' : 'No profiles yet.'}</Empty>
      )}
    </>
  )
}

function ProfileRow({ profile, isAdmin }: { profile: Profile; isAdmin: boolean }) {
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

  const canAccess = profile.can_access !== false
  const inner = (
    <>
      <Avatar name={profile.name} size={40} />
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-gray-900 truncate flex items-center gap-1.5">
          {profile.name}
          {!canAccess && (
            <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-gray-400 bg-slate-100 rounded-full px-1.5 py-0.5">
              <Lock className="w-2.5 h-2.5" /> no access
            </span>
          )}
        </p>
        <p className="text-xs text-gray-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
          {(profile.total ?? 0) > 0 && (
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-brand-50 text-brand-700 rounded text-[10px] font-semibold">
              {profile.applied ?? 0} applied · {profile.done ?? 0} tailored
            </span>
          )}
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded text-[10px] font-semibold">
            {profile.batch_count} {profile.batch_count === 1 ? 'batch' : 'batches'}
          </span>
          {profile.base_resume_filename ? (
            <span className="inline-flex items-center gap-1 text-emerald-700">
              <FileCheck className="w-3 h-3" />
              <span className="truncate max-w-[280px]">{profile.base_resume_filename}</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-amber-700 font-medium">
              <FileWarning className="w-3 h-3" /> no base resume
            </span>
          )}
        </p>
      </div>
    </>
  )

  return (
    <li className={clsx('flex items-center px-5 py-4 transition', canAccess ? 'hover:bg-slate-50/60' : 'bg-slate-50/40')}>
      {canAccess ? (
        <Link to={`/admin/profiles/${profile.id}`} className="flex items-center gap-3 flex-1 min-w-0">{inner}</Link>
      ) : (
        <div className="flex items-center gap-3 flex-1 min-w-0 cursor-default" title="You don't have access to this profile">{inner}</div>
      )}
      <div className="flex items-center gap-1 shrink-0 ml-3">
        {isAdmin && (<>
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
        </>)}
        {canAccess && (
          <Link
            to={`/admin/profiles/${profile.id}`}
            className="p-2 text-gray-300 hover:text-gray-600 hover:bg-slate-100 rounded-md transition"
            title="Open"
          ><ChevronRight className="w-4 h-4" /></Link>
        )}
      </div>
    </li>
  )
}
