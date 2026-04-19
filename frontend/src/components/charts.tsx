import clsx from 'clsx'

/**
 * Radial / ring progress chart. Pure SVG, no dependencies.
 * Renders applied/target as a circle fill with % in the center.
 */
export function RingChart({
  value,
  target,
  size = 112,
  stroke = 10,
  color = 'brand',
  label,
}: {
  value: number
  target: number
  size?: number
  stroke?: number
  color?: 'brand' | 'green' | 'amber'
  label?: string
}) {
  const radius = (size - stroke) / 2
  const circ = 2 * Math.PI * radius
  const pct = target > 0 ? Math.min(1, value / target) : 0
  const hit = target > 0 && value >= target
  const gradId = `ring-${color}-${size}`

  const gradients = {
    brand:  [['#6366f1', 0], ['#4f46e5', 1]],
    green:  [['#22c55e', 0], ['#16a34a', 1]],
    amber:  [['#f59e0b', 0], ['#d97706', 1]],
  }
  const stops = gradients[hit ? 'green' : color]

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="1">
            <stop offset={`${(stops[0][1] as number) * 100}%`} stopColor={stops[0][0] as string} />
            <stop offset={`${(stops[1][1] as number) * 100}%`} stopColor={stops[1][0] as string} />
          </linearGradient>
        </defs>
        {/* track */}
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke="#e2e8f0" strokeWidth={stroke}
        />
        {/* value arc */}
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={`url(#${gradId})`} strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - pct)}
          className="transition-all duration-500"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={clsx(
          'text-xl font-bold tabular-nums leading-none',
          hit ? 'text-green-600' : 'text-gray-900',
        )}>
          {target > 0 ? Math.round(pct * 100) : 0}%
        </span>
        {label && <span className="text-[10px] text-gray-400 mt-1">{label}</span>}
      </div>
    </div>
  )
}

/**
 * Sparkline bar chart — small daily-trend visualization.
 */
export function Sparkline({
  data,
  dates,
  highlight,
  height = 40,
  color = '#6366f1',
}: {
  data: number[]
  dates?: string[]
  highlight?: number          // index to highlight (usually today)
  height?: number
  color?: string
}) {
  const max = Math.max(1, ...data)
  return (
    <div className="flex items-end gap-0.5 h-full" style={{ height }}>
      {data.map((v, i) => {
        const pct = (v / max) * 100
        const isHi = highlight === i
        const tooltip = dates?.[i] ? `${dates[i]}: ${v}` : String(v)
        return (
          <div
            key={i}
            title={tooltip}
            className="flex-1 rounded-sm transition-all relative group"
            style={{
              height: `${Math.max(2, pct)}%`,
              background: v === 0 ? '#e2e8f0' : color,
              opacity: v === 0 ? 0.5 : isHi ? 1 : 0.75,
              outline: isHi ? `2px solid ${color}` : 'none',
              outlineOffset: isHi ? 2 : 0,
            }}
          />
        )
      })}
    </div>
  )
}

/**
 * Stacked pill showing counts of different status buckets in a single bar.
 */
export function StatusStack({
  segments,
  total,
  height = 8,
}: {
  segments: { value: number; color: string; label: string }[]
  total: number
  height?: number
}) {
  if (total === 0) {
    return (
      <div className="bg-slate-200 rounded-full" style={{ height }} />
    )
  }
  return (
    <div className="flex bg-slate-200 rounded-full overflow-hidden" style={{ height }}>
      {segments.map((s, i) => {
        if (s.value === 0) return null
        const pct = (s.value / total) * 100
        return (
          <div
            key={i}
            title={`${s.label}: ${s.value}`}
            className="transition-all"
            style={{ width: `${pct}%`, background: s.color }}
          />
        )
      })}
    </div>
  )
}
