import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type User } from '@/lib/api'
import { Alert } from '@/components/ui'

export default function Setup() {
  const [sp] = useSearchParams()
  const token = sp.get('token') || ''
  const nav = useNavigate()
  const qc = useQueryClient()

  const peek = useQuery({
    queryKey: ['setup-peek', token],
    queryFn: () => api.get<{ email: string }>(`/api/setup/peek?token=${encodeURIComponent(token)}`),
    enabled: !!token,
    retry: false,
  })

  const [pw, setPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const submit = useMutation({
    mutationFn: () => api.post<{ user: User }>('/api/setup', { token, password: pw, confirm }),
    onSuccess: (data) => {
      qc.setQueryData(['me'], data.user)
      nav(data.user.role === 'admin' ? '/admin' : '/my')
    },
  })

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div
            className="inline-flex items-center justify-center w-12 h-12 rounded-2xl text-white text-xl font-bold mb-4 shadow-lg"
            style={{ background: 'linear-gradient(135deg,#6366f1,#4f46e5)' }}
          >R</div>
          <h1 className="text-2xl font-bold text-gray-900">Set your password</h1>
          <p className="text-sm text-gray-500 mt-1">Resume Builder</p>
        </div>

        <div className="card p-6">
          {!token || peek.isError ? (
            <Alert variant="error">Invite link is invalid or expired. Ask your admin for a new one.</Alert>
          ) : peek.isLoading ? (
            <p className="text-sm text-gray-400">Verifying link…</p>
          ) : (
            <>
              <p className="text-sm text-gray-600 mb-5">
                Setting a password for <span className="font-semibold text-gray-800">{peek.data!.email}</span>
              </p>
              <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit.mutate() }}>
                {submit.isError && <Alert variant="error">{(submit.error as Error).message}</Alert>}
                <div>
                  <label className="label">
                    New password <span className="text-gray-400 font-normal">(min 8 chars)</span>
                  </label>
                  <input type="password" required minLength={8} autoFocus className="input" placeholder="••••••••"
                         value={pw} onChange={(e) => setPw(e.target.value)} />
                </div>
                <div>
                  <label className="label">Confirm password</label>
                  <input type="password" required minLength={8} className="input" placeholder="••••••••"
                         value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                </div>
                <button disabled={submit.isPending} className="btn-primary w-full py-2.5">
                  {submit.isPending ? 'Saving…' : 'Set password & sign in'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
