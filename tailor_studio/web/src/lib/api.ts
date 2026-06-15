export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
    ...init,
  })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText
    throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data as T
}

export const api = {
  get:  <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? null : JSON.stringify(body) }),
  upload: async <T>(path: string, file: File): Promise<T> => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(path, { method: 'POST', credentials: 'include', body: fd })
    const text = await res.text()
    const data = text ? JSON.parse(text) : null
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || res.statusText
      throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
    return data as T
  },
}

// ── Types ────────────────────────────────────────────────────────────────

export interface User {
  id: number
  email: string
  name: string | null
  role: 'admin' | 'bidder'
  password_set: boolean
  created_at: string
}

export interface Profile {
  id: number
  name: string
  base_resume_filename: string | null
  has_base_resume: boolean
  batch_count: number
  tailor_prompt: string
  uses_default_prompt: boolean
  created_at: string
}

export type JobStatus = 'pending' | 'fetching' | 'analyzing' | 'tailoring' | 'done' | 'needs_manual_jd' | 'error'

export interface CoverageTerm { term: string; weight: number }

export interface CoverageReport {
  exact_count: number
  adjacent_count?: number
  gap_count: number
  weighted_coverage: number
  similarity?: { tf_cosine: number; jaccard: number }
  covered_exact?: CoverageTerm[]
  gap?: CoverageTerm[]
  must_have_phrases?: string[]
}

export interface Job {
  id: number
  url: string
  status: JobStatus
  company: string | null
  title: string | null
  location: string | null
  work_type: 'remote' | 'hybrid' | 'onsite' | null
  description: string | null
  error_message: string | null
  application_status: string
  applied_at: string | null
  application_note: string | null
  application_source?: string | null
  apply_count?: number
  has_docx: boolean
  download_count: number
  upload_filename?: string | null
  upload_match?: 'tailored' | 'base' | 'other' | null
  upload_observed_at?: string | null
  note?: string | null
  note_updated_at?: string | null
  note_seen_at?: string | null
  has_unread_note?: boolean
  // Constrained-rewrite pipeline outputs (only present after status === 'done').
  coverage_initial?: CoverageReport | null
  coverage_final?: CoverageReport | null
  claimed_terms?: string[]
}

export interface BatchSummary {
  total: number; done: number; in_flight: number; needs_jd: number; errors: number
  percent: number; applied: number; applied_percent: number
}

export interface ProfileStatus {
  profile: { id: number; name: string; has_base_resume: boolean }
  today_batch: { id: number; created_at: string } | null
  summary: BatchSummary    // today only
  week: BatchSummary       // last 7 PT days
  trend: number[]          // last 7 days applied count, oldest → newest
}

export interface TodayJobRow {
  job_id: number
  batch_id: number
  profile_id: number
  profile_name: string
  company: string | null
  title: string | null
  location: string | null
  work_type: 'remote' | 'hybrid' | 'onsite' | null
  url: string
  status: JobStatus
  application_status: string
  upload_match: 'tailored' | 'base' | 'other' | null
  apply_count: number
  applied_at: string | null
  created_at: string
  has_unread_note: boolean
}

export interface AdminDashboard {
  now_pst: string; today: string
  profile_statuses: ProfileStatus[]
  agg: BatchSummary
  agg_trend: number[]
  trend_dates: string[]
  today_jobs: TodayJobRow[]
  ready_profiles: Profile[]
  has_any_profile: boolean
}

export interface ProfileDetail {
  profile: Profile
  accesses: { id: number; user: User; invite_url: string | null }[]
  batches: { id: number; created_at: string; url_count: number }[]
}

export interface BidderDetail {
  bidder: User
  profiles: Profile[]
  invite_url: string | null
}

export interface BatchDetail {
  batch: { id: number; created_at: string }
  profile: { id: number; name: string }
  jobs: Job[]
  summary: BatchSummary
}

export interface CalendarDay {
  date: string; day: number; in_month: boolean; is_today: boolean
  batches: {
    id: number; profile_id: number; profile_name: string
    url_count: number; done: number; applied: number
  }[]
  totals: { applied: number; tailored: number; percent: number }
}

export interface CalendarData {
  year: number; month: number; month_name: string
  weeks: CalendarDay[][]
  today: string
  prev: { year: number; month: number }
  next: { year: number; month: number }
}

export interface MyProfile {
  profile: Profile
  batches: {
    id: number
    created_at: string
    total: number
    done: number
    needs_jd: number
    in_flight: number
    errors: number
  }[]
}

export interface MyBatch {
  batch: { id: number; created_at: string }
  profile: { id: number; name: string }
  jobs: Job[]                // done resumes (downloadable)
  pending_jobs: Job[]        // still in progress / needs JD / errored
  applied: number
}
