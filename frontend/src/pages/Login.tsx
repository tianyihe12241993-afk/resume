import { useState } from 'react'
import { useNavigate, useSearchParams, Navigate } from 'react-router-dom'
import { useAuth, useLogin } from '@/hooks/useAuth'
import { Alert } from '@/components/ui'

export default function Login() {
  const [sp] = useSearchParams()
  const next = sp.get('next') || '/'
  const nav = useNavigate()
  const login = useLogin()
  const { data: user, isLoading } = useAuth()

  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')

  if (isLoading) return <div className="p-8 text-center text-gray-400 text-sm">Loading…</div>
  if (user) return <Navigate to={next.startsWith('/') ? next : '/'} replace />

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div
            className="inline-flex items-center justify-center w-12 h-12 rounded-2xl text-white text-xl font-bold mb-4 shadow-lg"
            style={{ background: 'linear-gradient(135deg,#6366f1,#4f46e5)' }}
          >R</div>
          <h1 className="text-2xl font-bold text-gray-900">Welcome back</h1>
          <p className="text-sm text-gray-500 mt-1">Sign in to Resume Builder</p>
        </div>

        <div className="card p-6">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              login.mutate({ email, password: pw }, {
                onSuccess: (data) =>
                  nav(next.startsWith('/') ? next : (data.user.role === 'admin' ? '/admin' : '/my')),
              })
            }}
          >
            {login.isError && <Alert variant="error">{(login.error as Error).message}</Alert>}

            <div>
              <label className="label">Email address</label>
              <input type="email" required autoFocus className="input" placeholder="you@example.com"
                     value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label className="label">Password</label>
              <input type="password" required className="input" placeholder="••••••••"
                     value={pw} onChange={(e) => setPw(e.target.value)} />
            </div>
            <button disabled={login.isPending} className="btn-primary w-full py-2.5">
              {login.isPending ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="mt-5 text-center text-xs text-gray-400">
          First time here? Your admin will share a setup link.
        </p>
      </div>
    </div>
  )
}
