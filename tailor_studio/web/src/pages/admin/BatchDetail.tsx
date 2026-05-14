import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, ChevronDown, ChevronRight, Download, ExternalLink,
  Target, RotateCw, Sparkles,
} from 'lucide-react'
import clsx from 'clsx'
import { api, type BatchDetail, type Job } from '@/lib/api'
import { Alert, Chip, Progress } from '@/components/ui'
import { formatDateTime } from '@/lib/format'

export default function BatchDetailPage() {
  const { id } = useParams()
  const bid = Number(id)
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['admin/batch', bid],
    queryFn: () => api.get<BatchDetail>(`/api/admin/batches/${bid}`),
    refetchInterval: 3000,
  })

  const retry = useMutation({
    mutationFn: (jid: number) => api.post(`/api/admin/batches/${bid}/jobs/${jid}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
  })
  const retryAll = useMutation({
    mutationFn: () => api.post<{ requeued: number }>(`/api/admin/batches/${bid}/retry-errors`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
  })
  const setAppStatus = useMutation({
    mutationFn: ({ jid, status }: { jid: number; status: string }) =>
      api.post(`/api/batches/${bid}/jobs/${jid}/app-status`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
    onError: (e) => {
      // Without this the dropdown silently reverts on refetch and the user
      // has no idea why their click did nothing.
      alert(`Couldn't update status: ${(e as Error).message || 'unknown error'}`)
    },
  })

  const [manualJob, setManualJob] = useState<Job | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const toggleExpand = (id: number) =>
    setExpanded((s) => {
      const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n
    })

  const claim = useMutation({
    mutationFn: ({ jid, terms }: { jid: number; terms: string[] }) =>
      api.post(`/api/admin/batches/${bid}/jobs/${jid}/claim`, { terms }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
  })

  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const { batch, profile, jobs, summary } = data

  return (
    <>
      <Link to={`/admin/profiles/${profile.id}`}
            className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition">
        <ChevronLeft className="w-4 h-4" /> {profile.name}
      </Link>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{formatDateTime(batch.created_at)}</h1>
        <p className="text-sm text-gray-400 mt-0.5">{profile.name} · batch #{batch.id}</p>
      </div>

      {/* progress: applied vs target */}
      <div className="card p-5 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Target className="w-4 h-4 text-brand-500" />
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Applied / Tailored
              </span>
            </div>
            <div className="flex items-baseline gap-2 mb-2">
              <span className={clsx('text-3xl font-bold tabular-nums',
                summary.done > 0 && summary.applied >= summary.done ? 'text-green-600' : 'text-brand-600')}>
                {summary.applied}
              </span>
              <span className="text-gray-400">/ {summary.done}</span>
              <span className="ml-auto text-sm text-gray-500">{summary.applied_percent}%</span>
            </div>
            <Progress
              percent={Math.min(100, summary.applied_percent)}
              color={summary.done > 0 && summary.applied >= summary.done ? 'green' : 'blue'}
            />
          </div>
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Queue</span>
            </div>
            <div className="flex items-baseline gap-2 mb-2">
              <span className="text-3xl font-bold text-green-600 tabular-nums">{summary.done}</span>
              <span className="text-gray-400">/ {summary.total}</span>
              <span className="ml-auto text-sm text-gray-500">{summary.percent}%</span>
            </div>
            <Progress percent={summary.percent} color="green" />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {summary.in_flight > 0 && <span className="chip chip-tailoring">{summary.in_flight} in progress</span>}
          {summary.needs_jd > 0 && <span className="chip chip-needs_manual_jd">{summary.needs_jd} need JD</span>}
          {summary.errors > 0 && <span className="chip chip-error">{summary.errors} errors</span>}
          {summary.done > 0 && <span className="chip chip-done">{summary.done} done</span>}
        </div>
      </div>

      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-gray-600">Jobs ({jobs.length})</h2>
        <div className="flex items-center gap-2">
          {summary.errors > 0 && (
            <button onClick={() => retryAll.mutate()} className="btn-danger text-xs py-1.5 px-3">
              Retry {summary.errors} error{summary.errors === 1 ? '' : 's'}
            </button>
          )}
          {summary.done > 0 && (
            <a href={`/download/batch/${bid}/zip`} className="btn-primary text-xs py-1.5 px-3">
              <Download className="w-3.5 h-3.5" /> Download all ({summary.done}) .zip
            </a>
          )}
        </div>
      </div>

      {/* Excel-like table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm table-fixed">
            <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-10">
              <tr className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                <Th className="w-7"> </Th>
                <Th className="w-10 text-center">#</Th>
                <Th className="w-[90px]">Status</Th>
                <Th className="w-[110px]">Application</Th>
                <Th className="w-[170px]">Company</Th>
                <Th>Title</Th>
                <Th className="w-[110px]">Coverage</Th>
                <Th className="w-[150px]">Location</Th>
                <Th className="w-[110px]">URL</Th>
                <Th className="w-[140px] text-center">Resume</Th>
                <Th className="w-[50px] text-center">Action</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((j, i) => (
                <AdminRow
                  key={j.id}
                  job={j}
                  index={i + 1}
                  expanded={expanded.has(j.id)}
                  onToggleExpand={() => toggleExpand(j.id)}
                  onRetry={() => retry.mutate(j.id)}
                  onAppStatus={(status) => setAppStatus.mutate({ jid: j.id, status })}
                  onNeedsJd={() => setManualJob(j)}
                  onClaim={(terms) => claim.mutate({ jid: j.id, terms })}
                  claimPending={claim.isPending}
                />
              ))}
              {jobs.length === 0 && (
                <tr><td colSpan={11} className="p-10 text-center text-sm text-gray-400">No jobs yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {manualJob && (
        <ManualJdDialog
          batchId={bid}
          job={manualJob}
          onClose={() => setManualJob(null)}
        />
      )}
    </>
  )
}

function Th({ className, children }: { className?: string; children: React.ReactNode }) {
  return <th className={clsx('px-3 py-2.5 font-semibold', className)}>{children}</th>
}

function AdminRow({
  index, job, expanded, onToggleExpand, onRetry, onAppStatus, onNeedsJd,
  onClaim, claimPending,
}: {
  index: number; job: Job
  expanded: boolean
  onToggleExpand: () => void
  onRetry: () => void
  onAppStatus: (status: string) => void
  onNeedsJd: () => void
  onClaim: (terms: string[]) => void
  claimPending: boolean
}) {
  const isDone = job.status === 'done'
  const needsJd = job.status === 'needs_manual_jd'
  const hasReport = isDone && job.coverage_final
  return (
    <>
      <tr className={clsx(
        'hover:bg-slate-50/80 transition group',
        expanded && 'bg-brand-50/40',
      )}>
        <td className="px-1 py-2 text-center">
          <button
            onClick={onToggleExpand}
            disabled={!hasReport}
            title={hasReport ? (expanded ? 'Collapse' : 'Show coverage report') : 'No report yet'}
            className={clsx(
              'p-0.5 rounded',
              hasReport
                ? 'text-gray-400 hover:text-brand-600 hover:bg-brand-50'
                : 'text-gray-200 cursor-not-allowed',
            )}
          >
            {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </button>
        </td>
        <td className="px-3 py-2 text-center text-xs text-gray-400 tabular-nums">{index}</td>
        <td className="px-3 py-2"><Chip status={job.status} /></td>
        <td className="px-3 py-2">
          <AppStatusSelect
            value={job.application_status || 'not_yet'}
            disabled={!isDone}
            onChange={onAppStatus}
          />
        </td>
        <td className="px-3 py-2 text-gray-900 truncate" title={job.company || ''}>
          {job.company || <span className="text-gray-300">—</span>}
        </td>
        <td className="px-3 py-2 text-gray-900 truncate" title={job.title || ''}>
          {job.title || <span className="text-gray-300">—</span>}
        </td>
        <td className="px-3 py-2">
          <CoverageCell job={job} onClick={onToggleExpand} />
        </td>
        <td className="px-3 py-2 text-gray-500 text-xs break-words" title={job.location || ''}>
          {job.location || <span className="text-gray-300">—</span>}
        </td>
        <td className="px-3 py-2">
          <a href={job.url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 hover:border-gray-400 rounded transition"
             title={job.url}>
            <ExternalLink className="w-3 h-3" /> Open
          </a>
          {job.error_message && <p className="text-[11px] text-red-600 mt-0.5 truncate" title={job.error_message}>{job.error_message}</p>}
        </td>
        <td className="px-3 py-2 text-center">
          {isDone && job.has_docx ? (
            <div className="inline-flex items-center gap-1">
              {job.download_count > 0 && (
                <span
                  title={`Downloaded ${job.download_count} time${job.download_count === 1 ? '' : 's'}`}
                  className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 rounded-full bg-slate-200 text-slate-700 text-[10px] font-semibold tabular-nums"
                >{job.download_count}</span>
              )}
              <a href={`/download/${job.id}/docx`}
                 title="Download .docx"
                 className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded transition shadow-sm"
              ><Download className="w-3 h-3" /> docx</a>
              <a href={`/download/${job.id}/pdf`}
                 title="Download .pdf (generated on first click)"
                 className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold text-red-700 bg-red-50 hover:bg-red-100 border border-red-200 rounded transition"
              >pdf</a>
            </div>
          ) : <span className="text-gray-300 text-xs">—</span>}
        </td>
        <td className="px-3 py-2 text-center">
          <div className="inline-flex items-center gap-1">
            {(needsJd || job.status === 'error' || isDone) && (
              <button
                onClick={onNeedsJd}
                title={
                  needsJd ? 'Paste the job description manually' :
                  job.status === 'error' ? 'Edit JD and re-run' :
                  'Edit JD and re-tailor'
                }
                className={clsx(
                  'text-xs font-medium px-2 py-1 rounded transition',
                  needsJd
                    ? 'text-amber-700 hover:text-amber-900 hover:bg-amber-50'
                    : job.status === 'error'
                    ? 'text-red-700 hover:text-red-900 hover:bg-red-50'
                    : 'text-gray-400 hover:text-brand-600 hover:bg-brand-50',
                )}
              >
                {needsJd ? 'Paste JD' : job.status === 'error' ? 'Fix JD' : 'Edit JD'}
              </button>
            )}
            {(job.status === 'error' || isDone) && (
              <button
                onClick={onRetry}
                title="Re-run tailoring with the existing JD"
                className="text-gray-300 hover:text-gray-600 hover:bg-slate-100 rounded p-1 transition"
              >
                <RotateCw className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </td>
      </tr>
      {expanded && hasReport && (
        <tr>
          <td colSpan={11} className="px-6 py-4 bg-slate-50/60 border-y border-slate-200">
            <CoveragePanel
              job={job}
              onClaim={onClaim}
              claimPending={claimPending}
            />
          </td>
        </tr>
      )}
    </>
  )
}

const APP_STATUS_OPTIONS: { v: string; t: string }[] = [
  { v: 'not_yet',    t: '— not yet' },
  { v: 'applied',    t: '✓ applied' },
  { v: 'error',      t: '✕ error' },
  { v: 'not_remote', t: '⊘ not remote' },
]

function AppStatusSelect({
  value, disabled, onChange,
}: { value: string; disabled?: boolean; onChange: (v: string) => void }) {
  // Color-code the picker so the row reads at a glance.
  const cls = clsx(
    'text-xs font-medium border rounded px-1.5 py-0.5 cursor-pointer focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-40',
    value === 'applied'    && 'bg-green-50  text-green-800  border-green-200',
    value === 'error'      && 'bg-red-50    text-red-800    border-red-200',
    value === 'not_remote' && 'bg-slate-100 text-slate-700  border-slate-300',
    (value === 'not_yet' || !value) && 'bg-white text-gray-500 border-gray-300',
  )
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className={cls}
      onClick={(e) => e.stopPropagation()}
    >
      {APP_STATUS_OPTIONS.map((o) => (
        <option key={o.v} value={o.v}>{o.t}</option>
      ))}
    </select>
  )
}

function CoverageCell({ job, onClick }: { job: Job; onClick: () => void }) {
  const cf = job.coverage_final
  const ci = job.coverage_initial
  if (!cf) return <span className="text-gray-300 text-xs">—</span>
  const fmtPct = (v: number) => Math.round(v * 100) + '%'
  const finalCov = fmtPct(cf.weighted_coverage)
  const initialCov = ci ? fmtPct(ci.weighted_coverage) : null
  const finalSim = cf.similarity ? fmtPct(cf.similarity.tf_cosine) : null
  return (
    <button
      onClick={onClick}
      className="text-left flex flex-col gap-0.5 hover:bg-brand-50 rounded px-1.5 py-1 transition"
      title="Click to expand the full coverage report"
    >
      <span className="text-xs font-semibold text-gray-700 tabular-nums flex items-center gap-1">
        <Sparkles className="w-3 h-3 text-brand-500" />
        {finalCov}
        {initialCov && initialCov !== finalCov && (
          <span className="text-gray-400 font-normal text-[10px]">↑ {initialCov}</span>
        )}
      </span>
      {finalSim && (
        <span className="text-[10px] text-gray-400 tabular-nums">sim {finalSim}</span>
      )}
    </button>
  )
}

function CoveragePanel({
  job, onClaim, claimPending,
}: { job: Job; onClaim: (terms: string[]) => void; claimPending: boolean }) {
  const cf = job.coverage_final!
  const ci = job.coverage_initial
  const claimedSet = new Set(job.claimed_terms || [])
  const [staged, setStaged] = useState<Set<string>>(new Set(claimedSet))
  const fmtPct = (v: number | null | undefined) =>
    v == null ? '—' : (v * 100).toFixed(1) + '%'

  const dirty =
    staged.size !== claimedSet.size ||
    [...staged].some((t) => !claimedSet.has(t))

  const toggle = (term: string) => {
    setStaged((s) => {
      const n = new Set(s); n.has(term) ? n.delete(term) : n.add(term); return n
    })
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 text-sm">
      {/* Metrics column */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          Metrics
        </h4>
        <ul className="space-y-1.5 text-xs">
          <Metric label="JD-weighted coverage"
                  current={fmtPct(cf.weighted_coverage)}
                  prev={ci ? fmtPct(ci.weighted_coverage) : null} />
          <Metric label="Lexical similarity (TF cos)"
                  current={fmtPct(cf.similarity?.tf_cosine)}
                  prev={fmtPct(ci?.similarity?.tf_cosine)} />
          <Metric label="Token overlap (Jaccard)"
                  current={fmtPct(cf.similarity?.jaccard)}
                  prev={fmtPct(ci?.similarity?.jaccard)} />
          <Metric label="Exact-match terms"
                  current={String(cf.exact_count)}
                  prev={ci ? String(ci.exact_count) : null} />
          <Metric label="Gap terms"
                  current={String(cf.gap_count)}
                  prev={ci ? String(ci.gap_count) : null} />
        </ul>
      </div>

      {/* Covered terms */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          In your tailored resume verbatim
        </h4>
        {(cf.covered_exact || []).length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {cf.covered_exact!.map((c) => (
              <span key={c.term} title={`weight ${c.weight.toFixed(2)}`}
                    className="text-[11px] px-1.5 py-0.5 rounded bg-green-100 text-green-800">
                {c.term}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-400 italic">No exact JD-term matches yet.</p>
        )}
      </div>

      {/* Gap claim */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
          Still gaps — tick what you can defend
        </h4>
        {(cf.gap || []).length > 0 ? (
          <>
            <div className="flex flex-col gap-1 max-h-44 overflow-y-auto pr-1">
              {cf.gap!.map((g) => (
                <label key={g.term} className="inline-flex items-center gap-1.5 text-xs cursor-pointer">
                  <input type="checkbox" checked={staged.has(g.term)}
                         onChange={() => toggle(g.term)}
                         className="w-3.5 h-3.5 rounded border-gray-300" />
                  <span className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-800"
                        title={`weight ${g.weight.toFixed(2)}`}>
                    {g.term}
                  </span>
                </label>
              ))}
            </div>
            <button
              disabled={!dirty || claimPending}
              onClick={() => onClaim([...staged])}
              className={clsx(
                'mt-2 text-xs font-medium px-2.5 py-1 rounded transition',
                dirty
                  ? 'bg-brand-600 text-white hover:bg-brand-700'
                  : 'bg-gray-100 text-gray-400 cursor-not-allowed',
              )}
            >
              {claimPending ? 'Rebuilding…'
                : dirty ? `Apply ${staged.size} claim${staged.size === 1 ? '' : 's'}`
                : 'No changes'}
            </button>
            <p className="text-[10px] text-gray-400 mt-1.5 leading-tight">
              Claimed terms get appended to the appropriate skill row and the .docx is rebuilt.
            </p>
          </>
        ) : (
          <p className="text-xs text-gray-400 italic">No gaps — every JD term is covered.</p>
        )}
        {(cf.must_have_phrases || []).length > 0 && (
          <details className="mt-3">
            <summary className="text-[11px] text-gray-500 cursor-pointer hover:text-gray-700">
              JD must-have phrases ({cf.must_have_phrases!.length})
            </summary>
            <ul className="mt-1 space-y-0.5 text-[11px] text-gray-600 list-disc pl-4">
              {cf.must_have_phrases!.map((p) => <li key={p}>{p}</li>)}
            </ul>
          </details>
        )}
      </div>
    </div>
  )
}

function Metric({
  label, current, prev,
}: { label: string; current: string; prev: string | null }) {
  const changed = prev != null && prev !== current
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="text-gray-500">{label}</span>
      <span className="font-semibold tabular-nums text-gray-900">
        {current}
        {changed && (
          <span className="ml-1 text-[10px] font-normal text-gray-400">
            (was {prev})
          </span>
        )}
      </span>
    </li>
  )
}

function ManualJdDialog({
  batchId, job, onClose,
}: { batchId: number; job: Job; onClose: () => void }) {
  const qc = useQueryClient()
  const [company, setCompany] = useState(job.company || '')
  const [title, setTitle] = useState(job.title || '')
  const [location, setLocation] = useState(job.location || '')
  const [description, setDescription] = useState(job.description || '')

  const submit = useMutation({
    mutationFn: () => api.post(`/api/admin/batches/${batchId}/jobs/${job.id}/manual`,
      { company, title, location, description }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin/batch', batchId] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="font-semibold text-gray-900">Paste job description</h3>
            <a href={job.url} target="_blank" rel="noopener noreferrer"
               className="text-xs text-brand-600 hover:underline break-all">{job.url}</a>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>

        <form className="space-y-3" onSubmit={(e) => {
          e.preventDefault()
          if (description.trim().length >= 100) submit.mutate()
        }}>
          <p className="text-xs text-gray-500">
            Paste the JD text below. <span className="font-medium">Company / Title / Location are optional</span> — Claude will extract them from the text if you leave them blank.
          </p>
          <div className="grid grid-cols-3 gap-2">
            <input className="input text-sm" placeholder="Company (optional)" value={company} onChange={(e) => setCompany(e.target.value)} />
            <input className="input text-sm" placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <input className="input text-sm" placeholder="Location (optional)" value={location} onChange={(e) => setLocation(e.target.value)} />
          </div>
          <textarea rows={12} required className="input font-mono resize-y"
                    placeholder="Paste the full job description here (min 100 chars)."
                    value={description} onChange={(e) => setDescription(e.target.value)} />
          {submit.isError && <Alert variant="error">{(submit.error as Error).message}</Alert>}
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">Cancel</button>
            <button disabled={submit.isPending} className="btn-primary text-sm">
              {submit.isPending ? 'Saving…' : 'Save & re-run'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
