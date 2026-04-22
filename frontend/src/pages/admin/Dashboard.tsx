import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type AdminDashboard, type ProfileStatus } from '@/lib/api'
import { Alert } from '@/components/ui'
import { RingChart, Sparkline, StatusStack } from '@/components/charts'
import { formatLongDate, formatTime } from '@/lib/format'
import {
  ArrowRight, Target, CheckCircle2, TrendingUp, Flame,
  Plus, Upload, AlertCircle,
} from 'lucide-react'
import clsx from 'clsx'

export default function Dashboard() {
  const qc = useQueryClient()
  const nav = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['admin/dashboard'],
    queryFn: () => api.get<AdminDashboard>('/api/admin/dashboard'),
    refetchInterval: 5000,
  })

  const [startForProfile, setStartForProfile] = useState<number | null>(null)
  const [urls, setUrls] = useState('')

  const create = useMutation({
    mutationFn: (pid: number) => api.post<{ batch_id: number | null; added: number; skipped_done: number; skipped_dupe: number; message?: string }>(
      '/api/admin/batches', { profile_id: pid, urls }),
    onSuccess: (res) => {
      setUrls('')
      setStartForProfile(null)
      if (res.batch_id) {
        nav(`/admin/batches/${res.batch_id}`)
      } else {
        qc.invalidateQueries({ queryKey: ['admin/dashboard'] })
      }
    },
  })

  if (isLoading || !data) return <div className="text-center text-gray-400 text-sm">Loading…</div>

  const { agg, profile_statuses, agg_trend, trend_dates } = data
  const allApplied = agg.done > 0 && agg.applied >= agg.done

  return (
    <>
      <div className="flex items-end justify-between mb-6">
        <div>
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
            {formatLongDate(data.now_pst)} · US Pacific
          </p>
          <h1 className="text-2xl font-bold text-gray-900">Today</h1>
        </div>
        <Link to="/admin/calendar" className="btn-secondary text-sm">
          All days <ArrowRight className="w-4 h-4" />
        </Link>
      </div>

      {/* ── Overview ──────────────────────────────────────────────── */}
      {profile_statuses.length > 0 ? (
        <div className="card p-6 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr_auto] gap-6 items-center">
            <div className="flex items-center justify-center">
              <RingChart value={agg.applied} target={agg.done} size={140} stroke={14}
                         label={`${agg.applied} / ${agg.done}`} />
            </div>

            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <div className="w-8 h-8 rounded-lg grid place-items-center text-white shadow"
                     style={{ background: 'linear-gradient(135deg,#6366f1,#4f46e5)' }}>
                  <Target className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-xs text-gray-400 font-medium uppercase tracking-wider">Today's progress</p>
                  <p className="text-lg font-bold text-gray-900">
                    {agg.applied} applied
                    <span className="text-sm text-gray-400 font-normal ml-1">of {agg.done} tailored</span>
                  </p>
                </div>
              </div>

              <div className="mt-4">
                <div className="flex items-center justify-between text-[11px] text-gray-400 mb-1">
                  <span className="uppercase tracking-wider font-semibold flex items-center gap-1">
                    <TrendingUp className="w-3 h-3" /> Last 7 days (all profiles)
                  </span>
                  <span className="tabular-nums font-medium">{agg_trend.reduce((a, b) => a + b, 0)} total</span>
                </div>
                <Sparkline data={agg_trend} dates={trend_dates} highlight={agg_trend.length - 1} height={44} color="#6366f1" />
                <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                  {trend_dates.map((d, i) => (
                    <span key={d} className={clsx(i === trend_dates.length - 1 && 'font-semibold text-brand-600')}>
                      {new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' })[0]}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="min-w-[180px]">
              <p className="text-[11px] text-gray-400 uppercase tracking-wider font-semibold mb-2">Today's pipeline</p>
              <StatusStack
                total={agg.total}
                segments={[
                  { value: agg.applied,   color: '#4f46e5', label: 'Applied' },
                  { value: agg.done - agg.applied, color: '#22c55e', label: 'Tailored' },
                  { value: agg.needs_jd,  color: '#f59e0b', label: 'Needs JD' },
                ]}
              />
              <ul className="mt-3 space-y-1.5 text-xs">
                <Legend swatch="#4f46e5" label="Applied" value={agg.applied} />
                <Legend swatch="#22c55e" label="Tailored" value={Math.max(0, agg.done - agg.applied)} />
                <Legend swatch="#f59e0b" label="Needs JD" value={agg.needs_jd} />
              </ul>
            </div>
          </div>

          {allApplied && (
            <div className="mt-4 flex items-center gap-2 text-sm font-semibold text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-2">
              <CheckCircle2 className="w-4 h-4" /> All tailored resumes applied across every profile
            </div>
          )}
        </div>
      ) : (
        <div className="card p-8 text-center mb-6">
          <Target className="w-10 h-10 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500 mb-3">No profiles yet.</p>
          <Link to="/admin/profiles" className="btn-primary text-sm">Create one</Link>
        </div>
      )}

      {/* ── Per-profile status cards (all profiles, always) ───────── */}
      {profile_statuses.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
            Profiles <span className="text-gray-400 normal-case font-normal">({profile_statuses.length})</span>
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
            {profile_statuses.map((ps) => (
              <ProfileCard
                key={ps.profile.id}
                status={ps}
                trendDates={trend_dates}
                onStart={() => setStartForProfile(ps.profile.id)}
              />
            ))}
          </div>
        </>
      )}

      {/* ── Start a batch (modal) ─────────────────────────────────── */}
      {startForProfile !== null && (
        <StartBatchDialog
          profile={profile_statuses.find((x) => x.profile.id === startForProfile)!.profile}
          urls={urls}
          setUrls={setUrls}
          onClose={() => { setStartForProfile(null); setUrls('') }}
          onSubmit={() => create.mutate(startForProfile)}
          pending={create.isPending}
          error={create.isError ? (create.error as Error).message : null}
        />
      )}
    </>
  )
}

function Legend({ swatch, label, value }: { swatch: string; label: string; value: number }) {
  if (value === 0) return (
    <li className="flex items-center justify-between text-gray-300">
      <span className="flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-sm" style={{ background: swatch, opacity: 0.3 }} />
        {label}
      </span>
      <span className="tabular-nums">0</span>
    </li>
  )
  return (
    <li className="flex items-center justify-between">
      <span className="flex items-center gap-1.5 text-gray-600">
        <span className="w-2 h-2 rounded-sm" style={{ background: swatch }} />
        {label}
      </span>
      <span className="tabular-nums font-semibold text-gray-900">{value}</span>
    </li>
  )
}

function ProfileCard({
  status, trendDates, onStart,
}: {
  status: ProfileStatus
  trendDates: string[]
  onStart: () => void
}) {
  const { profile, summary, trend, today_batch } = status
  const target = summary.done  // "target" = tailored count
  const hit = target > 0 && summary.applied >= target
  const hasTodayBatch = today_batch !== null
  const weekTotal = trend.reduce((a, b) => a + b, 0)

  // If there's a batch today → click card to open it
  // Otherwise → card is static but has a Start button
  const CardWrapper = ({ children }: { children: React.ReactNode }) =>
    hasTodayBatch ? (
      <Link to={`/admin/batches/${today_batch!.id}`} className="card card-hover block p-5">
        {children}
      </Link>
    ) : (
      <div className="card p-5">{children}</div>
    )

  return (
    <CardWrapper>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-gray-900 truncate">{profile.name}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {hasTodayBatch
              ? <>Started {formatTime(today_batch!.created_at)} PT · batch #{today_batch!.id}</>
              : <span className="text-amber-600 font-medium">No batch today yet</span>
            }
          </p>
          {hit && (
            <span className="inline-flex items-center gap-1 mt-2 text-xs font-semibold text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
              <CheckCircle2 className="w-3 h-3" /> All applied
            </span>
          )}
        </div>
        <RingChart value={summary.applied} target={target} size={90} stroke={9} />
      </div>

      {/* Big numbers */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold">Applied</p>
          <p className={clsx('text-2xl font-bold tabular-nums',
            hit ? 'text-green-600' : hasTodayBatch ? 'text-brand-600' : 'text-gray-300')}>
            {summary.applied}
            <span className="text-sm text-gray-400 font-medium"> / {summary.done} tailored</span>
          </p>
        </div>
        <div>
          <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold">Queue</p>
          <p className={clsx('text-2xl font-bold tabular-nums',
            hasTodayBatch ? 'text-gray-900' : 'text-gray-300')}>
            {summary.done}
            <span className="text-sm text-gray-400 font-medium"> / {summary.total}</span>
          </p>
        </div>
      </div>

      {/* Sparkline */}
      <div className="mb-3">
        <div className="flex items-center justify-between text-[10px] text-gray-400 mb-1">
          <span className="uppercase tracking-wider font-semibold flex items-center gap-1">
            <Flame className="w-3 h-3" /> 7-day applied
          </span>
          <span className="tabular-nums font-medium text-gray-500">{weekTotal} total</span>
        </div>
        <Sparkline
          data={trend} dates={trendDates}
          highlight={trend.length - 1}
          color={hit ? '#16a34a' : '#6366f1'}
          height={32}
        />
      </div>

      {hasTodayBatch && (
        <>
          <StatusStack
            total={summary.total}
            height={6}
            segments={[
              { value: summary.applied, color: '#4f46e5', label: 'Applied' },
              { value: summary.done - summary.applied, color: '#22c55e', label: 'Tailored' },
              { value: summary.needs_jd,  color: '#f59e0b', label: 'Needs JD' },
            ]}
          />
          {summary.needs_jd > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              <span className="chip chip-needs_manual_jd">{summary.needs_jd} need JD</span>
            </div>
          )}
        </>
      )}

      {/* Always show a batch action button — new batch or add more URLs. */}
      <div className={clsx('flex gap-2', hasTodayBatch && 'mt-4')}>
        {profile.has_base_resume ? (
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onStart() }}
            className="btn-primary flex-1 text-sm"
          >
            <Plus className="w-4 h-4" />
            {hasTodayBatch ? "Add more URLs" : "Start today's batch"}
          </button>
        ) : (
          <Link
            to={`/admin/profiles/${profile.id}`}
            onClick={(e) => e.stopPropagation()}
            className="btn-secondary flex-1 text-sm"
          >
            <Upload className="w-4 h-4" /> Upload base resume to start
          </Link>
        )}
        {hasTodayBatch && (
          <Link
            to={`/admin/batches/${today_batch!.id}`}
            onClick={(e) => e.stopPropagation()}
            className="btn-secondary text-sm"
          >
            Open
          </Link>
        )}
      </div>
    </CardWrapper>
  )
}

