import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft, Download, ExternalLink, RotateCw, MessageSquare,
} from 'lucide-react'
import clsx from 'clsx'
import { api, type BatchDetail, type Job, FAIL_REASON } from '@/lib/api'
import { Alert, Progress } from '@/components/ui'
import { StatusOrb, rowTintForStatus } from '@/components/charts'
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
  const reapply = useMutation({
    mutationFn: (jid: number) => api.post(`/api/admin/batches/${bid}/jobs/${jid}/reapply`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
  })

  const [manualJob, setManualJob] = useState<Job | null>(null)
  const [noteJob, setNoteJob] = useState<Job | null>(null)

  const saveNote = useMutation({
    mutationFn: ({ jid, text }: { jid: number; text: string }) =>
      api.post(`/api/admin/batches/${bid}/jobs/${jid}/note`, { text }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
  })
  const markNoteSeen = useMutation({
    mutationFn: (jid: number) =>
      api.post(`/api/admin/batches/${bid}/jobs/${jid}/note/seen`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin/batch', bid] })
      qc.invalidateQueries({ queryKey: ['admin/notes/unread'] })
    },
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

      {/* Slim metric strip — single row of numbers + a 4px progress bar */}
      <div className="card px-4 py-2.5 mb-4">
        <div className="flex items-center gap-5 text-sm flex-wrap">
          <div className="flex items-baseline gap-1.5">
            <span className="text-xs uppercase tracking-wider text-gray-400 font-semibold">Tailored</span>
            <span className="font-bold tabular-nums text-gray-800">{summary.done}</span>
            <span className="text-gray-300">/ {summary.total}</span>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-xs uppercase tracking-wider text-gray-400 font-semibold">Applied</span>
            <span className={clsx('font-bold tabular-nums',
              summary.done > 0 && summary.applied >= summary.done ? 'text-green-600' : 'text-brand-600')}>
              {summary.applied}
            </span>
            <span className="text-gray-300">/ {summary.done}</span>
          </div>
          <div className="flex items-center gap-2 ml-auto flex-wrap">
            {summary.in_flight > 0 && <span className="chip chip-tailoring">{summary.in_flight} in progress</span>}
            {summary.needs_jd > 0 && <span className="chip chip-needs_manual_jd">{summary.needs_jd} need JD</span>}
            {summary.errors > 0 && <span className="chip chip-error">{summary.errors} errors</span>}
          </div>
        </div>
        <div className="mt-2 -mx-1">
          <Progress percent={summary.percent} color="green" />
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
                <Th className="w-[60px] text-center">Status</Th>
                <Th>Job</Th>
                <Th className="w-[110px] text-center">Open JD</Th>
                <Th className="w-[260px]">Application</Th>
                <Th className="w-[200px] text-center">Actions</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((j) => (
                <AdminRow
                  key={j.id}
                  job={j}
                  onRetry={() => retry.mutate(j.id)}
                  onAppStatus={(status) => setAppStatus.mutate({ jid: j.id, status })}
                  onReapply={() => reapply.mutate(j.id)}
                  onNeedsJd={() => setManualJob(j)}
                  onOpenNote={() => {
                    setNoteJob(j)
                    if (j.has_unread_note) markNoteSeen.mutate(j.id)
                  }}
                />
              ))}
              {jobs.length === 0 && (
                <tr><td colSpan={5} className="p-10 text-center text-sm text-gray-400">No jobs yet.</td></tr>
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
      {noteJob && (
        <NoteDialog
          job={noteJob}
          onClose={() => setNoteJob(null)}
          onSave={(text) => saveNote.mutate({ jid: noteJob.id, text }, {
            onSuccess: () => setNoteJob(null),
          })}
          pending={saveNote.isPending}
        />
      )}
    </>
  )
}

function Th({ className, children }: { className?: string; children?: React.ReactNode }) {
  return <th className={clsx('px-3 py-2.5 font-semibold', className)}>{children}</th>
}

function UploadVerdictPill({
  match, filename, observedAt,
}: {
  match: 'tailored' | 'base' | 'other' | null | undefined
  filename?: string | null
  observedAt?: string | null
}) {
  if (!match) {
    // Show an explicit "no upload observed" placeholder so the user always
    // knows whether the audit is missing or it just hasn't happened.
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-dashed border-gray-300 text-[11px] text-gray-400"
        title="The extension didn't see a file uploaded for this job yet."
      >
        <span className="w-2 h-2 rounded-full bg-gray-300" />
        Upload not yet observed
      </span>
    )
  }
  const meta = match === 'tailored'
    ? { dot: 'bg-emerald-500', cls: 'bg-emerald-50 text-emerald-800 border-emerald-200', label: 'Tailored uploaded' }
    : match === 'base'
    ? { dot: 'bg-amber-500',   cls: 'bg-amber-50   text-amber-800   border-amber-200',   label: 'Base resume uploaded' }
    : { dot: 'bg-rose-500',    cls: 'bg-rose-50    text-rose-800    border-rose-200',    label: 'Different file uploaded' }
  const fname = filename || '(unknown filename)'
  const tooltip = observedAt
    ? `${meta.label}: ${fname}\nObserved ${new Date(observedAt).toLocaleString()}`
    : `${meta.label}: ${fname}`
  return (
    <span
      title={tooltip}
      className={clsx(
        'inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-medium max-w-full',
        meta.cls,
      )}
    >
      <span className={clsx('w-2 h-2 rounded-full flex-shrink-0', meta.dot)} />
      <span className="font-semibold whitespace-nowrap">{meta.label}</span>
      <span className="opacity-60 truncate" title={fname}>· {fname}</span>
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

function AdminRow({
  job, onRetry, onAppStatus, onReapply, onNeedsJd, onOpenNote,
}: {
  job: Job
  onRetry: () => void
  onAppStatus: (status: string) => void
  onReapply: () => void
  onNeedsJd: () => void
  onOpenNote: () => void
}) {
  const isDone = job.status === 'done'
  const needsJd = job.status === 'needs_manual_jd'
  return (
    <tr className={clsx(
      'hover:bg-slate-50/80 transition group',
      rowTintForStatus(job.status),
    )}>
      {/* status — colored orb */}
      <td className="px-3 py-3 align-top text-center">
        <StatusOrb status={job.status} size={28} />
      </td>

      {/* job: company / title / [work_type, location, coverage chip] */}
      <td className="px-3 py-3 align-top">
        <div className="font-semibold text-gray-900 truncate" title={job.company || ''}>
          {job.company || <span className="text-gray-300">(no company)</span>}
        </div>
        <div className="text-gray-700 truncate" title={job.title || ''}>
          {job.title || <span className="text-gray-300">(no title)</span>}
        </div>
        <div className="flex items-center gap-2 mt-1.5 text-xs text-gray-500 flex-wrap">
          <WorkTypeBadge value={job.work_type} />
          {job.location && <span className="truncate" title={job.location}>{job.location}</span>}
          <CoverageInlineChip job={job} />
        </div>
        {job.error_message && (() => {
          const fr = job.fail_reason ? FAIL_REASON[job.fail_reason] : null
          const tone = fr?.tone === 'red'
            ? 'text-red-700 bg-red-50 border-red-200'
            : 'text-amber-800 bg-amber-50 border-amber-200'
          return (
            <div className={clsx('mt-1.5 rounded border px-1.5 py-1', tone)}>
              {fr && (
                <div className="flex items-center gap-1.5 text-[11px] font-semibold mb-0.5">
                  <span>{fr.label}</span>
                  <span className="opacity-60">·</span>
                  <span className="uppercase tracking-wide opacity-80">{fr.action}</span>
                </div>
              )}
              <p className="text-[11px] line-clamp-2" title={job.error_message}>{job.error_message}</p>
            </div>
          )
        })()}
      </td>

      {/* JD: dedicated prominent open-link column */}
      <td className="px-3 py-3 align-top">
        <a href={job.url} target="_blank" rel="noopener noreferrer"
           title={job.url}
           className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-sm font-semibold text-brand-700 bg-brand-50 hover:bg-brand-100 border border-brand-200 rounded-md transition">
          <ExternalLink className="w-4 h-4" /> Open
        </a>
      </td>

      {/* application: properly-sized select + prominent verdict pill */}
      <td className="px-3 py-3 align-top">
        <div className="flex flex-col gap-1.5">
          <AppStatusSelect
            value={job.application_status || 'not_yet'}
            disabled={!isDone}
            onChange={onAppStatus}
          />
          <AppliedMeta job={job} onReapply={onReapply} />
          <UploadVerdictPill
            match={job.upload_match}
            filename={job.upload_filename}
            observedAt={job.upload_observed_at}
          />
        </div>
      </td>

      {/* actions: docx / pdf / Note / Edit JD */}
      <td className="px-3 py-3 align-top">
        <div className="flex items-center justify-center gap-1.5 flex-wrap">
          {isDone && job.has_docx ? (
            <>
              <a href={`/download/${job.id}/docx`}
                 title="Download .docx"
                 className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded-md transition shadow-sm">
                <Download className="w-3.5 h-3.5" /> .docx
              </a>
              <a href={`/download/${job.id}/pdf`}
                 title="Download .pdf (generated on first click)"
                 className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-red-700 bg-red-50 hover:bg-red-100 border border-red-200 rounded-md transition">
                .pdf
              </a>
            </>
          ) : isDone && !job.has_docx ? (
            <button
              onClick={onRetry}
              title="Resume file was pruned. Re-tailor and regenerate the .docx."
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-brand-700 bg-brand-50 hover:bg-brand-100 border border-brand-200 rounded-md transition"
            >
              <RotateCw className="w-3.5 h-3.5" /> Re-tailor
            </button>
          ) : null}
          <NoteButton job={job} onClick={onOpenNote} />
          {(needsJd || job.status === 'error' || isDone) && (
            <button
              onClick={onNeedsJd}
              title={
                needsJd ? 'Paste the job description manually' :
                job.status === 'error' ? 'Edit JD and re-run' :
                'Edit JD and re-tailor'
              }
              className={clsx(
                'inline-flex items-center px-3 py-1.5 text-xs font-semibold rounded-md transition border',
                needsJd
                  ? 'text-amber-700 bg-amber-50 hover:bg-amber-100 border-amber-200'
                  : job.status === 'error'
                  ? 'text-red-700 bg-red-50 hover:bg-red-100 border-red-200'
                  : 'text-gray-600 bg-white hover:bg-slate-50 border-gray-300',
              )}
            >
              {needsJd ? 'Paste JD' : job.status === 'error' ? 'Fix JD' : 'Edit JD'}
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

const APP_STATUS_OPTIONS: { v: string; t: string }[] = [
  { v: 'not_yet',     t: '— not yet' },
  { v: 'applied',     t: '✓ applied' },
  { v: 'error',       t: '✕ error' },
  { v: 'not_remote',  t: '⊘ not remote' },
  { v: 'unavailable', t: '⌫ unavailable' },
]

function AppStatusSelect({
  value, disabled, onChange,
}: { value: string; disabled?: boolean; onChange: (v: string) => void }) {
  // Properly button-sized so the click target reads as the primary action
  // in the row, not an afterthought.
  const cls = clsx(
    'w-full text-sm font-medium border-2 rounded-md px-2.5 py-1.5 cursor-pointer focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-40 transition',
    value === 'applied'     && 'bg-green-50  text-green-800  border-green-300',
    value === 'error'       && 'bg-red-50    text-red-800    border-red-300',
    value === 'not_remote'  && 'bg-slate-100 text-slate-700  border-slate-300',
    value === 'unavailable' && 'bg-amber-50  text-amber-800  border-amber-300',
    (value === 'not_yet' || !value) && 'bg-white text-gray-600 border-gray-300 hover:border-brand-300',
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


function NoteButton({ job, onClick }: { job: Job; onClick: () => void }) {
  const hasNote = !!(job.note && job.note.trim())
  const unread = !!job.has_unread_note
  return (
    <button
      onClick={onClick}
      title={unread ? 'Unread note — click to read' :
             hasNote ? 'View / edit collaboration note' :
                       'Leave a note for the co-worker'}
      className={clsx(
        'relative inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md border transition',
        unread
          ? 'text-rose-700 bg-rose-50 border-rose-300 hover:bg-rose-100 animate-pulse'
          : hasNote
          ? 'text-indigo-700 bg-indigo-50 border-indigo-200 hover:bg-indigo-100'
          : 'text-gray-600 bg-white border-gray-300 hover:bg-slate-50',
      )}
    >
      <MessageSquare className="w-3.5 h-3.5" />
      Note
      {unread && (
        <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-rose-500 ring-2 ring-white" />
      )}
    </button>
  )
}


function NoteDialog({
  job, onClose, onSave, pending,
}: {
  job: Job
  onClose: () => void
  onSave: (text: string) => void
  pending: boolean
}) {
  const [text, setText] = useState(job.note || '')
  const dirty = (job.note || '') !== text
  const lastUpdated = job.note_updated_at ? new Date(job.note_updated_at) : null
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={onClose}>
      <div className="card w-full max-w-xl p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-900 text-lg flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-indigo-500" /> Collaboration note
            </h3>
            <p className="text-xs text-gray-500 mt-0.5 truncate">
              {job.company && <span className="font-medium">{job.company}</span>}
              {job.title && <span> · {job.title}</span>}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none ml-3">✕</button>
        </div>

        <textarea
          autoFocus
          rows={8}
          className="input font-sans resize-y w-full"
          placeholder="Leave a note for your co-worker about this job…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        <div className="flex items-center justify-between mt-3">
          <p className="text-xs text-gray-400">
            {lastUpdated ? <>Last edited {lastUpdated.toLocaleString()}</> : 'No note yet'}
          </p>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="btn-secondary text-sm">Close</button>
            <button
              disabled={!dirty || pending}
              onClick={() => onSave(text.trim())}
              className="btn-primary text-sm"
            >
              {pending ? 'Saving…' : dirty ? 'Save note' : 'Saved'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


function relativeDays(iso: string): string {
  const t = new Date(iso).getTime()
  const days = Math.floor((Date.now() - t) / 86400000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  if (months < 12) return `${months}mo ago`
  const years = Math.round(days / 365)
  return `${years}y ago`
}


function AppliedMeta({ job, onReapply }: { job: Job; onReapply: () => void }) {
  // Two states worth surfacing:
  //   (1) Applied → show "Applied 14d ago · N×" + a +1 button for re-applies.
  //   (2) Not yet but apply_count > 0 → it was applied before and undone, hint
  //       that this is a known posting.
  const applied = job.application_status === 'applied'
  const count = job.apply_count || 0
  const at = job.applied_at
  if (!applied && count === 0) return null
  return (
    <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
      {applied && at && (
        <span className="text-emerald-700 font-medium">Applied {relativeDays(at)}</span>
      )}
      {!applied && count > 0 && (
        <span className="text-gray-500">Previously applied {count}×</span>
      )}
      {count > 1 && (
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold tabular-nums"
          title={`Applied ${count} time${count === 1 ? '' : 's'}`}
        >
          {count}×
        </span>
      )}
      {applied && (
        <button
          onClick={onReapply}
          title="Reposted? Mark applied again (bumps the count)."
          className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700 bg-brand-50 hover:bg-brand-100 border border-brand-200 rounded transition"
        >
          <RotateCw className="w-2.5 h-2.5" /> +1 again
        </button>
      )}
    </div>
  )
}


function CoverageInlineChip({ job }: { job: Job }) {
  const cf = job.coverage_final
  if (!cf) return null
  const after = Math.round(cf.weighted_coverage * 100)
  const before = job.coverage_initial ? Math.round(job.coverage_initial.weighted_coverage * 100) : null
  const tone =
    after >= 80 ? 'text-emerald-700 bg-emerald-50 border-emerald-200' :
    after >= 60 ? 'text-amber-700 bg-amber-50 border-amber-200' :
                  'text-rose-700 bg-rose-50 border-rose-200'
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold tabular-nums',
        tone,
      )}
      title="JD-weighted coverage: before tailoring → after tailoring"
    >
      {before != null && (
        <>
          <span className="opacity-60">{before}%</span>
          <span className="opacity-50">→</span>
        </>
      )}
      <span>{after}%</span>
      {before != null && before !== after && (
        <span className="opacity-70">{after - before > 0 ? '+' : ''}{after - before}</span>
      )}
    </span>
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
