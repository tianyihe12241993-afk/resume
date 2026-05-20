import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardList, Save } from 'lucide-react'
import { api, type Profile } from '@/lib/api'
import { Avatar } from '@/components/charts'
import clsx from 'clsx'

interface Answers {
  personal: {
    first_name: string; last_name: string; email: string; phone: string
    linkedin_url: string; github_url: string; portfolio_url: string
    address_city: string; address_state: string; address_country: string; address_zip: string
  }
  professional: {
    current_company: string; current_title: string; years_of_experience: string | number
  }
  eligibility: {
    us_authorized: boolean | null; need_sponsorship: boolean | null
    willing_to_relocate: boolean | null; willing_remote: boolean | null
    salary_expectation: string; preferred_start: string
  }
  demographics: {
    gender: string; race: string; veteran: string; disability: string
  }
}

export default function AnswersPage() {
  const qc = useQueryClient()
  // Profile list — drives the picker.
  const { data: profilesData } = useQuery({
    queryKey: ['admin/profiles'],
    queryFn: () => api.get<{ profiles: Profile[] }>('/api/admin/profiles'),
  })
  const profiles = profilesData?.profiles || []

  // Selected profile — persisted to localStorage so a refresh keeps focus.
  const [pid, setPid] = useState<number | null>(() => {
    const stored = localStorage.getItem('answers.profileId')
    return stored ? Number(stored) : null
  })
  useEffect(() => {
    if (pid == null && profiles.length > 0) setPid(profiles[0].id)
  }, [profiles, pid])
  useEffect(() => {
    if (pid != null) localStorage.setItem('answers.profileId', String(pid))
  }, [pid])

  const { data, isLoading } = useQuery({
    enabled: pid != null,
    queryKey: ['admin/answers', pid],
    queryFn: () => api.get<{ profile_id: number; answers: Answers }>(
      `/api/admin/answers?profile_id=${pid}`),
  })

  const [draft, setDraft] = useState<Answers | null>(null)
  useEffect(() => { if (data) setDraft(data.answers) }, [data])

  const save = useMutation({
    mutationFn: (answers: Answers) =>
      api.post<{ profile_id: number; answers: Answers }>(
        '/api/admin/answers', { profile_id: pid, answers }),
    onSuccess: (res) => {
      qc.setQueryData(['admin/answers', pid], res)
      setDraft(res.answers)
    },
  })

  function set<K extends keyof Answers>(section: K, key: keyof Answers[K], value: any) {
    setDraft((d) => d && ({ ...d, [section]: { ...d[section], [key]: value } }))
  }

  const dirty = draft && JSON.stringify(draft) !== JSON.stringify(data?.answers || {})

  return (
    <>
      <div className="flex items-end justify-between mb-4 flex-wrap gap-3">
        <div>
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-0.5 flex items-center gap-1.5">
            <ClipboardList className="w-3 h-3" /> Answer library
          </p>
          <h1 className="text-2xl font-bold text-gray-900">Standard answers</h1>
          <p className="text-sm text-gray-500 mt-1">
            Per-profile. The extension's "Fill form" button uses the answer library of your main profile.
          </p>
        </div>
        <button
          disabled={!dirty || save.isPending || draft == null}
          onClick={() => draft && save.mutate(draft)}
          className="btn-primary"
        >
          <Save className="w-4 h-4" />
          {save.isPending ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
        </button>
      </div>

      {/* Profile picker chips */}
      {profiles.length > 0 && (
        <div className="card px-3 py-2 mb-4 flex items-center gap-2 flex-wrap">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-gray-500 mr-1">Profile</p>
          {profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => setPid(p.id)}
              className={clsx(
                'inline-flex items-center gap-1.5 text-xs font-medium pl-1 pr-2.5 py-1 rounded-full border transition',
                pid === p.id
                  ? 'bg-brand-50 text-brand-800 border-brand-300 shadow-sm'
                  : 'bg-white text-gray-600 border-gray-200 hover:bg-slate-50',
              )}
            >
              <Avatar name={p.name} size={18} />
              <span className="truncate max-w-[140px]">{p.name}</span>
            </button>
          ))}
        </div>
      )}

      {isLoading || !draft ? (
        <div className="text-center text-gray-400 text-sm">Loading…</div>
      ) : (
        <>
          <Section title="Personal">
            <Two>
              <Field label="First name" value={draft.personal.first_name}
                     onChange={(v) => set('personal', 'first_name', v)} />
              <Field label="Last name" value={draft.personal.last_name}
                     onChange={(v) => set('personal', 'last_name', v)} />
            </Two>
            <Two>
              <Field label="Email" type="email" value={draft.personal.email}
                     onChange={(v) => set('personal', 'email', v)} />
              <Field label="Phone" value={draft.personal.phone}
                     onChange={(v) => set('personal', 'phone', v)} />
            </Two>
            <Two>
              <Field label="LinkedIn URL" value={draft.personal.linkedin_url}
                     onChange={(v) => set('personal', 'linkedin_url', v)} />
              <Field label="GitHub URL" value={draft.personal.github_url}
                     onChange={(v) => set('personal', 'github_url', v)} />
            </Two>
            <Field label="Portfolio / website" value={draft.personal.portfolio_url}
                   onChange={(v) => set('personal', 'portfolio_url', v)} />
            <Two>
              <Field label="City" value={draft.personal.address_city}
                     onChange={(v) => set('personal', 'address_city', v)} />
              <Field label="State / region" value={draft.personal.address_state}
                     onChange={(v) => set('personal', 'address_state', v)} />
            </Two>
            <Two>
              <Field label="Country" value={draft.personal.address_country}
                     onChange={(v) => set('personal', 'address_country', v)} />
              <Field label="ZIP / postal" value={draft.personal.address_zip}
                     onChange={(v) => set('personal', 'address_zip', v)} />
            </Two>
          </Section>

          <Section title="Professional">
            <Two>
              <Field label="Current company" value={draft.professional.current_company}
                     onChange={(v) => set('professional', 'current_company', v)} />
              <Field label="Current title" value={draft.professional.current_title}
                     onChange={(v) => set('professional', 'current_title', v)} />
            </Two>
            <Field label="Years of experience"
                   value={String(draft.professional.years_of_experience)}
                   onChange={(v) => set('professional', 'years_of_experience', v)} />
          </Section>

          <Section title="Eligibility">
            <YesNo label="Authorized to work in the U.S.?"
                   value={draft.eligibility.us_authorized}
                   onChange={(v) => set('eligibility', 'us_authorized', v)} />
            <YesNo label="Will you require visa sponsorship?"
                   value={draft.eligibility.need_sponsorship}
                   onChange={(v) => set('eligibility', 'need_sponsorship', v)} />
            <YesNo label="Willing to relocate?"
                   value={draft.eligibility.willing_to_relocate}
                   onChange={(v) => set('eligibility', 'willing_to_relocate', v)} />
            <YesNo label="Open to remote work?"
                   value={draft.eligibility.willing_remote}
                   onChange={(v) => set('eligibility', 'willing_remote', v)} />
            <Two>
              <Field label="Salary expectations"
                     value={draft.eligibility.salary_expectation}
                     onChange={(v) => set('eligibility', 'salary_expectation', v)} />
              <Field label="Preferred start date"
                     value={draft.eligibility.preferred_start}
                     onChange={(v) => set('eligibility', 'preferred_start', v)} />
            </Two>
          </Section>

          <Section title="EEO / voluntary self-identification">
            <p className="text-[11px] text-gray-400 -mt-2 mb-2">
              Optional — only fill if you want these auto-selected on EEO dropdowns. Use the wording the ATS uses (e.g. "Male", "Female", "Non-binary", "Decline to self-identify").
            </p>
            <Two>
              <Field label="Gender" value={draft.demographics.gender}
                     onChange={(v) => set('demographics', 'gender', v)} />
              <Field label="Race / ethnicity" value={draft.demographics.race}
                     onChange={(v) => set('demographics', 'race', v)} />
            </Two>
            <Two>
              <Field label="Veteran status" value={draft.demographics.veteran}
                     onChange={(v) => set('demographics', 'veteran', v)} />
              <Field label="Disability status" value={draft.demographics.disability}
                     onChange={(v) => set('demographics', 'disability', v)} />
            </Two>
          </Section>
        </>
      )}
    </>
  )
}


