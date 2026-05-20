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
 * 7-day heatmap — N small rounded squares, intensity scaled to the max value.
 * Reads much better than a sparkline when the data is spiky / sparse.
 */
export function WeekHeatmap({
  data,
  dates,
  color = 'indigo',
  size = 18,
  gap = 3,
}: {
  data: number[]
  dates?: string[]
  color?: 'indigo' | 'emerald' | 'amber' | 'rose' | 'violet' | 'sky' | 'fuchsia'
  size?: number
  gap?: number
}) {
  const max = Math.max(1, ...data)
  // Tailwind-equivalent hex stops per color, light → dark.
  const stops: Record<string, string[]> = {
    indigo:  ['#eef2ff', '#c7d2fe', '#a5b4fc', '#818cf8', '#6366f1', '#4f46e5'],
    emerald: ['#ecfdf5', '#a7f3d0', '#6ee7b7', '#34d399', '#10b981', '#059669'],
    amber:   ['#fffbeb', '#fde68a', '#fcd34d', '#fbbf24', '#f59e0b', '#d97706'],
    rose:    ['#fff1f2', '#fecdd3', '#fda4af', '#fb7185', '#f43f5e', '#e11d48'],
    violet:  ['#f5f3ff', '#ddd6fe', '#c4b5fd', '#a78bfa', '#8b5cf6', '#7c3aed'],
    sky:     ['#f0f9ff', '#bae6fd', '#7dd3fc', '#38bdf8', '#0ea5e9', '#0284c7'],
    fuchsia: ['#fdf4ff', '#f5d0fe', '#f0abfc', '#e879f9', '#d946ef', '#c026d3'],
  }
  const palette = stops[color]
  const todayIdx = data.length - 1
  return (
    <div className="flex items-center" style={{ gap }}>
      {data.map((v, i) => {
        // Bucket into 6 intensity levels: 0 → empty, 1..5 → palette[1..5].
        const bucket = v === 0 ? 0 : Math.max(1, Math.ceil((v / max) * 5))
        const bg = palette[bucket]
        const isToday = i === todayIdx
        const tooltip = dates?.[i] ? `${dates[i]}: ${v}` : String(v)
        return (
          <div
            key={i}
            title={tooltip}
            className={clsx(
              'rounded-[4px] transition-all',
              isToday && 'ring-2 ring-offset-1',
            )}
            style={{
              width: size, height: size, background: bg,
              ...(isToday ? { boxShadow: `0 0 0 2px ${palette[5]}` } : {}),
            }}
          />
        )
      })}
    </div>
  )
}


/**
 * Tiny SVG donut showing pct with a center number. Lighter than RingChart.
 */
export function MiniDonut({
  pct,
  size = 44,
  stroke = 5,
  color = '#6366f1',
  trackColor = '#e2e8f0',
  label,
}: {
  pct: number          // 0–100
  size?: number
  stroke?: number
  color?: string
  trackColor?: string
  label?: string | number
}) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const p = Math.max(0, Math.min(100, pct))
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={trackColor} strokeWidth={stroke} />
        <circle
          cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - p/100)}
          className="transition-all duration-500"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-[10px] font-bold text-gray-700 tabular-nums">
          {label != null ? label : `${Math.round(p)}%`}
        </span>
      </div>
    </div>
  )
}


/**
 * Auto-colored avatar from a name. Initial + gradient based on a hash so the
 * same profile always renders the same color.
 */
export function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  const initial = (name || '?').trim().charAt(0).toUpperCase() || '?'
  // Deterministic hash → palette index.
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0
  const palettes = [
    ['#818cf8', '#4f46e5'],   // indigo
    ['#34d399', '#059669'],   // emerald
    ['#fbbf24', '#d97706'],   // amber
    ['#fb7185', '#e11d48'],   // rose
    ['#a78bfa', '#7c3aed'],   // violet
    ['#38bdf8', '#0284c7'],   // sky
    ['#e879f9', '#c026d3'],   // fuchsia
  ]
  const [a, b] = palettes[Math.abs(hash) % palettes.length]
  return (
    <div
      className="rounded-full grid place-items-center text-white font-bold shadow-sm flex-shrink-0"
      style={{
        width: size, height: size,
        fontSize: size * 0.42,
        background: `linear-gradient(135deg, ${a}, ${b})`,
      }}
      title={name}
    >
      {initial}
    </div>
  )
}


