import clsx from 'clsx'
import { AlertCircle, CheckCircle2, Info, AlertTriangle } from 'lucide-react'

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={clsx('card', className)}>{children}</div>
}

export function Alert({
  variant = 'info',
  children,
}: {
  variant?: 'info' | 'success' | 'warning' | 'error'
  children: React.ReactNode
}) {
  const styles = {
    info:    'bg-brand-50 text-brand-800 border-brand-200',
    success: 'bg-green-50 text-green-700 border-green-200',
    warning: 'bg-amber-50 text-amber-700 border-amber-200',
    error:   'bg-red-50 text-red-700 border-red-200',
  }
  const Icon = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: AlertCircle }[variant]
  return (
    <div className={clsx('flex items-start gap-2 text-sm border rounded-lg px-4 py-3', styles[variant])}>
      <Icon className="w-4 h-4 mt-0.5 shrink-0" />
      <div className="flex-1">{children}</div>
    </div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="card p-10 text-center text-sm text-gray-400 border-dashed">
      {children}
    </div>
  )
}

export function BackLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <a
      href={to}
      onClick={(e) => { e.preventDefault(); window.history.pushState({}, '', to); window.dispatchEvent(new PopStateEvent('popstate')); }}
      className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition"
    >
      <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7"/>
      </svg>
      {children}
    </a>
  )
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'pending',
  fetching: 'fetching',
  tailoring: 'tailoring',
  done: 'tailored',
  needs_manual_jd: 'needs jd',
  error: 'error',
}

export function Chip({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status.replace(/_/g, ' ')
  return <span className={`chip chip-${status}`}>{label}</span>
}

export function Progress({ percent, color = 'green' }: { percent: number; color?: 'green' | 'blue' }) {
  const grad = color === 'green'
    ? 'linear-gradient(90deg,#22c55e,#16a34a)'
    : 'linear-gradient(90deg,#60a5fa,#3b82f6)'
  return (
    <div className="progress-bar">
      <div className="progress-fill" style={{ width: `${percent}%`, background: grad }} />
    </div>
  )
}
