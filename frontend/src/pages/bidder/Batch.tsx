import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, Download, ExternalLink, Target, StickyNote } from 'lucide-react'
import clsx from 'clsx'
import { useState } from 'react'
import { api, type MyBatch, type Job } from '@/lib/api'
import { Empty, Progress } from '@/components/ui'
import { formatDateTime } from '@/lib/format'

export default function MyBatchPage() {
  const { id } = useParams()
  const bid = Number(id)
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['my/batch', bid],
    queryFn: () => api.get<MyBatch>(`/api/my/batches/${bid}`),
    refetchInterval: 10_000,
  })

  const toggle = useMutation({
    mutationFn: (j: Job) => api.post(`/api/batches/${bid}/jobs/${j.id}/app-status`, {
      status: j.application_status === 'applied' ? 'new' : 'applied',
    }),
    onMutate: async (j) => {
      await qc.cancelQueries({ queryKey: ['my/batch', bid] })
      const prev = qc.getQueryData<MyBatch>(['my/batch', bid])
      if (prev) {
        qc.setQueryData<MyBatch>(['my/batch', bid], {
          ...prev,
          jobs: prev.jobs.map((x) => x.id === j.id
            ? { ...x, application_status: x.application_status === 'applied' ? 'new' : 'applied' }
            : x),
          applied: prev.applied + (j.application_status === 'applied' ? -1 : 1),
        })
      }
      return { prev }
    },
    onError: (_err, _j, ctx) => ctx?.prev && qc.setQueryData(['my/batch', bid], ctx.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: ['my/batch', bid] }),
  })

  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>
  const { profile, batch, jobs, applied } = data
  const tailored = jobs.length
  const percent = tailored > 0 ? Math.min(100, Math.round(100 * applied / tailored)) : 0
  const hit = tailored > 0 && applied >= tailored

  return (
    <>
      <Link to={`/my/profiles/${profile.id}`}
            className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition">
        <ChevronLeft className="w-4 h-4" /> {profile.name}
      </Link>

      <div className="flex items-start justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{formatDateTime(batch.created_at)}</h1>
          <p className="text-sm text-gray-400 mt-0.5">{jobs.length} resumes ready</p>
        </div>
        {jobs.length > 0 && (
          <a href={`/download/batch/${bid}/zip`} className="btn-primary">
            <Download className="w-4 h-4" /> Download all ({jobs.length}) .zip
          </a>
        )}
      </div>

      {/* Target progress */}
      <div className="card p-5 mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <div className={clsx('w-9 h-9 rounded-lg grid place-items-center text-white shadow',
              hit ? 'bg-green-600' : 'bg-brand-600')}>
              <Target className="w-4 h-4" />
            </div>
            <div>
              <p className="text-xs text-gray-400 font-medium uppercase tracking-wider">Progress</p>
              <p className="text-sm text-gray-500">Tick the "Done" box after you apply to each job.</p>
            </div>
          </div>
          {hit && (
            <span className="text-sm font-semibold text-green-700 bg-green-50 border border-green-200 rounded-full px-3 py-1">
              🎉 All applied!
            </span>
          )}
        </div>
        <div className="flex items-baseline gap-2 mb-2">
          <span className={clsx('text-4xl font-bold tabular-nums', hit ? 'text-green-600' : 'text-brand-600')}>
            {applied}
          </span>
          <span className="text-lg text-gray-400">/ {tailored} tailored</span>
          <span className="ml-auto text-sm font-medium text-gray-500">{percent}%</span>
        </div>
        <Progress percent={percent} color={hit ? 'green' : 'blue'} />
      </div>

      {jobs.length === 0 ? (
        <Empty>No tailored resumes are ready in this batch yet.</Empty>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm table-fixed">
              <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-10">
                <tr className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                  <Th className="w-10 text-center">#</Th>
                  <Th className="w-16 text-center">Done</Th>
                  <Th className="w-[180px]">Company</Th>
                  <Th>Role</Th>
                  <Th className="w-[200px]">Location</Th>
                  <Th className="w-[90px] text-center">Job</Th>
                  <Th className="w-[120px] text-center">Resume</Th>
                  <Th className="w-[40px]"></Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobs.map((j, i) => (
                  <BidderRow key={j.id} job={j} index={i + 1}
                             onToggle={() => toggle.mutate(j)} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

function Th({ className, children }: { className?: string; children: React.ReactNode }) {
  return <th className={clsx('px-3 py-2.5 font-semibold', className)}>{children}</th>
}

function BidderRow({ job, index, onToggle }: { job: Job; index: number; onToggle: () => void }) {
  const [showNote, setShowNote] = useState(false)
  const isApplied = job.application_status === 'applied'
  return (
    <>
      <tr className={clsx(
        'hover:bg-slate-50 transition',
        isApplied && 'bg-green-50/40',
      )}>
        <td className="px-3 py-2 text-center text-xs text-gray-400 tabular-nums">{index}</td>
        <td className="px-3 py-2 text-center">
          <input
            type="checkbox"
            checked={isApplied}
            onChange={onToggle}
            title="Tick after you apply"
            className="w-5 h-5 rounded border-2 border-gray-300 text-brand-600 focus:ring-brand-500 cursor-pointer"
          />
        </td>
        <td className={clsx('px-3 py-2 font-medium truncate',
          isApplied ? 'text-gray-500 line-through decoration-gray-300' : 'text-gray-900')}
          title={job.company || ''}>
          {job.company || <span className="text-gray-300">—</span>}
        </td>
        <td className={clsx('px-3 py-2 truncate',
          isApplied ? 'text-gray-500 line-through decoration-gray-300' : 'text-gray-900')}
          title={job.title || ''}>
          {job.title || <span className="text-gray-300">—</span>}
        </td>
        <td className="px-3 py-2 text-gray-500 text-xs break-words" title={job.location || ''}>
          {job.location || <span className="text-gray-300">—</span>}
        </td>
        <td className="px-3 py-2 text-center">
          <a href={job.url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 hover:border-gray-400 rounded transition">
            <ExternalLink className="w-3 h-3" /> Open
          </a>
        </td>
        <td className="px-3 py-2 text-center">
          {job.has_docx ? (
            <a href={`/download/${job.id}/docx`}
               className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded transition shadow-sm"
            ><Download className="w-3 h-3" /> Download</a>
          ) : <span className="text-gray-300 text-xs">—</span>}
        </td>
        <td className="px-3 py-2 text-center">
          <button
            onClick={() => setShowNote(!showNote)}
            className={clsx('transition', job.application_note ? 'text-brand-500' : 'text-gray-300 hover:text-gray-500')}
            title={job.application_note || 'Add note'}
          >
            <StickyNote className="w-3.5 h-3.5" />
          </button>
        </td>
      </tr>
      {showNote && (
        <tr className="bg-slate-50/60">
          <td colSpan={8} className="px-3 py-2">
            <NoteEditor job={job} onDone={() => setShowNote(false)} />
          </td>
        </tr>
      )}
    </>
  )
}

function NoteEditor({ job, onDone }: { job: Job; onDone: () => void }) {
  const qc = useQueryClient()
  const [note, setNote] = useState(job.application_note || '')
  const save = useMutation({
    mutationFn: () => api.post(`/api/batches/${job.id > 0 ? '' : ''}${/* ignore */''}` + '', {}),
  })
  // The app-status endpoint accepts a note alongside status; reuse it.
  const saveNote = useMutation({
    mutationFn: () => {
      // We need the batch id. job doesn't have it directly, but parent route has it.
      // We'll read from URL.
      const m = window.location.pathname.match(/\/batches\/(\d+)/)
      const bid = m ? Number(m[1]) : 0
      return api.post(`/api/batches/${bid}/jobs/${job.id}/app-status`, {
        status: job.application_status, note,
      })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['my/batch'] }); onDone() },
  })
  void save
  return (
    <div className="flex items-center gap-2">
      <input
        value={note} onChange={(e) => setNote(e.target.value)}
        placeholder="Add a note (e.g. source, recruiter name…)"
        className="input text-sm flex-1"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter') saveNote.mutate()
          if (e.key === 'Escape') onDone()
        }}
      />
      <button onClick={() => saveNote.mutate()} disabled={saveNote.isPending}
              className="btn-primary text-xs py-1.5 px-3">Save</button>
      <button onClick={onDone} className="btn-secondary text-xs py-1.5 px-3">Cancel</button>
    </div>
  )
}