/**
 * Deterministic palette key (matches Avatar) so the per-profile heatmap
 * can be tinted to that profile's color.
 */
export function paletteForName(name: string): 'indigo' | 'emerald' | 'amber' | 'rose' | 'violet' | 'sky' | 'fuchsia' {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0
  const keys = ['indigo', 'emerald', 'amber', 'rose', 'violet', 'sky', 'fuchsia'] as const
  return keys[Math.abs(hash) % keys.length]
}


/**
 * Gradient stat tile for the dashboard top strip.
 */
export function StatTile({
  label, value, sublabel, tone, icon,
}: {
  label: string
  value: number | string
  sublabel?: string
  tone: 'brand' | 'emerald' | 'amber'
  icon?: React.ReactNode
}) {
  const gradients = {
    brand:   'from-indigo-500 to-violet-600',
    emerald: 'from-emerald-500 to-teal-600',
    amber:   'from-amber-400 to-orange-500',
  }
  return (
    <div className={clsx(
      'relative overflow-hidden rounded-xl text-white shadow-md px-4 py-3 flex-1 min-w-[180px]',
      'bg-gradient-to-br', gradients[tone],
    )}>
      <div className="absolute -right-2 -bottom-2 opacity-20 text-white" style={{ fontSize: 80, lineHeight: 1 }}>
        {icon}
      </div>
      <div className="relative">
        <p className="text-[10px] uppercase tracking-wider font-semibold opacity-90">{label}</p>
        <p className="text-2xl font-bold tabular-nums mt-0.5 leading-tight">{value}</p>
        {sublabel && <p className="text-[11px] opacity-80 mt-0.5">{sublabel}</p>}
      </div>
    </div>
  )
}


/**
 * Pipeline-status orb. Replaces the text chip; a single colored disc whose
 * tone and icon encode the row's lifecycle. Pair with row-level background
 * tints for an at-a-glance scan.
 */
export function StatusOrb({
  status, size = 22,
}: {
  status: string
  size?: number
}) {
  type Tone = { bg: string; fg: string; icon: string; label: string; pulse?: boolean }
  const tones: Record<string, Tone> = {
    done:             { bg: '#10b981', fg: '#fff', icon: '✓', label: 'tailored' },
    applied:          { bg: '#10b981', fg: '#fff', icon: '✓', label: 'applied'  },
    pending:          { bg: '#cbd5e1', fg: '#475569', icon: '·', label: 'pending'   },
    fetching:         { bg: '#6366f1', fg: '#fff', icon: '↓', label: 'fetching',  pulse: true },
    analyzing:        { bg: '#6366f1', fg: '#fff', icon: '∿', label: 'analyzing', pulse: true },
    tailoring:        { bg: '#6366f1', fg: '#fff', icon: '✎', label: 'tailoring', pulse: true },
    needs_manual_jd:  { bg: '#f59e0b', fg: '#fff', icon: '?', label: 'needs JD' },
    error:            { bg: '#ef4444', fg: '#fff', icon: '✕', label: 'error' },
  }
  const t = tones[status] || { bg: '#cbd5e1', fg: '#475569', icon: '·', label: status }
  return (
    <span
      title={t.label}
      className={clsx(
        'inline-flex items-center justify-center rounded-full font-bold shadow-sm flex-shrink-0',
        t.pulse && 'animate-pulse',
      )}
      style={{
        width: size, height: size, background: t.bg, color: t.fg,
        fontSize: size * 0.55, lineHeight: 1,
      }}
    >
      {t.icon}
    </span>
  )
}


/**
 * Map a pipeline status to a row-background utility class. Subtle tints so
 * a row tells you its state without you reading the chip.
 */
export function rowTintForStatus(status: string): string {
  switch (status) {
    case 'error':            return 'bg-rose-50/50'
    case 'needs_manual_jd':  return 'bg-amber-50/50'
    case 'fetching':
    case 'analyzing':
    case 'tailoring':        return 'bg-indigo-50/40'
    case 'pending':          return 'bg-slate-50/60'
    default:                 return ''
  }
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
