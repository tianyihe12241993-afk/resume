import { useState, useRef, useEffect } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, Check, TriangleAlert,
  Upload, FileText, Pencil, Trash2, AlertOctagon, Wand2, UsersRound,
} from 'lucide-react'
import { api, type ProfileDetail } from '@/lib/api'
import { Alert } from '@/components/ui'
import { Avatar } from '@/components/charts'
import { useAuth } from '@/hooks/useAuth'
import { formatDateTime } from '@/lib/format'

export default function ProfileDetailPage() {
  const { id } = useParams()
  const pid = Number(id)
  const qc = useQueryClient()
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const { data } = useQuery({
    queryKey: ['admin/profile', pid],
    queryFn: () => api.get<ProfileDetail>(`/api/admin/profiles/${pid}`),
  })

  const { data: me } = useAuth()
  const isAdmin = !!me?.is_admin

  const [editingName, setEditingName] = useState(false)
  const [name, setName] = useState('')
  useEffect(() => {
    if (data) setName(data.profile.name)
  }, [data])

  const [urls, setUrls] = useState('')

  // Tailor prompt state
  const [prompt, setPrompt] = useState('')
  const [promptDirty, setPromptDirty] = useState(false)
  useEffect(() => {
    if (data) {
      setPrompt(data.profile.tailor_prompt || '')
      setPromptDirty(false)
    }
  }, [data])

  const { data: defaultPrompt } = useQuery({
    queryKey: ['admin/tailor-prompt-default'],
    queryFn: () => api.get<{ prompt: string }>('/api/admin/tailor-prompt-default'),
    staleTime: Infinity,
  })

  const saveProfile = useMutation({
    mutationFn: (patch: { name?: string; tailor_prompt?: string }) =>
      api.post(`/api/admin/profiles/${pid}/update`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/profile', pid] }),
  })
  const upload = useMutation({
    mutationFn: (f: File) => api.upload(`/api/admin/profiles/${pid}/resume`, f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/profile', pid] }),
  })
  const startBatch = useMutation({
    mutationFn: () => api.post<{ batch_id: number | null }>(
      '/api/admin/batches', { profile_id: pid, urls }),
    onSuccess: (res) => { if (res.batch_id) nav(`/admin/batches/${res.batch_id}`) },
  })
  const deleteProfile = useMutation({
    mutationFn: () => api.post(`/api/admin/profiles/${pid}/delete`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin/profiles'] })
      qc.invalidateQueries({ queryKey: ['admin/dashboard'] })
      nav('/admin/profiles')
    },
  })

  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const { profile, batches } = data

  const nameDirty = name.trim() && name.trim() !== profile.name

  return (
    <>
      <Link to="/admin/profiles"
            className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition">
        <ChevronLeft className="w-4 h-4" /> Profiles
      </Link>

      {/* ── Profile heading + name editor ─────────────────────────── */}
      <div className="flex items-center gap-4 mb-6">
        <Avatar name={profile.name} size={56} />
        <div className="flex-1 min-w-0">
          {editingName ? (
            <form className="flex items-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (nameDirty) saveProfile.mutate({ name: name.trim() })
                    setEditingName(false)
                  }}>
              <input autoFocus className="input text-xl font-bold flex-1 max-w-md"
                     value={name} onChange={(e) => setName(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Escape') { setName(profile.name); setEditingName(false) } }} />
              <button className="btn-primary text-sm">Save</button>
              <button type="button" onClick={() => { setName(profile.name); setEditingName(false) }}
                      className="btn-secondary text-sm">Cancel</button>
            </form>
          ) : (
            <div className="flex items-center gap-2 group">
              <h1 className="text-2xl font-bold text-gray-900">{profile.name}</h1>
              {isAdmin && (
                <button onClick={() => setEditingName(true)}
                        title="Rename profile"
                        className="text-gray-400 hover:text-brand-600 transition">
                  <Pencil className="w-4 h-4" />
                </button>
              )}
            </div>
          )}
          <p className="text-xs text-gray-400 mt-1">
            Created {formatDateTime(profile.created_at)} · {profile.batch_count} batches
          </p>
        </div>
      </div>

      {/* ── Base resume ───────────────────────────────────────────── */}
      <div className="mb-6">
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="w-4 h-4 text-brand-500" />
            <h2 className="text-base font-semibold text-gray-900">Base resume</h2>
          </div>

          {profile.has_base_resume ? (
            <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 mb-3">
              <Check className="w-4 h-4 shrink-0" />
              <span className="font-medium truncate flex-1">{profile.base_resume_filename}</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
              <TriangleAlert className="w-4 h-4 shrink-0" />
              <span>Not uploaded — batches can't run until you upload one.</span>
            </div>
          )}

          {isAdmin && (<>
            <input ref={fileRef} type="file" accept=".docx" className="hidden"
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f) }} />
            <button onClick={() => fileRef.current?.click()} disabled={upload.isPending}
                    className="btn-secondary text-sm w-full">
              <Upload className="w-4 h-4" />
              {upload.isPending ? 'Uploading…' : profile.has_base_resume ? 'Replace .docx' : 'Upload .docx'}
            </button>
            {upload.isError && <div className="mt-2"><Alert variant="error">{(upload.error as Error).message}</Alert></div>}
          </>)}
        </div>
      </div>

      {/* ── Tailoring prompt (admin) ──────────────────────────────── */}
      {isAdmin && (
      <div className="card p-5 mb-6">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Wand2 className="w-4 h-4 text-brand-500" />
            <h2 className="text-base font-semibold text-gray-900">Tailoring prompt</h2>
            {profile.uses_default_prompt ? (
              <span className="chip bg-gray-100 text-gray-600">using default</span>
            ) : (
              <span className="chip chip-tailoring">custom</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {prompt && (
              <button type="button" disabled={saveProfile.isPending}
                      onClick={() => {
                        if (!confirm('Clear this profile\'s custom prompt and fall back to the default?')) return
                        saveProfile.mutate({ tailor_prompt: '' })
                      }}
                      className="text-xs text-gray-500 hover:text-red-600 transition">
                Clear &amp; use default
              </button>
            )}
            {defaultPrompt && (
              <button type="button"
                      onClick={() => { setPrompt(defaultPrompt.prompt); setPromptDirty(true) }}
                      className="text-xs text-gray-500 hover:text-brand-600 transition">
                Load default
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          Override the system prompt sent to Claude when tailoring resumes for this profile.
          Leave empty to use the built-in default. Edits apply to future batches only —
          already-tailored resumes won't change.
        </p>
        <textarea
          rows={14}
          value={prompt}
          onChange={(e) => { setPrompt(e.target.value); setPromptDirty(true) }}
          placeholder={defaultPrompt?.prompt ?? 'Loading default prompt…'}
          className="input font-mono text-xs leading-relaxed resize-y w-full"
        />
        <div className="flex items-center justify-between mt-3">
          <p className="text-xs text-gray-400">
            {prompt.length.toLocaleString()} chars
            {prompt.trim() === (defaultPrompt?.prompt ?? '').trim() && prompt &&
              ' · matches the default exactly'}
          </p>
          <button type="button"
                  disabled={!promptDirty || saveProfile.isPending}
                  onClick={() => { saveProfile.mutate({ tailor_prompt: prompt }) }}
                  className="btn-primary text-sm">
            {saveProfile.isPending ? 'Saving…' : 'Save prompt'}
          </button>
        </div>
        {saveProfile.isError && (
          <div className="mt-2"><Alert variant="error">{(saveProfile.error as Error).message}</Alert></div>
        )}
      </div>
      )}

      {/* ── Assign to bidders (admin) ─────────────────────────────── */}
      {isAdmin && <BidderAccessCard pid={pid} />}

      {/* ── New batch ─────────────────────────────────────────────── */}
      <div className="card p-5 mb-6">
        <h2 className="text-base font-semibold text-gray-900 mb-3">New batch</h2>
        <form className="space-y-3"
              onSubmit={(e) => { e.preventDefault(); if (urls.trim()) startBatch.mutate() }}>
          <textarea rows={8} required className="input font-mono resize-y"
                    placeholder="Paste one job URL per line. Lines starting with # are ignored."
                    value={urls} onChange={(e) => setUrls(e.target.value)} />
          {startBatch.isError && <Alert variant="error">{(startBatch.error as Error).message}</Alert>}
          <div className="flex items-center gap-3">
            <button disabled={!profile.has_base_resume || startBatch.isPending} className="btn-primary">
              {profile.has_base_resume ? (startBatch.isPending ? 'Starting…' : 'Start batch') : 'Upload base resume first'}
            </button>
            <p className="text-xs text-gray-400">Multiple batches per day merge into one.</p>
          </div>
        </form>
      </div>

      {/* ── Batch history ─────────────────────────────────────────── */}
      <div className="card p-5 mb-6">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Batch history</h2>
        {batches.length > 0 ? (
          <ul className="divide-y divide-slate-100">
            {batches.map((b) => (
              <li key={b.id} className="py-2.5 flex items-center justify-between text-sm">
                <Link to={`/admin/batches/${b.id}`}
                      className="font-medium hover:underline text-gray-800">
                  {formatDateTime(b.created_at)}
                </Link>
                <span className="text-gray-400">{b.url_count} URLs</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-400">No batches yet.</p>
        )}
      </div>

      {/* ── Danger zone (admin) ───────────────────────────────────── */}
      {isAdmin && (
      <div className="border border-red-200 rounded-xl p-5 bg-red-50/40">
        <div className="flex items-start gap-3">
          <AlertOctagon className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div className="flex-1">
            <h2 className="text-base font-semibold text-red-900">Delete this profile</h2>
            <p className="text-sm text-red-700/80 mt-1">
              Permanently deletes <span className="font-semibold">{profile.name}</span>,
              all {profile.batch_count} batches, the uploaded base resume, and every tailored .docx.
              This cannot be undone.
            </p>
          </div>
          <button
            onClick={() => {
              if (confirm(`Really delete "${profile.name}"? This removes ${profile.batch_count} batches and all tailored resumes permanently.`)) {
                deleteProfile.mutate()
              }
            }}
            disabled={deleteProfile.isPending}
            className="btn-danger text-sm shrink-0"
          >
            <Trash2 className="w-4 h-4" />
            {deleteProfile.isPending ? 'Deleting…' : 'Delete profile'}
          </button>
        </div>
      </div>
      )}
    </>
  )
}

// ── Admin: assign this profile to bidders ────────────────────────────────────
interface BidderRow { id: number; name: string; email: string; has_access: boolean }
function BidderAccessCard({ pid }: { pid: number }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['admin/profile-access', pid],
    queryFn: () => api.get<{ bidders: BidderRow[] }>(`/api/admin/profiles/${pid}/access`),
  })
  const setAccess = useMutation({
    mutationFn: ({ uid, granted }: { uid: number; granted: boolean }) =>
      api.post(`/api/admin/profiles/${pid}/access/${uid}`, { granted }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/profile-access', pid] }),
  })

  const bidders = data?.bidders ?? []
  return (
    <div className="card p-5 mb-6">
      <div className="flex items-center gap-2 mb-1">
        <UsersRound className="w-4 h-4 text-brand-500" />
        <h2 className="text-base font-semibold text-gray-900">Assign to bidders</h2>
      </div>
      <p className="text-xs text-gray-400 mb-4">
        Toggle which bidders can see and work on this profile. They only see profiles you assign.
      </p>
      {bidders.length === 0 ? (
        <p className="text-sm text-gray-400">No approved bidders yet — approve some on the Members page.</p>
      ) : (
        <ul className="divide-y divide-slate-100 -mx-5">
          {bidders.map((b) => (
            <li key={b.id} className="px-5 py-2.5 flex items-center gap-3">
              <Avatar name={b.name} size={28} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{b.name}</p>
                <p className="text-xs text-gray-400 truncate">{b.email}</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" className="sr-only peer" checked={b.has_access}
                       disabled={setAccess.isPending}
                       onChange={(e) => setAccess.mutate({ uid: b.id, granted: e.target.checked })} />
                <div className="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:bg-brand-600 transition" />
                <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition peer-checked:translate-x-4" />
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
