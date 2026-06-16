import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type AdminDashboard, type ProfileStatus, FAIL_REASON } from '@/lib/api'
import { Alert } from '@/components/ui'
import { Avatar, MiniDonut, StatTile, WeekHeatmap, paletteForName } from '@/components/charts'
import { formatLongDate } from '@/lib/format'
import {
  ArrowRight, Target, CheckCircle2, Sparkles, TrendingUp,
  Plus, Upload, Download, Copy, AlertCircle, Lock,
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
  const [showUrlsDialog, setShowUrlsDialog] = useState(false)

  interface PasteResult {
    batch_id: number | null
    added: number
    skipped_done: number
    skipped_dupe: number
    skipped_existing?: number
    message?: string
    duplicates?: Array<{
      url: string
      job_id: number
      batch_id: number
      status: string
      application_status: string
      applied_at: string | null
      days_since_applied: number | null
      apply_count: number
      company: string | null
      title: string | null
    }>
  }
  const [pasteResult, setPasteResult] = useState<PasteResult | null>(null)
  const create = useMutation({
    mutationFn: (pid: number) => api.post<PasteResult>(
      '/api/admin/batches', { profile_id: pid, urls }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['admin/dashboard'] })
      const hasDups = (res.duplicates || []).length > 0
      if (hasDups) {
        // Show the duplicate report instead of just navigating away.
        setPasteResult(res)
        return
      }
      setUrls('')
      setStartForProfile(null)
      if (res.batch_id) nav(`/admin/batches/${res.batch_id}`)
    },
  })

  // Profile filter — selected IDs are persisted in localStorage so reloads
  // keep your current focus. Empty set = no filter (show all).
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => {
    try {
      const raw = localStorage.getItem('dashboard.selectedProfileIds')
      return raw ? new Set(JSON.parse(raw)) : new Set()
    } catch { return new Set() }
  })
  useEffect(() => {
    try {
      localStorage.setItem('dashboard.selectedProfileIds',
        JSON.stringify([...selectedIds]))
    } catch {}
  }, [selectedIds])

  // Compute filtered view (profile rows + aggregate stats + trend).
  const filtered = useMemo(() => {
    if (!data) return null
    const all = data.profile_statuses
    const visible = selectedIds.size === 0 ? all : all.filter((p) => selectedIds.has(p.profile.id))
    // Re-aggregate from the visible subset so the top tiles match the filter.
    const sum = (key: 'total' | 'done' | 'applied' | 'in_flight' | 'needs_jd' | 'errors') =>
      visible.reduce((acc, p) => acc + (p.summary[key] || 0), 0)
    const t = sum('total')
    const d = sum('done')
    const a = sum('applied')
    const aggFiltered = {
      total: t, done: d, applied: a,
      in_flight: sum('in_flight'), needs_jd: sum('needs_jd'), errors: sum('errors'),
      percent: t ? Math.round(100 * d / t) : 0,
      applied_percent: d ? Math.round(100 * a / d) : 0,
    }
    const trend = new Array(7).fill(0)
    for (const ps of visible) ps.trend.forEach((v, i) => { trend[i] += v })
    // Today's jobs filtered by the active profile selection.
    const visibleIds = new Set(visible.map((p) => p.profile.id))
    const today_jobs = (data.today_jobs || []).filter((r) => visibleIds.has(r.profile_id))
    return { visible, agg: aggFiltered, agg_trend: trend, today_jobs }
  }, [data, selectedIds])

  if (isLoading || !data || !filtered) return <div className="text-center text-gray-400 text-sm">Loading…</div>

  const { profile_statuses, trend_dates } = data
  const agg = filtered.agg
  const agg_trend = filtered.agg_trend
  const allApplied = agg.done > 0 && agg.applied >= agg.done

  return (
    <>
      <div className="flex items-end justify-between mb-4 flex-wrap gap-3">
        <div>
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
            {formatLongDate(data.now_pst)} · US Pacific
          </p>
          <h1 className="text-2xl font-bold text-gray-900">Today</h1>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowUrlsDialog(true)} className="btn-secondary text-sm" title="Copy all of today's job URLs to paste into another instance">
            <Copy className="w-4 h-4" /> Copy URLs
          </button>
          <a href={`/download/resumes/zip?date=${data.today}`} className="btn-secondary text-sm" title="Download every tailored resume from today as a zip">
            <Download className="w-4 h-4" /> Today’s resumes
          </a>
          <a href="/download/resumes/zip" className="btn-secondary text-sm" title="Download every tailored resume (full archive) as a zip">
            <Download className="w-4 h-4" /> All
          </a>
          <Link to="/admin/calendar" className="btn-secondary text-sm">
            All days <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>

      {/* ── Profile filter chips ──────────────────────────────────── */}
      {profile_statuses.length > 1 && (
        <ProfileFilter
          profiles={profile_statuses.map((p) => p.profile)}
          selected={selectedIds}
          setSelected={setSelectedIds}
        />
      )}

      {/* ── Colorful gradient stat tiles + heatmap ────────────────── */}
      {profile_statuses.length > 0 ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <StatTile
              label="Applied today"
              value={`${agg.applied} / ${agg.done}`}
              sublabel={agg.done > 0 ? `${Math.round(100 * agg.applied / agg.done)}% submitted` : 'No tailored yet'}
              tone={allApplied ? 'emerald' : 'brand'}
              icon={<Target className="w-16 h-16" />}
            />
            <StatTile
              label="Tailored today"
              value={`${agg.done} / ${agg.total}`}
              sublabel={agg.in_flight > 0 ? `${agg.in_flight} in progress` : 'Queue clear'}
              tone="emerald"
              icon={<Sparkles className="w-16 h-16" />}
            />
            <StatTile
              label="7-day applied"
              value={agg_trend.reduce((a, b) => a + b, 0).toLocaleString()}
              sublabel={selectedIds.size === 0
                ? `Across all ${profile_statuses.length} profiles`
                : `Across ${filtered.visible.length} of ${profile_statuses.length} profiles`}
              tone="amber"
              icon={<TrendingUp className="w-16 h-16" />}
            />
          </div>

          <div className="card px-4 py-3 mb-6 flex items-center gap-4 flex-wrap">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 mr-1">7-day overall</p>
            <div className="flex flex-col items-start gap-1">
              <WeekHeatmap data={agg_trend} dates={trend_dates} color="indigo" size={22} gap={4} />
              <div className="flex gap-[7px] mt-0.5">
                {trend_dates.map((d, i) => (
                  <span key={d}
                    className={clsx('text-[10px] w-[22px] text-center',
                      i === trend_dates.length - 1 ? 'font-bold text-brand-600' : 'text-gray-400')}>
                    {new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' })[0]}
                  </span>
                ))}
              </div>
            </div>
            <div className="ml-auto flex items-center gap-1 flex-wrap">
              {agg.in_flight > 0 && <span className="chip chip-tailoring">{agg.in_flight} in flight</span>}
              {agg.needs_jd  > 0 && <span className="chip chip-needs_manual_jd">{agg.needs_jd} need JD</span>}
              {agg.errors    > 0 && <span className="chip chip-error">{agg.errors} errors</span>}
            </div>
          </div>

          {allApplied && (
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-2">
              <CheckCircle2 className="w-4 h-4" /> All tailored resumes applied across every profile
            </div>
          )}
        </>
      ) : (
        <div className="card p-8 text-center mb-6">
          <Target className="w-10 h-10 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500 mb-3">No profiles yet.</p>
          <Link to="/admin/profiles" className="btn-primary text-sm">Create one</Link>
        </div>
      )}

      {/* ── Today's per-profile cards ─────────────────────────────── */}
      {profile_statuses.length > 0 && (
        <>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-2">
            Today
            <span className="text-gray-400 normal-case font-normal">
              · {selectedIds.size === 0 ? `all ${profile_statuses.length} profiles` : `${filtered.visible.length} selected`}
            </span>
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
            {filtered.visible.map((ps) => (
              <TodayCard
                key={ps.profile.id}
                status={ps}
                onStart={() => setStartForProfile(ps.profile.id)}
              />
            ))}
            {filtered.visible.length === 0 && (
              <div className="card p-6 text-center text-sm text-gray-400 border-dashed col-span-full">
                No profiles selected.
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Jobs needing attention (fetch/JD failures) ────────────── */}
      {profile_statuses.length > 0 && (
        <NeedsAttentionPanel jobs={filtered.today_jobs} />
      )}

      {/* ── Resume upload verification ────────────────────────────── */}
      {profile_statuses.length > 0 && (
        <UploadVerificationPanel jobs={filtered.today_jobs} />
      )}

      {/* ── This week's work per profile (one consolidated table) ──── */}
      {profile_statuses.length > 0 && (
        <>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-2">
            This week
            <span className="text-gray-400 normal-case font-normal">
              · {selectedIds.size === 0 ? 'all profiles' : `${filtered.visible.length} selected`} · last 7 days
            </span>
          </h2>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
                  <Th>Profile</Th>
                  <Th className="w-[110px] text-right">Applied</Th>
                  <Th className="w-[110px] text-right">Tailored</Th>
                  <Th className="w-[80px] text-right">Total</Th>
                  <Th className="w-[180px]">7-day applied</Th>
                  <Th className="w-[180px]">Issues</Th>
                  <Th className="w-[120px] text-right">Action</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.visible.map((ps) => (
                  <WeekRow
                    key={ps.profile.id}
                    status={ps}
                    trendDates={trend_dates}
                    onStart={() => setStartForProfile(ps.profile.id)}
                  />
                ))}
                {filtered.visible.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-sm text-gray-400">
                      No profiles selected. Click chips above to choose which to display.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* ── Start a batch (modal) ─────────────────────────────────── */}
      {startForProfile !== null && !pasteResult && (
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
      {pasteResult && (
        <DuplicatesDialog
          result={pasteResult}
          onClose={() => {
            // Either jump to the new batch (if anything was added) or stay
            // on the dashboard.
            const bid = pasteResult.batch_id
            setPasteResult(null)
            setStartForProfile(null)
            setUrls('')
            if (bid) nav(`/admin/batches/${bid}`)
          }}
        />
      )}
      {showUrlsDialog && (
        <TodayUrlsDialog
          jobs={filtered.today_jobs}
          onClose={() => setShowUrlsDialog(false)}
        />
      )}
    </>
  )
}


function TodayUrlsDialog({ jobs, onClose }: { jobs: AdminDashboard['today_jobs']; onClose: () => void }) {
  // Group today's URLs by batch (one batch per profile), deduped within each.
  const groups = useMemo(() => {
    const m = new Map<number, { profile: string; urls: string[] }>()
    for (const j of jobs) {
      if (!j.url) continue
      const g = m.get(j.batch_id) ?? { profile: j.profile_name, urls: [] }
      if (!g.urls.includes(j.url)) g.urls.push(j.url)
      m.set(j.batch_id, g)
    }
    return Array.from(m.entries())
      .map(([batch_id, g]) => ({ batch_id, ...g }))
      .sort((a, b) => a.profile.localeCompare(b.profile))
  }, [jobs])
  const total = groups.reduce((n, g) => n + g.urls.length, 0)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 2000)
    } catch {
      const ta = document.getElementById(`urls-${key}`) as HTMLTextAreaElement | null
      ta?.select()
    }
  }
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={onClose}>
      <div className="card w-full max-w-xl p-5 max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-semibold text-gray-900 text-lg">Today’s URLs by batch</h3>
            <p className="text-xs text-gray-500 mt-0.5">{groups.length} batch{groups.length === 1 ? '' : 'es'} · {total} URL{total === 1 ? '' : 's'} — copy a batch and paste into another instance’s “New batch” box.</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none ml-3">✕</button>
        </div>

        <div className="overflow-y-auto space-y-4 pr-1">
          {groups.length === 0 && <p className="text-sm text-gray-400 text-center py-6">No URLs added today.</p>}
          {groups.map((g) => {
            const key = String(g.batch_id)
            const text = g.urls.join('\n')
            return (
              <div key={g.batch_id}>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-sm font-semibold text-gray-900">
                    {g.profile} <span className="font-normal text-gray-500">· {g.urls.length} URL{g.urls.length === 1 ? '' : 's'}</span>
                  </p>
                  <button onClick={() => copy(key, text)} className="btn-secondary text-xs py-1 px-2.5">
                    {copiedKey === key ? '✓ Copied' : 'Copy'}
                  </button>
                </div>
                <textarea
                  id={`urls-${key}`}
                  readOnly
                  value={text}
                  onFocus={(e) => e.currentTarget.select()}
                  className="w-full h-28 text-xs font-mono border border-slate-200 rounded-md p-2 bg-slate-50 resize-none"
                />
              </div>
            )
          })}
        </div>

        <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-slate-100">
          <button onClick={onClose} className="btn-secondary text-sm">Close</button>
          <button
            onClick={() => copy('all', groups.map((g) => `# ${g.profile}\n${g.urls.join('\n')}`).join('\n\n'))}
            disabled={!total}
            className="btn-primary text-sm"
          >
            {copiedKey === 'all' ? '✓ Copied' : 'Copy all'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Th({ className, children }: { className?: string; children: React.ReactNode }) {
  return <th className={clsx('px-3 py-2 font-semibold', className)}>{children}</th>
}


function TodayCard({
  status, onStart,
}: {
  status: ProfileStatus
  onStart: () => void
}) {
  const { profile, summary, today_batch } = status
  const canAccess = profile.can_access !== false
  const hit = summary.done > 0 && summary.applied >= summary.done
  const hasTodayBatch = today_batch !== null
  const pct = summary.done > 0 ? Math.round((summary.applied / summary.done) * 100) : 0

  const Wrapper = ({ children }: { children: React.ReactNode }) =>
    hasTodayBatch && canAccess ? (
      <Link to={`/admin/batches/${today_batch!.id}`} className="card card-hover block p-3.5">{children}</Link>
    ) : (
      <div className={clsx('card p-3.5', !canAccess && 'opacity-70')}>{children}</div>
    )

  return (
    <Wrapper>
      {/* Avatar + name + done badge */}
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <Avatar name={profile.name} size={32} />
          <p className="font-semibold text-gray-900 truncate text-sm">{profile.name}</p>
          {!canAccess && <Lock className="w-3 h-3 text-gray-400 shrink-0" />}
        </div>
        {hit && <CheckCircle2 className="w-4 h-4 text-green-600 flex-shrink-0" />}
      </div>

      {/* Today's applied / tailored */}
      <div className="flex items-baseline gap-1.5 mb-2">
        <span className={clsx('text-2xl font-bold tabular-nums leading-none',
          hit ? 'text-green-600' : hasTodayBatch ? 'text-brand-600' : 'text-gray-300')}>
          {summary.applied}
        </span>
        <span className="text-xs text-gray-400">/ {summary.done} tailored</span>
        {summary.done > 0 && (
          <span className="ml-auto text-xs text-gray-500 tabular-nums">{pct}%</span>
        )}
      </div>

      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mb-2.5">
        <div
          className={clsx('h-full rounded-full transition-all',
            hit ? 'bg-green-500' : 'bg-brand-500')}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Today's batch + queue size */}
      <p className="text-[11px] text-gray-400 mb-2.5 truncate">
        {hasTodayBatch
          ? <>Batch #{today_batch!.id} · {summary.done}/{summary.total} done</>
          : <span className="text-amber-600 font-medium">No batch today yet</span>
        }
      </p>

      {/* Status chips */}
      {hasTodayBatch && (summary.in_flight + summary.needs_jd + summary.errors > 0) && (
        <div className="flex flex-wrap gap-1 mb-2.5">
          {summary.in_flight > 0 && <span className="chip chip-tailoring">{summary.in_flight} in flight</span>}
          {summary.needs_jd  > 0 && <span className="chip chip-needs_manual_jd">{summary.needs_jd} need JD</span>}
          {summary.errors    > 0 && <span className="chip chip-error">{summary.errors} errors</span>}
        </div>
      )}

      {!canAccess ? (
        <p className="text-[11px] text-gray-400 text-center py-1.5">View only — not assigned to you</p>
      ) : profile.has_base_resume ? (
        <button
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); onStart() }}
          className="btn-primary w-full text-xs py-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          {hasTodayBatch ? 'Add URLs' : "Start today's batch"}
        </button>
      ) : (
        <Link
          to={`/admin/profiles/${profile.id}`}
          onClick={(e) => e.stopPropagation()}
          className="btn-secondary w-full text-xs py-1.5"
        >
          <Upload className="w-3.5 h-3.5" /> Upload base resume
        </Link>
      )}
    </Wrapper>
  )
}


