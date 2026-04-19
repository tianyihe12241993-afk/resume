import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { api, type CalendarData } from '@/lib/api'

export default function CalendarPage() {
  const [sp, setSp] = useSearchParams()
  const y = sp.get('year'); const m = sp.get('month')
  const qs = y && m ? `?year=${y}&month=${m}` : ''

  const { data } = useQuery({
    queryKey: ['admin/calendar', y, m],
    queryFn: () => api.get<CalendarData>(`/api/admin/calendar${qs}`),
  })
  if (!data) return <div className="text-center text-gray-400 text-sm">Loading…</div>

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          {data.month_name} {data.year}
          <span className="text-sm font-normal text-gray-400 ml-2">US Pacific</span>
        </h1>
        <div className="flex items-center gap-1">
          <button onClick={() => setSp({ year: String(data.prev.year), month: String(data.prev.month) })}
                  className="btn-secondary text-sm px-3 py-1.5">← Prev</button>
          <button onClick={() => setSp({})} className="btn-secondary text-sm px-3 py-1.5">Today</button>
          <button onClick={() => setSp({ year: String(data.next.year), month: String(data.next.month) })}
                  className="btn-secondary text-sm px-3 py-1.5">Next →</button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="grid grid-cols-7 bg-slate-50 border-b border-slate-200">
          {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map((d) => (
            <div key={d} className="px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase tracking-wider border-r last:border-r-0">{d}</div>
          ))}
        </div>
        {data.weeks.map((week, wi) => (
          <div key={wi} className="grid grid-cols-7 border-b last:border-b-0">
            {week.map((d) => {
              const { totals, batches } = d
              const hit = totals.tailored > 0 && totals.applied >= totals.tailored
              return (
                <div key={d.date}
                     className={clsx(
                       'min-h-[120px] p-2 border-r last:border-r-0 flex flex-col',
                       !d.in_month && 'bg-slate-50/60',
                       d.is_today && 'bg-brand-50',
                     )}>
                  <div className="flex items-center justify-between mb-1">
                    <div className={clsx('text-xs font-semibold',
                      !d.in_month ? 'text-gray-300' : d.is_today ? 'text-brand-600' : 'text-gray-600')}>
                      {d.day}
                    </div>
                    {d.in_month && totals.tailored > 0 && (
                      <div className={clsx('text-[10px] font-bold tabular-nums',
                        hit ? 'text-green-600' : 'text-brand-600')}>
                        {totals.applied}/{totals.tailored}
                      </div>
                    )}
                  </div>

                  {d.in_month && totals.tailored > 0 && (
                    <div className="h-1 bg-slate-200 rounded-full overflow-hidden mb-1.5">
                      <div
                        className={clsx('h-full rounded-full transition-all',
                          hit ? 'bg-green-500' : 'bg-brand-500')}
                        style={{ width: `${Math.min(100, totals.percent)}%` }}
                      />
                    </div>
                  )}

                  <div className="flex-1 space-y-0.5">
                    {batches.map((b) => {
                      const bHit = b.done > 0 && b.applied >= b.done
                      return (
                        <Link key={b.id} to={`/admin/batches/${b.id}`}
                              className={clsx(
                                'block text-[10.5px] leading-tight rounded px-1.5 py-0.5 transition truncate',
                                bHit ? 'bg-green-100 text-green-800 hover:bg-green-200'
                                     : 'bg-brand-100 text-brand-800 hover:bg-brand-200',
                              )}>
                          <span className="font-semibold">{b.profile_name}</span>
                          <span className="ml-1 opacity-70">{b.applied}/{b.done}</span>
                        </Link>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      <p className="mt-3 text-xs text-gray-400">
        Each day shows applied / tailored. Green = all tailored resumes applied.
      </p>
    </>
  )
}