function StartBatchDialog({
  profile, urls, setUrls, onClose, onSubmit, pending, error,
}: {
  profile: { id: number; name: string; has_base_resume: boolean }
  urls: string; setUrls: (s: string) => void
  onClose: () => void; onSubmit: () => void
  pending: boolean; error: string | null
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="font-semibold text-gray-900 text-lg">Start batch</h3>
            <p className="text-sm text-gray-500"><span className="font-medium text-gray-700">{profile.name}</span></p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>

        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (urls.trim()) onSubmit() }}>
          <div>
            <label className="label">Job URLs <span className="text-gray-400 font-normal">(one per line)</span></label>
            <textarea rows={10} required autoFocus className="input font-mono resize-y"
                      placeholder="https://…&#10;https://…&#10;https://…"
                      value={urls} onChange={(e) => setUrls(e.target.value)} />
          </div>
          {error && <Alert variant="error"><div className="flex items-center gap-1.5"><AlertCircle className="w-4 h-4" /> {error}</div></Alert>}
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-secondary text-sm">Cancel</button>
            <button disabled={pending || !urls.trim()} className="btn-primary text-sm">
              {pending ? 'Starting…' : 'Start batch'}
            </button>
          </div>
          <p className="text-xs text-gray-400">URLs already tailored for this profile will be skipped.</p>
        </form>
      </div>
    </div>
  )
}