function ProfileFilter({
  profiles, selected, setSelected,
}: {
  profiles: { id: number; name: string }[]
  selected: Set<number>
  setSelected: (s: Set<number>) => void
}) {
  const showingAll = selected.size === 0
  const toggle = (id: number) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }
  return (
    <div className="card px-3 py-2 mb-4 flex items-center gap-2 flex-wrap">
      <p className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 mr-1">Show</p>
      <button
        onClick={() => setSelected(new Set())}
        className={clsx(
          'text-xs font-medium px-2.5 py-1 rounded-full border transition',
          showingAll
            ? 'bg-brand-600 text-white border-brand-600 shadow-sm'
            : 'bg-white text-gray-600 border-gray-200 hover:bg-slate-50',
        )}
      >
        All
      </button>
      {profiles.map((p) => {
        const isOn = !showingAll && selected.has(p.id)
        return (
          <button
            key={p.id}
            onClick={() => toggle(p.id)}
            title={p.name}
            className={clsx(
              'inline-flex items-center gap-1.5 text-xs font-medium pl-1 pr-2.5 py-1 rounded-full border transition',
              isOn
                ? 'bg-brand-50 text-brand-800 border-brand-300 shadow-sm'
                : showingAll
                  ? 'bg-white text-gray-600 border-gray-200 hover:bg-slate-50'
                  : 'bg-white text-gray-400 border-gray-200 hover:bg-slate-50 opacity-70',
            )}
          >
            <Avatar name={p.name} size={18} />
            <span className="truncate max-w-[120px]">{p.name}</span>
          </button>
        )
      })}
    </div>
  )
}


