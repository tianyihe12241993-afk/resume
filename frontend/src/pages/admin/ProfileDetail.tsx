import { useState, useRef, useEffect } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, Check, TriangleAlert, Copy,
  Upload, FileText, Pencil, Trash2, KeyRound, Mail, AlertOctagon,
} from 'lucide-react'
import { api, type ProfileDetail } from '@/lib/api'
import { Alert } from '@/components/ui'
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

  const [editingName, setEditingName] = useState(false)
  const [name, setName] = useState('')
  useEffect(() => {
    if (data) setName(data.profile.name)
  }, [data])

  const [accessName, setAccessName] = useState('')
  const [accessEmail, setAccessEmail] = useState('')
  const [urls, setUrls] = useState('')
  const [copied, setCopied] = useState<number | null>(null)

  const saveProfile = useMutation({
    mutationFn: (patch: { name?: string }) =>
      api.post(`/api/admin/profiles/${pid}/update`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/profile', pid] }),
  })
  const upload = useMutation({
    mutationFn: (f: File) => api.upload(`/api/admin/profiles/${pid}/resume`, f),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/profile', pid] }),
  })
  const grant = useMutation({
    mutationFn: () => api.post(`/api/admin/profiles/${pid}/access`,
      { email: accessEmail, name: accessName || null }),
    onSuccess: () => {
      setAccessEmail(''); setAccessName('')
      qc.invalidateQueries({ queryKey: ['admin/profile', pid] })
    },
  })
  const revoke = useMutation({
    mutationFn: (aid: number) => api.post(`/api/admin/profiles/${pid}/access/${aid}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/profile', pid] }),
  })
  const resetInvite = useMutation({
    mutationFn: (uid: number) => api.post(`/api/admin/users/${uid}/reset-invite`),
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
  const { profile, accesses, batches } = data

  const nameDirty = name.trim() && name.trim() !== profile.name

  return (
    <>
      <Link to="/admin/profiles"
            className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition">
        <ChevronLeft className="w-4 h-4" /> Profiles
      </Link>

      {/* ── Profile heading + name editor ─────────────────────────── */}
      <div className="mb-6">
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
            <button onClick={() => setEditingName(true)}
                    className="text-gray-300 hover:text-brand-600 transition opacity-0 group-hover:opacity-100">
              <Pencil className="w-4 h-4" />
            </button>
          </div>
        )}
        <p className="text-xs text-gray-400 mt-1">
          Created {formatDateTime(profile.created_at)} · {profile.batch_count} batches
        </p>
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

          <input ref={fileRef} type="file" accept=".docx" className="hidden"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f) }} />
          <button onClick={() => fileRef.current?.click()} disabled={upload.isPending}
                  className="btn-secondary text-sm w-full">
            <Upload className="w-4 h-4" />
            {upload.isPending ? 'Uploading…' : profile.has_base_resume ? 'Replace .docx' : 'Upload .docx'}
          </button>
          {upload.isError && <div className="mt-2"><Alert variant="error">{(upload.error as Error).message}</Alert></div>}
        </div>
      </div>

      {/* ── Bidder access ──────────────────────────────────────────── */}
      <div className="card p-5 mb-6">
        <h2 className="text-base font-semibold text-gray-900 mb-1">Bidder access</h2>
        <p className="text-xs text-gray-400 mb-4">
          Grant a bidder access to this profile. They'll get a setup link to set a password.
        </p>

        <form className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2 mb-5"
              onSubmit={(e) => { e.preventDefault(); if (accessEmail) grant.mutate() }}>
          <input placeholder="Bidder name (optional)" className="input"
                 value={accessName} onChange={(e) => setAccessName(e.target.value)} />
          <input type="email" required placeholder="bidder@email.com" className="input"
                 value={accessEmail} onChange={(e) => setAccessEmail(e.target.value)} />
          <button disabled={grant.isPending} className="btn-primary text-sm whitespace-nowrap">
            {grant.isPending ? 'Granting…' : '+ Grant access'}
          </button>
        </form>

        {accesses.length > 0 ? (
          <ul className="divide-y divide-slate-100 -mx-5">
            {accesses.map((a) => (
              <li key={a.id} className="px-5 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <span className="w-8 h-8 rounded-full bg-brand-100 text-brand-700 text-xs font-semibold grid place-items-center shrink-0">
                      {((a.user.name || a.user.email)[0] || '?').toUpperCase()}
                    </span>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Link to={`/admin/bidders/${a.user.id}`}
                              className="font-medium text-sm hover:underline text-gray-900">
                          {a.user.name || a.user.email}
                        </Link>
                        {!a.user.password_set && <span className="chip chip-needs_manual_jd">pending setup</span>}
                      </div>
                      {a.user.name && (
                        <p className="text-xs text-gray-400 flex items-center gap-1 mt-0.5">
                          <Mail className="w-3 h-3" /> {a.user.email}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button onClick={() => resetInvite.mutate(a.user.id)}
                            title="Reset invite"
                            className="p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded transition">
                      <KeyRound className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => confirm(`Revoke access for ${a.user.name || a.user.email}?`) && revoke.mutate(a.id)}
                            title="Revoke"
                            className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
                {a.invite_url && (
                  <div className="mt-2 ml-11 flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
                    <input readOnly value={a.invite_url}
                           className="flex-1 bg-transparent text-xs text-amber-900 font-mono min-w-0" />
                    <button onClick={() => {
                      navigator.clipboard.writeText(a.invite_url!)
                      setCopied(a.user.id); setTimeout(() => setCopied(null), 1200)
                    }} className="text-[11px] bg-amber-600 text-white rounded px-2 py-0.5 shrink-0 hover:bg-amber-700 transition flex items-center gap-1">
                      <Copy className="w-3 h-3" /> {copied === a.user.id ? 'Copied!' : 'Copy link'}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-400 text-center py-4">No bidders yet.</p>
        )}
      </div>

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

      {/* ── Danger zone ───────────────────────────────────────────── */}
      <div className="border border-red-200 rounded-xl p-5 bg-red-50/40">
        <div className="flex items-start gap-3">
          <AlertOctagon className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div className="flex-1">
            <h2 className="text-base font-semibold text-red-900">Delete this profile</h2>
            <p className="text-sm text-red-700/80 mt-1">
              Permanently deletes <span className="font-semibold">{profile.name}</span>,
              all {profile.batch_count} batches, all tailored resumes, and all bidder access grants.
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
    </>
  )
}

