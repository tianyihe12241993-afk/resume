import { useState, useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search as SearchIcon, ExternalLink, Download, RotateCw } from 'lucide-react'
import { Avatar } from '@/components/charts'
import clsx from 'clsx'
import { api, type Job } from '@/lib/api'
import { Chip } from '@/components/ui'
import { formatDateTime } from '@/lib/format'

interface SearchResult {
  job: Job
  batch: { id: number; created_at: string }
  profile: { id: number; name: string }
}

interface SearchResponse {
  query: string
  count: number
  results: SearchResult[]
}

const STATUS_OPTIONS = [
  { v: '', t: 'all' },
  { v: 'done', t: 'tailored' },
  { v: 'tailoring', t: 'in flight' },
  { v: 'analyzing', t: 'in flight' },
  { v: 'fetching', t: 'in flight' },
  { v: 'pending', t: 'pending' },
  { v: 'needs_manual_jd', t: 'needs JD' },
  { v: 'error', t: 'error' },
]

const WORK_TYPE_OPTIONS = [
  { v: '', t: 'all' },
  { v: 'remote', t: 'remote' },
  { v: 'hybrid', t: 'hybrid' },
  { v: 'onsite', t: 'onsite' },
  { v: 'unknown', t: 'unknown' },
]

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const initialQ = params.get('q') ?? ''
  const initialStatus = params.get('status') ?? ''
  const initialWorkType = params.get('work_type') ?? ''

  const [q, setQ] = useState(initialQ)
  const [status, setStatus] = useState(initialStatus)
  const [workType, setWorkType] = useState(initialWorkType)
  const [debouncedQ, setDebouncedQ] = useState(initialQ)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 200)
    return () => clearTimeout(t)
  }, [q])

  // Keep URL in sync (so the search is shareable / bookmarkable).
  useEffect(() => {
    const next = new URLSearchParams()
    if (debouncedQ.trim()) next.set('q', debouncedQ.trim())
    if (status) next.set('status', status)
    if (workType) next.set('work_type', workType)
    setParams(next, { replace: true })
  }, [debouncedQ, status, workType, setParams])

  const { data, isFetching, error } = useQuery({
    queryKey: ['admin/search', debouncedQ, status, workType],
    enabled: debouncedQ.trim().length > 0,
    queryFn: () => {
      const qs = new URLSearchParams()
      qs.set('q', debouncedQ.trim())
      if (status) qs.set('status', status)
      if (workType) qs.set('work_type', workType)
      return api.get<SearchResponse>('/api/admin/search?' + qs.toString())
    },
    staleTime: 5_000,
  })

  return (
    <>
      <div className="mb-5">
        <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">Search</p>
        <h1 className="text-2xl font-bold text-gray-900">Find a job</h1>
        <p className="text-sm text-gray-500 mt-1">
          Search company, title, URL, location, and JD text across every batch.
        </p>
      </div>

      <div className="card p-4 mb-4">
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex-1 min-w-[260px]">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Query
            </label>
            <div className="relative">
              <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="company, title, URL, JD keyword…"
                className="input pl-8"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Status
            </label>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className="input">
              {STATUS_OPTIONS.map((o) => (
                <option key={o.v + o.t} value={o.v}>{o.t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1 block">
              Work type
            </label>
            <select value={workType} onChange={(e) => setWorkType(e.target.value)} className="input">
              {WORK_TYPE_OPTIONS.map((o) => (
                <option key={o.v + o.t} value={o.v}>{o.t}</option>
              ))}
            </select>
          </div>
        </div>
        {debouncedQ.trim() && (
          <p className="text-xs text-gray-400 mt-2">
            {isFetching ? 'Searching…' :
              data ? `${data.count} match${data.count === 1 ? '' : 'es'} for "${debouncedQ}"` : ''}
          </p>
        )}
      </div>

      {error && (
        <div className="card p-4 text-sm text-red-700 bg-red-50 border-red-200">
          {(error as Error).message}
        </div>
      )}

      {!debouncedQ.trim() ? (
        <div className="card p-10 text-center text-sm text-gray-400 border-dashed">
          Type at least one character to search.
        </div>
      ) : !data || data.count === 0 ? (
        <div className="card p-10 text-center text-sm text-gray-400 border-dashed">
          {isFetching ? 'Searching…' : `No matches for "${debouncedQ}".`}
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                <Th className="w-[170px]">Company</Th>
                <Th>Title</Th>
                <Th className="w-[140px]">Profile</Th>
                <Th className="w-[100px]">Status</Th>
                <Th className="w-[150px]">Created</Th>
                <Th className="w-[110px] text-center">URL</Th>
                <Th className="w-[130px] text-center">Resume</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.results.map((r) => (
                <SearchRow key={r.job.id} result={r} highlight={debouncedQ.trim()} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function Th({ className, children }: { className?: string; children: React.ReactNode }) {
  return <th className={clsx('px-3 py-2.5 font-semibold', className)}>{children}</th>
}

function UploadVerdictPill({
  match, filename,
}: { match: 'tailored' | 'base' | 'other' | null | undefined; filename?: string | null }) {
  if (!match) return null
  const meta = match === 'tailored'
    ? { icon: '✓', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'Tailored' }
    : match === 'base'
    ? { icon: '⚠', cls: 'bg-amber-50 text-amber-700 border-amber-200', label: 'Base resume' }
    : { icon: '✕', cls: 'bg-rose-50 text-rose-700 border-rose-200', label: 'Other file' }
  const fname = filename || '(unknown)'
  return (
    <span
      title={`${meta.label} uploaded: ${fname}`}
      className={clsx(
        'inline-flex items-center gap-1 max-w-[160px] px-1.5 py-0.5 rounded border text-[10px] font-medium',
        meta.cls,
      )}
    >
      <span className="font-bold flex-shrink-0">{meta.icon}</span>
      <span className="truncate">{fname}</span>
    </span>
  )
}


function WorkTypeBadge({ value }: { value: 'remote' | 'hybrid' | 'onsite' | null | undefined }) {
  if (!value) return null
  const cls = value === 'remote'
    ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
    : value === 'hybrid'
    ? 'bg-amber-100 text-amber-700 border-amber-200'
    : 'bg-rose-100 text-rose-700 border-rose-200'
  const label = value[0].toUpperCase() + value.slice(1)
  return (
    <span className={clsx(
      'inline-flex items-center px-1.5 py-0.5 mr-1.5 rounded border text-[10px] font-semibold uppercase tracking-wide align-middle',
      cls,
    )} title={`Work type: ${label}`}>
      {label}
    </span>
  )
}

function SearchRow({ result, highlight }: { result: SearchResult; highlight: string }) {
  const { job, batch, profile } = result
  const isDone = job.status === 'done'
  const qc = useQueryClient()
  const retry = useMutation({
    mutationFn: () => api.post(`/api/admin/batches/${batch.id}/jobs/${job.id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/search'] }),
  })
  return (
    <tr className="hover:bg-slate-50/80 transition">
      <td className="px-3 py-2 text-gray-900 truncate max-w-[170px]" title={job.company || ''}>
        <Highlight text={job.company || '—'} term={highlight} />
      </td>
      <td className="px-3 py-2 text-gray-900">
        <Link to={`/admin/batches/${batch.id}`} className="hover:text-brand-700 hover:underline">
          <Highlight text={job.title || '(no title)'} term={highlight} />
        </Link>
        {(job.location || job.work_type) && (
          <p className="text-xs text-gray-400 mt-0.5">
            <WorkTypeBadge value={job.work_type} />
            {job.location && <Highlight text={job.location} term={highlight} />}
          </p>
        )}
      </td>
      <td className="px-3 py-2 text-xs">
        <Link to={`/admin/profiles/${profile.id}`}
              className="inline-flex items-center gap-1.5 max-w-full hover:opacity-80 transition"
              title={profile.name}>
          <Avatar name={profile.name} size={20} />
          <span className="text-gray-700 truncate">{profile.name}</span>
        </Link>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-col gap-1 items-start">
          <Chip status={job.status} />
          <UploadVerdictPill match={job.upload_match} filename={job.upload_filename} />
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-gray-500">{formatDateTime(batch.created_at)}</td>
      <td className="px-3 py-2 text-center">
        <a href={job.url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1.5 px-2 py-1 text-xs text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 rounded transition" title={job.url}>
          <ExternalLink className="w-3 h-3" /> open
        </a>
      </td>
      <td className="px-3 py-2 text-center">
        {isDone && job.has_docx ? (
          <a href={`/download/${job.id}/docx`}
             className="inline-flex items-center gap-1.5 px-2 py-1 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded transition">
            <Download className="w-3 h-3" /> .docx
          </a>
        ) : isDone && !job.has_docx ? (
          <button
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
            title="Resume file was pruned. Re-tailor and regenerate the .docx."
            className="inline-flex items-center gap-1.5 px-2 py-1 text-xs font-semibold text-brand-700 bg-brand-50 hover:bg-brand-100 border border-brand-200 rounded transition disabled:opacity-60"
          >
            <RotateCw className={'w-3 h-3 ' + (retry.isPending ? 'animate-spin' : '')} />
            {retry.isPending ? 'Queuing…' : 'Re-tailor'}
          </button>
        ) : <span className="text-gray-300 text-xs">—</span>}
      </td>
    </tr>
  )
}

function Highlight({ text, term }: { text: string; term: string }) {
  if (!term.trim()) return <>{text}</>
  const t = term.trim()
  const lower = text.toLowerCase()
  const tlow = t.toLowerCase()
  const idx = lower.indexOf(tlow)
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-100 text-yellow-900 px-0.5 rounded">
        {text.slice(idx, idx + t.length)}
      </mark>
      {text.slice(idx + t.length)}
    </>
  )
}