function WeekRow({
  status, trendDates, onStart,
}: {
  status: ProfileStatus
  trendDates: string[]
  onStart: () => void
}) {
  const { profile, week, trend, today_batch } = status
  const canAccess = profile.can_access !== false
  const hit = week.done > 0 && week.applied >= week.done
  const appliedPct = week.done > 0 ? Math.round((week.applied / week.done) * 100) : 0
  const tailoredPct = week.total > 0 ? Math.round((week.done / week.total) * 100) : 0
  const palette = paletteForName(profile.name)
  const paletteHex: Record<string, string> = {
    indigo: '#6366f1', emerald: '#10b981', amber: '#f59e0b',
    rose: '#f43f5e', violet: '#8b5cf6', sky: '#0ea5e9', fuchsia: '#d946ef',
  }
  const donutColor = hit ? '#10b981' : paletteHex[palette]

  return (
    <tr className="hover:bg-slate-50/60 transition">
      {/* profile: avatar + name + batch link */}
      <td className="px-3 py-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <Avatar name={profile.name} size={36} />
          <div className="min-w-0">
            {canAccess ? (
              <Link to={`/admin/profiles/${profile.id}`}
                    className="font-semibold text-gray-900 hover:text-brand-700 truncate block">
                {profile.name}
              </Link>
            ) : (
              <span className="font-semibold text-gray-900 truncate flex items-center gap-1">
                {profile.name} <Lock className="w-3 h-3 text-gray-400" />
              </span>
            )}
            {today_batch && canAccess ? (
              <Link to={`/admin/batches/${today_batch.id}`}
                    className="text-[11px] text-gray-400 hover:text-brand-700 truncate block">
                today: batch #{today_batch.id} →
              </Link>
            ) : today_batch ? (
              <p className="text-[11px] text-gray-400 truncate">today: batch #{today_batch.id}</p>
            ) : !profile.has_base_resume ? (
              <p className="text-[11px] text-amber-600 truncate">No base resume</p>
            ) : (
              <p className="text-[11px] text-gray-400 truncate">No batch today</p>
            )}
          </div>
        </div>
      </td>

      {/* applied: donut + numerator/denominator */}
      <td className="px-3 py-3">
        <div className="flex items-center gap-2.5 justify-end">
          <div className="text-right leading-tight">
            <p className={clsx('font-bold tabular-nums text-lg',
              hit ? 'text-emerald-600' : week.applied > 0 ? 'text-brand-600' : 'text-gray-300')}>
              {week.applied}
            </p>
            <p className="text-[10px] text-gray-400 tabular-nums">of {week.done}</p>
          </div>
          <MiniDonut pct={appliedPct} color={donutColor} size={40} stroke={5} label={`${appliedPct}%`} />
        </div>
      </td>

      {/* tailored: donut + ratio */}
      <td className="px-3 py-3">
        <div className="flex items-center gap-2.5 justify-end">
          <div className="text-right leading-tight">
            <p className="font-semibold tabular-nums text-gray-800">{week.done}</p>
            <p className="text-[10px] text-gray-400 tabular-nums">of {week.total}</p>
          </div>
          <MiniDonut pct={tailoredPct} color="#10b981" trackColor="#d1fae5" size={36} stroke={4} label={`${tailoredPct}%`} />
        </div>
      </td>

      {/* total */}
      <td className="px-3 py-3 text-right text-gray-700 tabular-nums font-medium">{week.total}</td>

      {/* heatmap, profile-tinted */}
      <td className="px-3 py-3">
        <div className="flex flex-col items-start gap-0.5">
          <WeekHeatmap data={trend} dates={trendDates} color={palette} size={18} gap={3} />
          <div className="flex gap-[5px]">
            {trendDates.map((d, i) => (
              <span key={d}
                className={clsx('text-[9px] w-[18px] text-center',
                  i === trendDates.length - 1 ? 'font-bold text-gray-700' : 'text-gray-300')}>
                {new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' })[0]}
              </span>
            ))}
          </div>
        </div>
      </td>

      {/* issues */}
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-1">
          {hit && <span className="chip chip-done">all applied</span>}
          {week.in_flight > 0 && <span className="chip chip-tailoring">{week.in_flight} in flight</span>}
          {week.needs_jd  > 0 && <span className="chip chip-needs_manual_jd">{week.needs_jd} need JD</span>}
          {week.errors    > 0 && <span className="chip chip-error">{week.errors} errors</span>}
          {!hit && week.in_flight === 0 && week.needs_jd === 0 && week.errors === 0 && (
            <span className="text-xs text-gray-300">—</span>
          )}
        </div>
      </td>

      {/* action */}
      <td className="px-3 py-3 text-right">
        {!canAccess ? (
          <span className="text-[11px] text-gray-300">view only</span>
        ) : profile.has_base_resume ? (
          <button onClick={onStart} className="btn-primary text-xs py-1.5 px-2.5 whitespace-nowrap">
            <Plus className="w-3.5 h-3.5" /> Add URLs
          </button>
        ) : (
          <Link to={`/admin/profiles/${profile.id}`} className="btn-secondary text-xs py-1.5 px-2.5 whitespace-nowrap">
            <Upload className="w-3.5 h-3.5" /> Upload
          </Link>
        )}
      </td>
    </tr>
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



function NeedsAttentionPanel({ jobs }: { jobs: AdminDashboard['today_jobs'] }) {
  const stuck = jobs.filter((j) => j.status === 'needs_manual_jd' || j.status === 'error')
  if (stuck.length === 0) return null
  // Expired/skip first (terminal), then recoverable ones.
  const ordered = [...stuck].sort(
    (a, b) => (a.fail_reason === 'expired' ? 0 : 1) - (b.fail_reason === 'expired' ? 0 : 1),
  )
  return (
    <div className="mb-6">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-2">
        Needs attention
        <span className="text-gray-400 normal-case font-normal">· {stuck.length} job{stuck.length > 1 ? 's' : ''} couldn’t be tailored automatically</span>
      </h2>
      <ul className="space-y-1.5">
        {ordered.map((j) => {
          const fr = j.fail_reason ? FAIL_REASON[j.fail_reason] : null
          const tone = fr?.tone === 'red'
            ? 'border-rose-300 bg-rose-50/60'
            : 'border-amber-300 bg-amber-50/60'
          const chip = fr?.tone === 'red'
            ? 'bg-rose-100 text-rose-800 border-rose-200'
            : 'bg-amber-100 text-amber-800 border-amber-200'
          return (
            <li key={j.job_id} className={clsx('flex items-start gap-3 px-3 py-2 rounded-md border', tone)}>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">
                  {j.company || '—'}
                  <span className="ml-2 text-xs font-normal text-gray-500">{j.profile_name}</span>
                </p>
                {j.title && <p className="text-xs text-gray-600 truncate">{j.title}</p>}
                {j.error_message && <p className="text-[11px] text-gray-600 mt-0.5 line-clamp-2">{j.error_message}</p>}
              </div>
              {fr && (
                <span className={clsx('inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap', chip)}>
                  {fr.label} · {fr.action}
                </span>
              )}
              <Link to={`/admin/batches/${j.batch_id}`} className="btn-secondary text-xs py-1 px-2.5 whitespace-nowrap">Open →</Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}


const UPLOAD_VERDICT = {
  tailored: { label: 'Verified', icon: '✓', chip: 'bg-emerald-100 text-emerald-800 border-emerald-200', row: 'border-emerald-200 bg-emerald-50/50' },
  base:     { label: 'Base resume — not tailored', icon: '⚠', chip: 'bg-amber-100 text-amber-800 border-amber-200', row: 'border-amber-300 bg-amber-50/60' },
  other:    { label: 'Unrecognized file', icon: '✗', chip: 'bg-rose-100 text-rose-800 border-rose-200', row: 'border-rose-300 bg-rose-50/60' },
} as const

function UploadVerificationPanel({ jobs }: { jobs: AdminDashboard['today_jobs'] }) {
  // Only jobs where the extension actually observed an upload have a verdict.
  const observed = jobs.filter((j) => j.upload_match === 'tailored' || j.upload_match === 'base' || j.upload_match === 'other')
  if (observed.length === 0) return null

  const verified = observed.filter((j) => j.upload_match === 'tailored')
  // Surface the ones that need attention first.
  const problems = observed
    .filter((j) => j.upload_match !== 'tailored')
    .sort((a, b) => (a.upload_match === 'other' ? 0 : 1) - (b.upload_match === 'other' ? 0 : 1))

  return (
    <div className="mb-6">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-2">
        Resume uploads
        <span className="text-gray-400 normal-case font-normal">· what bidders actually submitted today</span>
      </h2>

      <div className="flex items-center gap-2 flex-wrap mb-3">
        <span className={clsx('inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full border', UPLOAD_VERDICT.tailored.chip)}>
          {UPLOAD_VERDICT.tailored.icon} {verified.length} verified
        </span>
        {problems.some((j) => j.upload_match === 'base') && (
          <span className={clsx('inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full border', UPLOAD_VERDICT.base.chip)}>
            {UPLOAD_VERDICT.base.icon} {problems.filter((j) => j.upload_match === 'base').length} base resume
          </span>
        )}
        {problems.some((j) => j.upload_match === 'other') && (
          <span className={clsx('inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full border', UPLOAD_VERDICT.other.chip)}>
            {UPLOAD_VERDICT.other.icon} {problems.filter((j) => j.upload_match === 'other').length} unrecognized
          </span>
        )}
      </div>

      {problems.length > 0 ? (
        <ul className="space-y-1.5">
          {problems.map((j) => {
            const v = UPLOAD_VERDICT[j.upload_match as 'base' | 'other']
            return (
              <li key={j.job_id} className={clsx('flex items-center gap-3 px-3 py-2 rounded-md border', v.row)}>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">
                    {j.company || '—'}
                    <span className="ml-2 text-xs font-normal text-gray-500">{j.profile_name}</span>
                  </p>
                  {j.title && <p className="text-xs text-gray-600 truncate">{j.title}</p>}
                </div>
                <span className={clsx('inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border whitespace-nowrap', v.chip)}>
                  {v.icon} {v.label}
                </span>
                <Link to={`/admin/batches/${j.batch_id}`} className="btn-secondary text-xs py-1 px-2.5 whitespace-nowrap">
                  Open →
                </Link>
              </li>
            )
          })}
        </ul>
      ) : (
        <div className="flex items-center gap-2 text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2">
          <CheckCircle2 className="w-4 h-4" /> Every observed upload today was the correct tailored resume.
        </div>
      )}
    </div>
  )
}


function DuplicatesDialog({
  result, onClose,
}: {
  result: {
    batch_id: number | null
    added: number
    skipped_existing?: number
    duplicates?: Array<{
      url: string
      job_id: number
      batch_id: number
      status: string
      application_status: string
      applied_at: string | null
      days_since_applied: number | null
      apply_count: number
      company: string | null
      title: string | null
    }>
  }
  onClose: () => void
}) {
  const dups = result.duplicates || []
  const appliedDups = dups.filter((d) => d.application_status === 'applied')
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={onClose}>
      <div className="card w-full max-w-2xl p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-semibold text-gray-900 text-lg">
              {result.added > 0
                ? `Queued ${result.added} new — ${dups.length} already in system`
                : `${dups.length} URLs already in system`}
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {appliedDups.length > 0
                ? `${appliedDups.length} previously applied — may be reposts. Click through to mark “+1 again” on any you want to re-apply to.`
                : `These URLs were already submitted for this profile.`}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none ml-3">✕</button>
        </div>
        <ul className="space-y-1.5 max-h-[400px] overflow-y-auto">
          {dups.map((d) => {
            const ago = d.applied_at
              ? (d.days_since_applied === 0 ? 'today'
                : d.days_since_applied === 1 ? 'yesterday'
                : `${d.days_since_applied}d ago`)
              : null
            const tone = d.application_status === 'applied'
              ? 'border-emerald-200 bg-emerald-50/40'
              : d.application_status === 'error' || d.application_status === 'unavailable' || d.application_status === 'not_remote'
              ? 'border-amber-200 bg-amber-50/40'
              : 'border-slate-200 bg-slate-50/60'
            return (
              <li key={d.job_id} className={`flex items-center gap-3 px-3 py-2 rounded-md border ${tone}`}>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">{d.company || '—'}</p>
                  {d.title && <p className="text-xs text-gray-600 truncate">{d.title}</p>}
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {d.application_status === 'applied' ? `✓ Applied ${ago}` : `· ${d.application_status.replace('_',' ')}`}
                    {d.apply_count > 1 && <span className="ml-1.5 font-bold text-emerald-700">{d.apply_count}×</span>}
                  </p>
                </div>
                <Link to={`/admin/batches/${d.batch_id}`}
                      onClick={onClose}
                      className="btn-secondary text-xs py-1 px-2.5 whitespace-nowrap">
                  Open →
                </Link>
              </li>
            )
          })}
        </ul>
        <div className="flex items-center justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-primary text-sm">
            {result.added > 0 ? `Open new batch (${result.added})` : 'Close'}
          </button>
        </div>
      </div>
    </div>
  )
}
