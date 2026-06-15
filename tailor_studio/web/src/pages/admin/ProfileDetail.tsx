import { useState, useRef, useEffect } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, Check, TriangleAlert, Copy,
  Upload, FileText, Pencil, Trash2, KeyRound, Mail, AlertOctagon, Wand2,
  Sparkles, Search, Clock,
} from 'lucide-react'
import { api, type ProfileDetail, type SearchConfig } from '@/lib/api'
import { Alert } from '@/components/ui'
import { Avatar } from '@/components/charts'
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
              <button onClick={() => setEditingName(true)}
                      title="Rename profile"
                      className="text-gray-400 hover:text-brand-600 transition">
                <Pencil className="w-4 h-4" />
              </button>
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

      {/* ── Tailoring prompt ──────────────────────────────────────── */}
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

      {/* Bidder access section — disabled in studio (single-user). */}
      {false && (
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
      )}

      {/* ── Auto-discover jobs ─────────────────────────────────────── */}
      <DiscoveryCard pid={pid} hasResume={profile.has_base_resume} />

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
    </>
  )
}

// ── Discovery settings + "Discover now" ──────────────────────────────────────
function DiscoveryCard({ pid, hasResume }: { pid: number; hasResume: boolean }) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['admin/search-config', pid],
    queryFn: () => api.get<{ config: SearchConfig }>(`/api/admin/profiles/${pid}/search-config`),
  })

  const [cfg, setCfg] = useState<SearchConfig | null>(null)
  useEffect(() => { if (data) setCfg(data.config) }, [data])

  const save = useMutation({
    mutationFn: (c: SearchConfig) => api.post(`/api/admin/profiles/${pid}/search-config`, c),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/search-config', pid] }),
  })
  const discover = useMutation({
    mutationFn: () => api.post<{ started: boolean; message: string }>(
      `/api/admin/profiles/${pid}/discover`),
    onSuccess: () => {
      // The discovery batch shows up in Batch history once the run finishes.
      setTimeout(() => qc.invalidateQueries({ queryKey: ['admin/profile', pid] }), 1500)
    },
  })

  if (!cfg) return null
  const set = <K extends keyof SearchConfig>(k: K, v: SearchConfig[K]) =>
    setCfg({ ...cfg, [k]: v })
  const hasInputs = cfg.keywords.trim().length > 0 || cfg.ats_companies.trim().length > 0

  return (
    <div className="card p-5 mb-6">
      <div className="flex items-center gap-2 mb-1">
        <Sparkles className="w-4 h-4 text-brand-500" />
        <h2 className="text-base font-semibold text-gray-900">Auto-discover jobs</h2>
      </div>
      <p className="text-xs text-gray-400 mb-4">
        Find aligned roles from job boards + company ATS pages, ranked by fit. Review and
        pick which to tailor — nothing is generated until you approve.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <label className="block">
          <span className="text-xs font-semibold text-gray-600">Keywords (one per line)</span>
          <textarea rows={3} className="input font-mono text-sm mt-1"
                    placeholder={'backend engineer\nplatform engineer'}
                    value={cfg.keywords} onChange={(e) => set('keywords', e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-gray-600">Locations (one per line)</span>
          <textarea rows={3} className="input font-mono text-sm mt-1"
                    placeholder={'Remote\nNew York, NY'}
                    value={cfg.locations} onChange={(e) => set('locations', e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-gray-600">Job-board sites (comma-separated)</span>
          <input className="input text-sm mt-1" placeholder="indeed,linkedin,glassdoor,zip_recruiter,google"
                 value={cfg.sites} onChange={(e) => set('sites', e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-gray-600">ATS company boards (one "provider:slug" per line)</span>
          <textarea rows={3} className="input font-mono text-sm mt-1"
                    placeholder={'greenhouse:stripe\nlever:netflix\nashby:linear'}
                    value={cfg.ats_companies} onChange={(e) => set('ats_companies', e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-gray-600">Preferences (free text, guides ranking)</span>
          <textarea rows={2} className="input text-sm mt-1"
                    placeholder="prefer staff-level fintech; avoid pure DevOps"
                    value={cfg.preferences || ''} onChange={(e) => set('preferences', e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-gray-600">Posted within (hours)</span>
            <input type="number" min={1} className="input text-sm mt-1"
                   value={cfg.hours_old} onChange={(e) => set('hours_old', Number(e.target.value))} />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-gray-600">Results / search</span>
            <input type="number" min={1} max={200} className="input text-sm mt-1"
                   value={cfg.results_limit} onChange={(e) => set('results_limit', Number(e.target.value))} />
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700 col-span-2">
            <input type="checkbox" checked={cfg.remote}
                   onChange={(e) => set('remote', e.target.checked)}
                   className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
            Remote only
          </label>
        </div>
      </div>

      {/* Daily schedule */}
      <div className="mt-4 flex flex-wrap items-center gap-3 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2.5">
        <Clock className="w-4 h-4 text-gray-400" />
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={cfg.enabled}
                 onChange={(e) => set('enabled', e.target.checked)}
                 className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500" />
          Run automatically every day at
        </label>
        <select className="input text-sm py-1 w-auto" value={cfg.schedule_hour}
                onChange={(e) => set('schedule_hour', Number(e.target.value))}>
          {Array.from({ length: 24 }, (_, h) => (
            <option key={h} value={h}>{String(h).padStart(2, '0')}:00 PT</option>
          ))}
        </select>
      </div>

      {discover.isError && <div className="mt-3"><Alert variant="error">{(discover.error as Error).message}</Alert></div>}
      {discover.isSuccess && (
        <div className="mt-3"><Alert variant="success">{discover.data.message} The new batch will appear in Batch history below.</Alert></div>
      )}

      <div className="flex items-center gap-3 mt-4">
        <button onClick={() => save.mutate(cfg)} disabled={save.isPending}
                className="btn-secondary text-sm">
          {save.isPending ? 'Saving…' : save.isSuccess ? 'Saved ✓' : 'Save settings'}
        </button>
        <button
          onClick={async () => { await save.mutateAsync(cfg); discover.mutate() }}
          disabled={!hasResume || !hasInputs || discover.isPending}
          className="btn-primary text-sm">
          <Search className="w-4 h-4" />
          {discover.isPending ? 'Discovering…' : 'Discover now'}
        </button>
        {!hasResume && <span className="text-xs text-amber-600">Upload a base resume first.</span>}
        {hasResume && !hasInputs && <span className="text-xs text-gray-400">Add a keyword or ATS company.</span>}
      </div>
    </div>
  )
}

