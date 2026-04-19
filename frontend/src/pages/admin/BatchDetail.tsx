import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, Download, ExternalLink, Target, RotateCw } from 'lucide-react'
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
  const toggleApplied = useMutation({
    mutationFn: (j: Job) => api.post(`/api/batches/${bid}/jobs/${j.id}/app-status`, {
      status: j.application_status === 'applied' ? 'new' : 'applied',
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin/batch', bid] }),
  })

  const [manualJob, setManualJob] = useState<Job | null>(null)

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
                <Th className="w-10 text-center">#</Th>
                <Th className="w-[90px]">Status</Th>
                <Th className="w-[70px] text-center">Applied</Th>
                <Th className="w-[170px]">Company</Th>
                <Th>Title</Th>
                <Th className="w-[190px]">Location</Th>
                <Th className="w-[140px]">URL</Th>
                <Th className="w-[110px] text-center">Resume</Th>
                <Th className="w-[50px] text-center">Action</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((j, i) => (
                <AdminRow
                  key={j.id}
                  job={j}
                  index={i + 1}
                  onRetry={() => retry.mutate(j.id)}
                  onApplied={() => toggleApplied.mutate(j)}
                  onNeedsJd={() => setManualJob(j)}
                />
              ))}
              {jobs.length === 0 && (
                <tr><td colSpan={9} className="p-10 text-center text-sm text-gray-400">No jobs yet.</td></tr>
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
  index, job, onRetry, onApplied, onNeedsJd,
}: {
  index: number; job: Job
  onRetry: () => void; onApplied: () => void; onNeedsJd: () => void
}) {
  const isDone = job.status === 'done'
  const needsJd = job.status === 'needs_manual_jd'
  return (
    <tr className="hover:bg-slate-50/80 transition group">
      <td className="px-3 py-2 text-center text-xs text-gray-400 tabular-nums">{index}</td>
      <td className="px-3 py-2"><Chip status={job.status} /></td>
      <td className="px-3 py-2 text-center">
        <input
          type="checkbox"
          checked={job.application_status === 'applied'}
          disabled={!isDone}
          onChange={onApplied}
          className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500 cursor-pointer disabled:cursor-not-allowed disabled:opacity-30"
        />
      </td>
      <td className="px-3 py-2 text-gray-900 truncate" title={job.company || ''}>
        {job.company || <span className="text-gray-300">—</span>}
      </td>
      <td className="px-3 py-2 text-gray-900 truncate" title={job.title || ''}>
        {job.title || <span className="text-gray-300">—</span>}
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
          <a href={`/download/${job.id}/docx`}
             className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded transition shadow-sm"
          ><Download className="w-3 h-3" /> Download</a>
        ) : <span className="text-gray-300 text-xs">—</span>}
      </td>
      <td className="px-3 py-2 text-center">
        {needsJd ? (
          <button onClick={onNeedsJd}
                  className="text-xs font-medium text-amber-700 hover:text-amber-900">Paste JD</button>
        ) : (
          <button onClick={onRetry} title="Retry"
                  className="text-gray-300 hover:text-gray-600 transition">
            <RotateCw className="w-3.5 h-3.5" />
          </button>
        )}
      </td>
    </tr>
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
          <div className="grid grid-cols-3 gap-2">
            <input className="input text-sm" placeholder="Company" value={company} onChange={(e) => setCompany(e.target.value)} />
            <input className="input text-sm" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <input className="input text-sm" placeholder="Location" value={location} onChange={(e) => setLocation(e.target.value)} />
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