function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card p-4 mb-4">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">{title}</h2>
      <div className="space-y-3">{children}</div>
    </div>
  )
}

function Two({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
}

function Field({
  label, value, onChange, type = 'text',
}: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <label className="block text-sm">
      <span className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">{label}</span>
      <input type={type} className="input w-full" value={value || ''}
             onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

function YesNo({
  label, value, onChange,
}: { label: string; value: boolean | null; onChange: (v: boolean | null) => void }) {
  const btn = (v: boolean | null, txt: string, on: string) => (
    <button
      type="button"
      onClick={() => onChange(v)}
      className={
        'px-3 py-1.5 text-sm font-medium border rounded-md transition ' +
        (value === v
          ? on
          : 'bg-white text-gray-500 border-gray-300 hover:bg-slate-50')
      }
    >
      {txt}
    </button>
  )
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 border-b border-slate-100 last:border-b-0">
      <span className="text-sm text-gray-700">{label}</span>
      <div className="flex gap-1.5">
        {btn(true, 'Yes', 'bg-emerald-50 text-emerald-700 border-emerald-300')}
        {btn(false, 'No', 'bg-rose-50 text-rose-700 border-rose-300')}
        {btn(null, '—', 'bg-slate-100 text-slate-700 border-slate-300')}
      </div>
    </div>
  )
}
